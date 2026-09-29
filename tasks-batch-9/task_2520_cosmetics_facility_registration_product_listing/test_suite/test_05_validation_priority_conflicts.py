"""Single requests that violate two rules at once, where the normative
evaluation order decides which rejection the caller is shown.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import make_responsible_person_agent_headers
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


def _listing_already_moved_to_its_second_designee(api):
    """A DRAFT listing transferred once, so the pre-transfer version is stale.

    Returns the two designees, the listing, and the version captured before the
    transfer alongside the version left behind by it.
    """
    facility = X.create_registered_facility(
        api, facility_name="Trellis Cosmetics", owner_operator_name="Trellis Group",
        state_or_province="MN",
    )
    person_a = X.create_responsible_person(api, legal_name="Trellis Brands A")
    person_b = X.create_responsible_person(
        api, legal_name="Trellis Brands B", contact_email="b@trellis.example"
    )
    listing = X.create_draft_listing(
        api, facility["id"], person_a["id"],
        product_name="Trellis Hair Straightener",
        category_code="05G",
        product_form=K.PRODUCT_FORM_RINSE_OFF,
        label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
        label_contact_value="care@trellis.example",
    )
    version_before = listing["version"]

    moved = get_success_data(
        api.transfer_responsible_person(
            listing["id"],
            F.transfer_payload(person_b["id"], version_before),
            make_responsible_person_agent_headers(person_a["id"]),
        )
    )
    return {
        "person_a": person_a,
        "person_b": person_b,
        "listing_id": listing["id"],
        "version_before": version_before,
        "version_after": moved["version"],
        "agent_b": make_responsible_person_agent_headers(person_b["id"]),
    }


class TestStaleSnapshotOutranksRedundantTransferTarget:
    """ERR_STALE_LISTING_VERSION (412) beats ERR_TRANSFER_TARGET_SAME_PERSON (422)."""

    def test_the_first_transfer_relinks_the_listing_and_invalidates_the_snapshot(self, api):
        """Moving the designation relinks the product to the incoming designee and lifts
        the listing's version by one, which is what makes the caller's captured version
        stale; because the listing is a draft it holds no slot, so no count moves.

        PRD: "A successful transfer sets the listing's `responsible_person_id` to the incoming designee."
        PRD: "A transfer of a `DRAFT` or `RETURNED` listing moves no counts at all."

        Design: Difficulty/priority_pair_validation_conflict/stale_listing_version_outranks_same_person_transfer_target
        """
        state = _listing_already_moved_to_its_second_designee(api)

        listing = X.read_listing(api, state["listing_id"])
        assert listing["responsible_person_id"] == state["person_b"]["id"]
        assert state["version_after"] == state["version_before"] + 1
        assert listing["listing_status"] == K.LISTING_STATUS_DRAFT

        assert X.read_responsible_person(api, state["person_a"]["id"])[
            "active_designation_count"] == 0
        assert X.read_responsible_person(api, state["person_b"]["id"])[
            "active_designation_count"] == 0

    def test_the_stale_version_is_reported_ahead_of_the_redundant_target(self, api):
        """The replayed request violates both rules at once — its snapshot is a version
        behind and its incoming designee is already the one on the label — and the caller
        is told about the snapshot, because the stale-version checks are group eight while
        the same-person check sits in group fifteen.

        PRD: "The three stale-version checks of §2.7, in the order `ERR_STALE_FACILITY_VERSION`, `ERR_STALE_LISTING_VERSION`, `ERR_STALE_RECALL_VERSION`."
        PRD: "As §2.7 records, the stale-version rejection `ERR_STALE_LISTING_VERSION` (HTTP 412) is evaluated ahead of the listing-state check and well ahead of the capacity check."

        Design: Difficulty/priority_pair_validation_conflict/stale_listing_version_outranks_same_person_transfer_target
        """
        state = _listing_already_moved_to_its_second_designee(api)

        validate_error(
            api.transfer_responsible_person(
                state["listing_id"],
                F.transfer_payload(state["person_b"]["id"], state["version_before"]),
                state["agent_b"],
            ),
            E.ERR_STALE_LISTING_VERSION,
        )

        listing = X.read_listing(api, state["listing_id"])
        A.assert_version_is(listing, state["version_after"], "listing")
        assert listing["responsible_person_id"] == state["person_b"]["id"]

    def test_with_a_current_snapshot_the_same_person_rule_becomes_observable(self, api):
        """Replaying the identical request with the version the listing actually holds
        satisfies the state check, and only then does the lower-priority business rule
        about a redundant target surface.

        PRD: "Two further conditions apply in this order: the incoming `responsible_person_id` must differ from the listing's current one, or the request is refused with `ERR_TRANSFER_TARGET_SAME_PERSON` (HTTP 422); and the **incoming** designee's `active_designation_count` must be strictly below its `designation_cap`, or the request is refused with `ERR_DESIGNATION_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/stale_listing_version_outranks_same_person_transfer_target
        """
        state = _listing_already_moved_to_its_second_designee(api)

        validate_error(
            api.transfer_responsible_person(
                state["listing_id"],
                F.transfer_payload(state["person_b"]["id"], state["version_after"]),
                state["agent_b"],
            ),
            E.ERR_TRANSFER_TARGET_SAME_PERSON,
        )

        A.assert_version_is(
            X.read_listing(api, state["listing_id"]), state["version_after"], "listing"
        )


UNDISCLOSED_ALLERGEN_PCT = 0.0015


def _draft_listing_and_agent(api, facility_id, person_id, **listing_overrides):
    """A DRAFT listing under the given designee, with that designee's headers."""
    agent = make_responsible_person_agent_headers(person_id)
    listing = X.create_draft_listing(api, facility_id, person_id, **listing_overrides)
    return listing, agent


