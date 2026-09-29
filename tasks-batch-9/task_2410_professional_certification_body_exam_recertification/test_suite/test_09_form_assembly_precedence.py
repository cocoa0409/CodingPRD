"""Provenance outranks length when one assembly request breaks both rules."""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

HOME_PROGRAM = {"name": "Certified Practitioner X", "credential_code": "CPX",
                "domain_specs": [{"domain_code": "D1", "weight_pct": 100,
                                  "min_operational_items": 1}]}
FOREIGN_PROGRAM = {"name": "Certified Practitioner Y", "credential_code": "CPY",
                   "domain_specs": [{"domain_code": "D2", "weight_pct": 100,
                                     "min_operational_items": 1}]}


def _two_programmes_with_approved_items(api):
    home = fx.active_program(api, **HOME_PROGRAM)
    foreign = fx.active_program(api, **FOREIGN_PROGRAM)
    item_a = fx.approved_item(api, home["id"], stem="CPX item A")
    item_b = fx.approved_item(api, home["id"], stem="CPX item B")
    item_c = fx.approved_item(api, foreign["id"], domain_code="D2", stem="CPY item C")
    return home, foreign, item_a, item_b, item_c


class TestAssemblyRejectionPrecedence:
    """A two-item list for a one-position form, one item from another programme."""

    def test_foreign_item_outranks_the_wrong_form_length(self, api):
        """The list is both the wrong length and cites an item from another
        programme, and provenance is the answer.

        PRD §2.7: "Assembling a form whose item list is both the wrong length and
        contains an item from another program returns `ERR_ITEM_DOMAIN_MISMATCH`,
        not `ERR_FORM_LENGTH_MISMATCH`, because provenance sits at layer 22 and
        length at layer 35."

        Design: Difficulty/priority_pair_validation_conflict/form_item_domain_mismatch_outranks_form_length_mismatch_on_one_request
        """
        home, _foreign, item_a, _item_b, item_c = _two_programmes_with_approved_items(api)

        refused = api.create_form(
            f.create_form_payload(home["id"], [item_a["id"], item_c["id"]]),
            fx.PSYCHOMETRICIAN)

        validate_error(refused, ApiErrorId.ERR_ITEM_DOMAIN_MISMATCH.value, 422)

    def test_removing_the_foreign_item_exposes_the_length_rule(self, api):
        """With both items home-grown the lower-ranked length rule becomes
        observable, which proves it was live all along.

        PRD §2.7: "**The first violated rule wins and its error is returned; no
        later rule is evaluated.**"

        PRD §2.7: "**Form length.** The number of entries in `item_ids` equals the
        program's `form_length` exactly → otherwise `ERR_FORM_LENGTH_MISMATCH`
        (422)."

        Design: Difficulty/priority_pair_validation_conflict/form_item_domain_mismatch_outranks_form_length_mismatch_on_one_request
        """
        home, _foreign, item_a, item_b, _item_c = _two_programmes_with_approved_items(api)

        refused = api.create_form(
            f.create_form_payload(home["id"], [item_a["id"], item_b["id"]]),
            fx.PSYCHOMETRICIAN)

        validate_error(refused, ApiErrorId.ERR_FORM_LENGTH_MISMATCH.value, 422)

    def test_neither_refusal_creates_a_form_and_the_correct_list_assembles(self, api):
        """Both refusals are total, and a single home-grown item assembles cleanly.

        PRD §2.10: "Operations that bring a new resource into existence answer with
        **HTTP 201**."

        PRD §3.5: "A `Psychometrician` assembles a form against an active program's
        blueprint, supplying the `program_id`, a `form_code` that is unique within
        that program, the ordered `item_ids` that constitute the form".

        Design: Difficulty/priority_pair_validation_conflict/form_item_domain_mismatch_outranks_form_length_mismatch_on_one_request
        """
        home, _foreign, item_a, item_b, item_c = _two_programmes_with_approved_items(api)

        api.create_form(f.create_form_payload(home["id"], [item_a["id"], item_c["id"]]),
                        fx.PSYCHOMETRICIAN)
        api.create_form(f.create_form_payload(home["id"], [item_a["id"], item_b["id"]]),
                        fx.PSYCHOMETRICIAN)
        forms, _meta = validate_paginated(
            api.list_forms(fx.PSYCHOMETRICIAN, {"program_id": home["id"]}))
        assert forms == []

        assembled = validate_success(api.create_form(
            f.create_form_payload(home["id"], [item_a["id"]]), fx.PSYCHOMETRICIAN), 201)

        assert assembled["status"] == "ASSEMBLED"
        assert assembled["item_ids"] == [item_a["id"]]
        assert assembled["scored_item_count"] == 1
        assert assembled["retired_item_count"] == 0
