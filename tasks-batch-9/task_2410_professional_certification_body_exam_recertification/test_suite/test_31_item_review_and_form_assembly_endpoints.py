"""Peer review needs two outsiders, and assembly and rating each guard their own inputs."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.test_users import (
    ITEM_AUTHOR_ID,
    ITEM_REVIEWER_1_ID,
    ITEM_REVIEWER_2_ID,
    OUTSIDE_PANELIST_ID,
    PANELIST_IDS,
    make_item_specialist_headers,
    make_panelist_headers,
)

REVIEWER_1 = make_item_specialist_headers(ITEM_REVIEWER_1_ID)
REVIEWER_2 = make_item_specialist_headers(ITEM_REVIEWER_2_ID)
PANELIST_1 = make_panelist_headers(PANELIST_IDS[0])
PANELIST_2 = make_panelist_headers(PANELIST_IDS[1])
TWO_PANELLISTS = [PANELIST_IDS[0], PANELIST_IDS[1]]

UNKNOWN_ITEM_ID = "00000000-0000-0000-0000-000000000000"


def _approve(api, item_id, headers):
    return api.review_item(item_id, f.review_item_payload("APPROVE"), headers)


def _two_approved_items(api):
    """An active programme with two independently approved items in domain D1."""
    program = fx.active_program(api)
    first = fx.approved_item(api, program["id"], stem="CPX approved item one")
    second = fx.approved_item(api, program["id"], stem="CPX approved item two")
    return program, first, second


def _an_approved_and_a_draft_item(api):
    """One item cleared for a form, and one that has never left DRAFT."""
    program = fx.active_program(api)
    approved = fx.approved_item(api, program["id"], stem="CPX approved item")
    draft = fx.draft_item(api, program["id"], stem="CPX draft item")
    assert draft["status"] == "DRAFT"
    return program, approved, draft


def _form_with_two_panellists(api):
    """An assembled form whose panel has two eligible members and no ratings yet."""
    program, approved, _draft = _an_approved_and_a_draft_item(api)
    form = validate_success(api.create_form(
        f.create_form_payload(program["id"], [approved["id"]],
                              panelist_user_ids=TWO_PANELLISTS), fx.PSYCHOMETRICIAN), 201)
    return program, form


class TestItemReviewPreconditions:
    """The chain is state, then authorship, then approver distinctness."""

    def test_reviewing_a_draft_item_is_refused_before_any_duties_question(self, api):
        """An untainted reviewer is turned away because the item has not been submitted,
        and the refusal leaves the item where it was.

        PRD §2.7: "12. **Transition legality.** The addressed record is in a state from
        which the requested transition is declared → otherwise `ERR_INVALID_STATE` (409).
        Applies to every action operation."

        PRD §3.2: "The new item's `status` is `DRAFT`, its `approver_user_ids` list is
        empty, its `review_round` starts at 1, all twelve of its response accumulators start
        at 0, and its `stat_basis_applied` starts at `INSUFFICIENT_DATA` with both `p_value`
        and `discrimination_index` null."

        Design: Corner/endpoints/item_review_requires_in_review_and_two_distinct_approvers_who_are_not_the_author
        """
        program = fx.active_program(api)
        item = fx.draft_item(api, program["id"])

        refused = _approve(api, item["id"], REVIEWER_1)

        validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)
        unchanged = fx.read_item(api, item["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["approver_user_ids"] == []
        assert unchanged["review_round"] == 1
        ax.assert_item(unchanged)

    def test_the_author_may_not_review_their_own_submission(self, api):
        """Submission moves the item into review with no approvals carried in, and the
        author's own APPROVE is refused on duties rather than on state.

        PRD §3.2: "Review is where the segregation-of-duties model earns its keep. A
        reviewing `ItemSpecialist` supplies a `decision` of `APPROVE`, `REVISE`, or
        `REJECT`, optionally with a `review_note`, and in every case the acting `X-User-ID`
        must differ from the item's `author_user_id` — otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.2: "First, `approver_user_ids` is reset to the empty list, unconditionally:
        approvals never carry across a round."

        Design: Corner/endpoints/item_review_requires_in_review_and_two_distinct_approvers_who_are_not_the_author
        """
        program = fx.active_program(api)
        item = fx.item_in_review(api, program["id"])
        assert item["status"] == "IN_REVIEW"
        assert item["approver_user_ids"] == []
        assert item["author_user_id"] == ITEM_AUTHOR_ID

        refused = _approve(api, item["id"], fx.ITEM_AUTHOR)

        error = validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value
        unchanged = fx.read_item(api, item["id"])
        assert unchanged["status"] == "IN_REVIEW"
        assert unchanged["approver_user_ids"] == []

    def test_two_distinct_non_author_approvals_are_needed_and_a_repeat_is_refused(self, api):
        """One approval leaves the item in review, the same reviewer approving twice is
        refused on duties, and only a second distinct reviewer clears it — with exactly two
        recorded approvers and no statistics.

        PRD §3.2: "An `APPROVE` decision additionally requires that the acting user does not
        already appear in `approver_user_ids`, and the same error is returned when they do."

        PRD §3.2: "The second `APPROVE`, which is by definition the one where
        `approver_user_ids` held exactly one entry before the call, appends the second user
        so the list length becomes 2 and moves the item `IN_REVIEW → APPROVED`."

        Design: Corner/endpoints/item_review_requires_in_review_and_two_distinct_approvers_who_are_not_the_author
        """
        program = fx.active_program(api)
        item = fx.item_in_review(api, program["id"])

        first = validate_success(_approve(api, item["id"], REVIEWER_1), 200)
        assert first["status"] == "IN_REVIEW"
        assert first["approver_user_ids"] == [ITEM_REVIEWER_1_ID]

        validate_error(_approve(api, item["id"], REVIEWER_1),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
        assert fx.read_item(api, item["id"])["approver_user_ids"] == [ITEM_REVIEWER_1_ID]

        cleared = validate_success(_approve(api, item["id"], REVIEWER_2), 200)
        assert cleared["status"] == "APPROVED"
        assert cleared["approver_user_ids"] == [ITEM_REVIEWER_1_ID, ITEM_REVIEWER_2_ID]
        assert cleared["p_value"] is None
        assert fx.read_program(api, program["id"])["operational_item_count"] == 0


class TestFormAssemblyReferences:
    """Assembly is the only link between a programme and its items, so both sides resolve."""

    def test_an_unknown_item_and_a_stray_pretest_identifier_are_each_refused(self, api):
        """A body-reference miss answers 404 on the item, and a pretest entry outside
        `item_ids` answers on the subset rule rather than on the length rule.

        PRD §3.5: "every entry of `pretest_item_ids` must also appear in `item_ids`, or
        `ERR_ITEM_NOT_IN_FORM`; and the number of entries in `item_ids` must equal the
        program's `form_length` exactly, or `ERR_FORM_LENGTH_MISMATCH`."

        PRD §2.7: "4. **Body-reference existence.** Every foreign identifier carried in a
        request body resolves to a stored record, with the 404 that matches the referenced
        collection. This layer guards item creation, form assembly, application submission,
        registration creation, and disciplinary case opening."

        Design: Corner/endpoints/form_assembly_links_program_and_items_and_rejects_an_unknown_item_or_a_stray_pretest_id
        """
        program, first, second = _two_approved_items(api)

        missing = api.create_form(
            f.create_form_payload(program["id"], [UNKNOWN_ITEM_ID], form_code="CPX-F0"),
            fx.PSYCHOMETRICIAN)
        validate_error(missing, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 404)

        stray = api.create_form(
            f.create_form_payload(program["id"], [first["id"]], form_code="CPX-F0",
                                  pretest_item_ids=[second["id"]]),
            fx.PSYCHOMETRICIAN)

        error = validate_error(stray, ApiErrorId.ERR_ITEM_NOT_IN_FORM.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_FORM_LENGTH_MISMATCH.value
        _rows, meta = validate_paginated(api.list_forms(fx.PSYCHOMETRICIAN,
                                                        {"program_id": program["id"]}))
        assert meta["total_count"] == 0

    def test_the_accepted_assembly_stores_the_association_and_derives_its_counts(self, api):
        """With no pretest positions the scored count is the whole form, the panel is open
        with no ratings, and no cut score exists yet.

        PRD §3.5: "A new form has `status` `ASSEMBLED`, `panel_status` `OPEN`, an empty
        `panel_ratings` list, a `scored_item_count` equal to the number of entries in
        `item_ids` less the number of entries in `pretest_item_ids`, and a
        `retired_item_count` computed from the current status of the cited items."

        PRD §3.5: "Its `mean_expected_pass_rate` and `raw_cut_score` are both null until a
        cut score is adopted."

        Design: Corner/endpoints/form_assembly_links_program_and_items_and_rejects_an_unknown_item_or_a_stray_pretest_id
        """
        program, first, _second = _two_approved_items(api)

        form = validate_success(api.create_form(
            f.create_form_payload(program["id"], [first["id"]]), fx.PSYCHOMETRICIAN), 201)

        assert form["status"] == "ASSEMBLED"
        assert form["panel_status"] == "OPEN"
        assert form["panel_ratings"] == []
        assert form["item_ids"] == [first["id"]]
        assert form["pretest_item_ids"] == []
        assert form["scored_item_count"] == 1
        assert form["retired_item_count"] == 0
        assert form["panelist_user_ids"] == [PANELIST_IDS[0]]
        assert form["raw_cut_score"] is None
        ax.assert_exam_form(form, expected_version=1)

        _rows, meta = validate_paginated(api.list_forms(fx.PSYCHOMETRICIAN,
                                                        {"program_id": program["id"]}))
        assert meta["total_count"] == 1


class TestPanelRatingMembershipAndMultiplicity:
    """A draft item never reaches a form, an outsider never rates, and nobody rates twice."""

    def test_a_draft_item_cited_as_a_scored_position_is_refused_on_maturity(self, api):
        """The form is the right length and the item belongs to the programme; the only
        objection is that the item has not been reviewed.

        PRD §3.5: "every scored item must be in `APPROVED`, `PRETEST`, or `OPERATIONAL`
        status, or `ERR_ITEM_NOT_ELIGIBLE_FOR_FORM`"

        Design: Corner/endpoints/panel_rating_rejects_an_outsider_and_a_repeat_while_assembly_rejects_a_draft_item
        """
        program, _approved, draft = _an_approved_and_a_draft_item(api)

        refused = api.create_form(
            f.create_form_payload(program["id"], [draft["id"]], form_code="CPX-F0",
                                  panelist_user_ids=TWO_PANELLISTS),
            fx.PSYCHOMETRICIAN)

        error = validate_error(refused, ApiErrorId.ERR_ITEM_NOT_ELIGIBLE_FOR_FORM.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_FORM_LENGTH_MISMATCH.value
        _rows, meta = validate_paginated(api.list_forms(fx.PSYCHOMETRICIAN,
                                                        {"program_id": program["id"]}))
        assert meta["total_count"] == 0

    def test_a_rating_for_someone_outside_the_panel_is_refused(self, api):
        """A psychometrician may submit on a panellist's behalf, but not on behalf of
        somebody the form never named, and the refusal leaves the panel empty.

        PRD §3.5: "The named `panelist_user_id` must appear in the form's
        `panelist_user_ids`, or the submission is refused with `ERR_PANELIST_NOT_ON_PANEL`,
        and a panellist who has already rated this form is refused with
        `ERR_DUPLICATE_PANELIST_RATING`."

        Design: Corner/endpoints/panel_rating_rejects_an_outsider_and_a_repeat_while_assembly_rejects_a_draft_item
        """
        _program, form = _form_with_two_panellists(api)
        assert form["panelist_user_ids"] == TWO_PANELLISTS

        refused = api.submit_panel_rating(
            form["id"], f.panel_rating_payload(OUTSIDE_PANELIST_ID, 0.55),
            fx.PSYCHOMETRICIAN)

        validate_error(refused, ApiErrorId.ERR_PANELIST_NOT_ON_PANEL.value, 422)
        unchanged = fx.read_form(api, form["id"])
        assert unchanged["panel_ratings"] == []
        assert unchanged["panel_status"] == "OPEN"

    def test_a_repeat_rating_is_refused_and_the_first_value_survives_to_completion(self, api):
        """One of two panellists leaves the panel open; the repeat is rejected without
        overwriting the stored 0.60; the second panellist completes the panel without
        adopting anything.

        PRD §3.5: "Each accepted rating is appended to `panel_ratings` as a record of the
        `panelist_user_id`, the `mean_expected_pass_rate`, and a `submitted_at` stamp from
        the logical clock."

        PRD §3.5: "Once the number of entries in `panel_ratings` equals the number of
        entries in `panelist_user_ids`, `panel_status` moves to `RATINGS_COMPLETE`."

        Design: Corner/endpoints/panel_rating_rejects_an_outsider_and_a_repeat_while_assembly_rejects_a_draft_item
        """
        _program, form = _form_with_two_panellists(api)

        rated_once = validate_success(api.submit_panel_rating(
            form["id"], f.panel_rating_payload(PANELIST_IDS[0], 0.60), PANELIST_1), 200)
        assert len(rated_once["panel_ratings"]) == 1
        assert rated_once["panel_status"] == "OPEN"

        refused = api.submit_panel_rating(
            form["id"], f.panel_rating_payload(PANELIST_IDS[0], 0.70), PANELIST_1)
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_PANELIST_RATING.value, 409)
        held = fx.read_form(api, form["id"])
        assert len(held["panel_ratings"]) == 1
        assert float(held["panel_ratings"][0]["mean_expected_pass_rate"]) == pytest.approx(
            0.60, abs=0.000001)

        completed = validate_success(api.submit_panel_rating(
            form["id"], f.panel_rating_payload(PANELIST_IDS[1], 0.80), PANELIST_2), 200)
        assert len(completed["panel_ratings"]) == 2
        assert completed["panel_status"] == "RATINGS_COMPLETE"
        assert completed["raw_cut_score"] is None