def _designee_at_cap_with_an_undisclosed_allergen(api):
    """One designee capped at a single slot, holding it, plus a second listing
    that is cleared for safety but carries an undisclosed fragrance allergen."""
    facility = X.create_registered_facility(
        api, facility_name="Kestrel Fragrance House", owner_operator_name="Kestrel LLC",
        facility_type="BOTH", state_or_province="NY",
    )
    person = X.create_responsible_person(
        api, legal_name="Kestrel Brands LLC", designation_cap=1
    )
    occupant, agent = _draft_listing_and_agent(
        api, facility["id"], person["id"],
        product_name="Kestrel Bath Oil",
        category_code="02C",
        product_form=K.PRODUCT_FORM_RINSE_OFF,
    )
    X.dossier_at_decision(api, occupant["id"], agent, X.PASSING_EVIDENCE, K.REVIEW_MODE_FULL)
    get_success_data(api.submit_listing(occupant["id"], agent))

    blocked, _agent = _draft_listing_and_agent(
        api, facility["id"], person["id"],
        product_name="Kestrel Blush Balm",
        category_code="07A",
        product_form=K.PRODUCT_FORM_LEAVE_ON,
    )
    ingredient = X.add_ingredient(
        api, blocked["id"], agent,
        F.allergen_ingredient_payload(concentration_pct=UNDISCLOSED_ALLERGEN_PCT),
    )
    X.dossier_at_decision(api, blocked["id"], agent, X.PASSING_EVIDENCE, K.REVIEW_MODE_FULL)
    return {
        "facility_id": facility["id"],
        "person_id": person["id"],
        "agent": agent,
        "occupant_id": occupant["id"],
        "blocked_id": blocked["id"],
        "ingredient": ingredient,
    }


class TestAllergenGapOutranksDesignationCapAtSubmit:
    """Both refusals are 422, but the safety gate is reported before the ceiling."""

    def test_the_slot_ledger_is_full_and_the_safety_gates_are_otherwise_satisfied(self, api):
        """The occupant listing fills the designee's single slot and turns it active, while
        the blocked listing is cleared for substantiation and fails only the disclosure
        derivation: one allergen at 0.0015 percent is at or above the leave-on threshold and
        is not named on the label.

        PRD: "`active_designation_count` in turn counts the listings designated to that party whose `listing_status` is `SUBMITTED` or `LISTED` — no other listing state occupies a designation slot."
        PRD: "From those flags, `undisclosed_allergen_count` is the number of ingredients whose `disclosure_required` is true while `label_disclosed` is false, and `allergen_disclosure_complete` is true exactly when that count is 0."

        Design: Difficulty/priority_pair_validation_conflict/allergen_disclosure_gap_outranks_designation_cap_at_submit
        """
        state = _designee_at_cap_with_an_undisclosed_allergen(api)

        designee = X.read_responsible_person(api, state["person_id"])
        assert designee["active_designation_count"] == 1
        assert designee["designation_cap"] == 1
        assert designee["status"] == K.RP_STATUS_ACTIVE

        assert state["ingredient"]["disclosure_required"] is True
        blocked = X.read_listing(api, state["blocked_id"])
        assert blocked["safety_status"] == K.SAFETY_STATUS_SUBSTANTIATED
        assert blocked["undisclosed_allergen_count"] == 1
        assert blocked["allergen_disclosure_complete"] is False

    def test_the_disclosure_gap_is_reported_and_not_the_capacity_ceiling(self, api):
        """The submission breaks the disclosure gate and the capacity ceiling in the same
        request; the caller is told about the allergen, because the four safety gates run
        before the designation-slot check.

        PRD: "Only then do the four safety gates run, in this fixed order: the listing's `safety_status` must be `SUBSTANTIATED`, failing which the submission is refused with `ERR_SUBSTANTIATION_NOT_ADEQUATE` (HTTP 422); `allergen_disclosure_complete` must be true, failing which it is refused with `ERR_ALLERGEN_DISCLOSURE_INCOMPLETE` (HTTP 422); the professional-use labelling condition must hold, failing which it is refused with `ERR_PROFESSIONAL_USE_LABEL_REQUIRED` (HTTP 422); and the label-contact condition must hold, failing which it is refused with `ERR_LABEL_CONTACT_REQUIRED` (HTTP 422)."
        PRD: "Last of all comes the capacity check on the designation slot, described below, which yields `ERR_DESIGNATION_CAP_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/allergen_disclosure_gap_outranks_designation_cap_at_submit
        """
        state = _designee_at_cap_with_an_undisclosed_allergen(api)

        validate_error(
            api.submit_listing(state["blocked_id"], state["agent"]),
            E.ERR_ALLERGEN_DISCLOSURE_INCOMPLETE,
        )

        assert X.read_listing(api, state["blocked_id"])["listing_status"] == (
            K.LISTING_STATUS_DRAFT
        )
        assert X.read_responsible_person(api, state["person_id"])[
            "active_designation_count"] == 1

    def test_once_the_allergen_is_named_the_capacity_rule_becomes_observable(self, api):
        """Ingredients are append-only, so the control is a separate listing built the same
        way with the allergen named on the label: it clears every safety gate and is then
        refused on the capacity ceiling, because a designee sitting exactly at its cap
        blocks the submission.

        PRD: "The **designation-slot capacity** check compares the designee that will hold the slot against its own ceiling: the current designee's `active_designation_count` must be strictly less than its `designation_cap`."
        PRD: "A designee sitting at exactly its cap blocks the submission."

        Design: Difficulty/priority_pair_validation_conflict/allergen_disclosure_gap_outranks_designation_cap_at_submit
        """
        state = _designee_at_cap_with_an_undisclosed_allergen(api)

        control, _agent = _draft_listing_and_agent(
            api, state["facility_id"], state["person_id"],
            product_name="Kestrel Blush Balm Control",
            category_code="07A",
            product_form=K.PRODUCT_FORM_LEAVE_ON,
        )
        disclosed = X.add_ingredient(
            api, control["id"], state["agent"],
            F.allergen_ingredient_payload(
                concentration_pct=UNDISCLOSED_ALLERGEN_PCT, label_disclosed=True
            ),
        )
        X.dossier_at_decision(
            api, control["id"], state["agent"], X.PASSING_EVIDENCE, K.REVIEW_MODE_FULL
        )

        assert disclosed["disclosure_required"] is True
        prepared = X.read_listing(api, control["id"])
        assert prepared["undisclosed_allergen_count"] == 0
        assert prepared["allergen_disclosure_complete"] is True

        validate_error(
            api.submit_listing(control["id"], state["agent"]),
            E.ERR_DESIGNATION_CAP_EXCEEDED,
        )
        assert X.read_listing(api, control["id"])["listing_status"] == K.LISTING_STATUS_DRAFT
