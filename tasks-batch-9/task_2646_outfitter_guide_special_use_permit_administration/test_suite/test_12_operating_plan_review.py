"""The annual operating plan: completeness, the bounded revision loop, custody.

Covers the cyclic SUBMITTED -> UNDER_REVIEW -> REVISION_REQUESTED lap with its
accumulating revision_round, the two gates that look like one "bad plan" check,
and the two duty separations enforced on the acting X-User-ID.
"""
from test_helpers import (
    ApiErrorId,
    OFFICER_USER_ID,
    OFFICER_USER_ID_ALT,
    SPECIALIST_USER_ID,
    SPECIALIST_USER_ID_ALT,
    appeal_action,
    campsite_section,
    create_operating_plan,
    issue_noncompliance_action,
    list_noncompliance_actions,
    operating_plan_payload,
    plan_section_payload,
    read_permit,
    read_operating_plan,
    sanitation_section,
    set_clock,
    setup_issued_permit,
    start_plan_review,
    submit_operating_plan,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    make_authorized_officer_headers,
    make_permit_specialist_headers,
    make_program_administrator_headers,
)

SPECIALIST_ONE = make_permit_specialist_headers(SPECIALIST_USER_ID)
SPECIALIST_TWO = make_permit_specialist_headers(SPECIALIST_USER_ID_ALT)
SPECIALIST_THREE_ID = "spec-3"
SPECIALIST_THREE = make_permit_specialist_headers(SPECIALIST_THREE_ID)
OFFICER = make_authorized_officer_headers(OFFICER_USER_ID)
OFFICER_ALT = make_authorized_officer_headers(OFFICER_USER_ID_ALT)
ADMIN_WEARING_THE_OFFICERS_ID = make_program_administrator_headers(OFFICER_USER_ID)


def _issued_permit_with_a_complete_draft_plan():
    """An ISSUED Alpine permit on BRW-01 carrying a complete DRAFT 2027 plan."""
    context = setup_issued_permit()
    plan = create_operating_plan(context["permit"]["id"], context["outfitter"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan["revision_round"] == 0
    assert plan["deficiency_sections"] == []
    assert plan["completeness_score"] == 100.0
    return context, plan


def _request_revision(plan_id, sections, headers):
    return api_client.request_operating_plan_revision(
        plan_id, {"deficiency_sections": sections}, headers
    )


def test_the_revision_round_accumulates_across_laps_and_bounds_the_loop_at_two():
    """PRD §3.5: "That loop is bounded: a revision may be requested only while `revision_round`
    is still below 2, so the third deficiency finding must be a rejection instead, and
    attempting a third revision returns `ERR_REVISION_LIMIT_EXCEEDED` (HTTP 409)."
    PRD §3.5: "A resubmission out of `REVISION_REQUESTED` differs in two respects:
    `revision_round` keeps its accumulated value rather than resetting, and
    `reviewed_by_user_id` is cleared to null so that a fresh reviewer must take custody of the
    revised plan."
    PRD §3.5: "A reviewer may return the plan to the holder, moving it
    `UNDER_REVIEW → REVISION_REQUESTED` with the `deficiency_sections` array naming the
    sections at fault"
    PRD §3.5: "The return increments `revision_round` by 1 and stores the array."
    PRD §3.5: "Either way the plan moves to `SUBMITTED` and `deficiency_sections` is cleared
    back to an empty array."
    PRD §3.5: "An `AuthorizedOfficer` or `ProgramAdministrator` may approve the plan, moving it
    `UNDER_REVIEW → APPROVED` and stamping `approved_by_user_id` from the acting `X-User-ID`"

    Design: Difficulty/non_linear_state_machine/operating_plan_revision_loop_bounded_at_two
    """
    context, plan = _issued_permit_with_a_complete_draft_plan()
    plan_id = plan["id"]
    outfitter_id = context["outfitter"]["id"]

    first_submission = submit_operating_plan(plan_id, outfitter_id)
    assert first_submission["status"] == "SUBMITTED"
    assert first_submission["revision_round"] == 0
    assert first_submission["reviewed_by_user_id"] is None

    lap_one = start_plan_review(plan_id, SPECIALIST_USER_ID)
    assert lap_one["status"] == "UNDER_REVIEW"
    assert lap_one["reviewed_by_user_id"] == SPECIALIST_USER_ID

    returned_once = validate_success(
        _request_revision(plan_id, ["stock_section"], SPECIALIST_ONE)
    )
    assert returned_once["status"] == "REVISION_REQUESTED"
    assert returned_once["revision_round"] == 1
    assert returned_once["deficiency_sections"] == ["stock_section"]
    assert returned_once["completeness_score"] == 100.0, (
        "a deficiency finding is a judgement about the content, not about the four keys"
    )

    second_submission = submit_operating_plan(plan_id, outfitter_id)
    assert second_submission["status"] == "SUBMITTED"
    assert second_submission["revision_round"] == 1, (
        "the return hop never resets the accumulated round count"
    )
    assert second_submission["deficiency_sections"] == []
    assert second_submission["reviewed_by_user_id"] is None, (
        "custody is surrendered on the way round, so a fresh reviewer must take the lap"
    )

    lap_two = start_plan_review(plan_id, SPECIALIST_USER_ID_ALT)
    assert lap_two["reviewed_by_user_id"] == SPECIALIST_USER_ID_ALT
    assert lap_two["revision_round"] == 1

    returned_twice = validate_success(
        _request_revision(
            plan_id, ["sanitation_section", "campsite_section"], SPECIALIST_TWO
        )
    )
    assert returned_twice["status"] == "REVISION_REQUESTED"
    assert returned_twice["revision_round"] == 2
    assert returned_twice["deficiency_sections"] == [
        "sanitation_section",
        "campsite_section",
    ]

    third_submission = submit_operating_plan(plan_id, outfitter_id)
    assert third_submission["status"] == "SUBMITTED"
    assert third_submission["revision_round"] == 2
    assert third_submission["deficiency_sections"] == []
    assert third_submission["reviewed_by_user_id"] is None

    lap_three = start_plan_review(plan_id, SPECIALIST_THREE_ID)
    assert lap_three["status"] == "UNDER_REVIEW"
    assert lap_three["reviewed_by_user_id"] == SPECIALIST_THREE_ID
    assert lap_three["revision_round"] == 2

    validate_error(
        _request_revision(plan_id, ["stock_section"], SPECIALIST_THREE),
        ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED,
    )

    unmoved = read_operating_plan(plan_id)
    assert unmoved["status"] == "UNDER_REVIEW", (
        "the refused third lap leaves the plan where the reviewer found it"
    )
    assert unmoved["revision_round"] == 2
    assert unmoved["deficiency_sections"] == []
    assert unmoved["reviewed_by_user_id"] == SPECIALIST_THREE_ID

    approved = validate_success(api_client.approve_operating_plan(plan_id, OFFICER))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == OFFICER_USER_ID
    assert approved["reviewed_by_user_id"] == SPECIALIST_THREE_ID
    assert approved["revision_round"] == 2, (
        "the accumulated laps survive onto the terminal row"
    )


def test_the_third_finding_must_be_a_rejection_and_rejection_frees_the_year():
    """PRD §3.5: "A `PermitSpecialist` or an `AuthorizedOfficer` takes a `SUBMITTED` plan under
    review, moving it `SUBMITTED → UNDER_REVIEW` and stamping `reviewed_by_user_id` with the
    acting `X-User-ID`."
    PRD §3.5: "every entry in that array must be one of the four section names, and anything
    else is `ERR_INVALID_REQUEST`"
    PRD §3.5: "Or they may reject it with a `rejection_reason_code`, moving it
    `UNDER_REVIEW → REJECTED`, which frees the permit-and-`plan_year` slot for a fresh filing."
    PRD §3.5: "Submission is available from `DRAFT` and from `REVISION_REQUESTED`, and any other
    status yields `ERR_INVALID_PLAN_STATE` (HTTP 409)."
    PRD §3.5: "listable per permit, oldest first, with optional `plan_year` and `status`
    filters."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Difficulty/non_linear_state_machine/operating_plan_revision_loop_bounded_at_two
    """
    context, plan = _issued_permit_with_a_complete_draft_plan()
    plan_id = plan["id"]
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]

    submit_operating_plan(plan_id, outfitter_id)
    start_plan_review(plan_id, SPECIALIST_USER_ID)
    version_before = read_operating_plan(plan_id)["version"]

    validate_error(
        _request_revision(plan_id, ["fire_section"], SPECIALIST_ONE),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        _request_revision(plan_id, ["stock_section", "gear_section"], SPECIALIST_ONE),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    intact = read_operating_plan(plan_id)
    assert intact["status"] == "UNDER_REVIEW"
    assert intact["revision_round"] == 0
    assert intact["deficiency_sections"] == []
    assert intact["version"] == version_before

    validate_success(_request_revision(plan_id, ["stock_section"], SPECIALIST_ONE))
    submit_operating_plan(plan_id, outfitter_id)
    start_plan_review(plan_id, SPECIALIST_USER_ID_ALT)
    validate_success(_request_revision(plan_id, ["campsite_section"], SPECIALIST_TWO))
    submit_operating_plan(plan_id, outfitter_id)

    officer_custody = validate_success(
        api_client.start_operating_plan_review(plan_id, OFFICER)
    )
    assert officer_custody["status"] == "UNDER_REVIEW"
    assert officer_custody["reviewed_by_user_id"] == OFFICER_USER_ID, (
        "an AuthorizedOfficer may take custody just as a specialist may"
    )
    assert officer_custody["revision_round"] == 2

    validate_error(
        _request_revision(plan_id, ["stock_section"], OFFICER),
        ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED,
    )

    rejected = validate_success(
        api_client.reject_operating_plan(
            plan_id, {"rejection_reason_code": "INADEQUATE_STOCK_CONTAINMENT"}, OFFICER_ALT
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason_code"] == "INADEQUATE_STOCK_CONTAINMENT"
    assert rejected["revision_round"] == 2
    assert rejected["reviewed_by_user_id"] == OFFICER_USER_ID
    assert rejected["approved_by_user_id"] is None

    validate_error(
        api_client.submit_operating_plan(plan_id, context["holder_headers"]),
        ApiErrorId.ERR_INVALID_PLAN_STATE,
    )

    refiled = validate_success(
        api_client.create_operating_plan(
            permit_id, operating_plan_payload(2027), context["holder_headers"]
        ),
        201,
    )
    assert refiled["status"] == "DRAFT"
    assert refiled["revision_round"] == 0
    assert refiled["completeness_score"] == 100.0

    rows, meta = validate_paginated(
        api_client.list_operating_plans(permit_id, SPECIALIST_ONE)
    )
    assert meta["total_count"] == 2
    assert [(row["id"], row["status"]) for row in rows] == [
        (plan_id, "REJECTED"),
        (refiled["id"], "DRAFT"),
    ]


def test_incompleteness_and_the_duplicate_year_fire_at_their_own_gates():
    """PRD §3.5: "Only one plan may occupy a given permit-and-`plan_year` pair in any status
    other than `REJECTED`; a second filing is `ERR_DUPLICATE_PLAN_YEAR` (HTTP 409)."
    PRD §3.5: "Each of the four sections is worth 25.0 points, awarded only when *every* one of
    that section's required keys is present and non-null."
    PRD §3.5: "`campsite_section` requires `designated_sites_only`, `max_nights_per_site` and
    `fire_policy`."
    PRD §3.5: "`sanitation_section` requires `human_waste_method`, `greywater_method` and
    `packout_commitment`."
    PRD §3.5: "The holder revises one section at a time by naming a `section_name` — one of the
    four section field names — and supplying the replacement `section_body`; a section may be
    replaced only while the plan is `DRAFT` or `REVISION_REQUESTED`, and each replacement
    recomputes `completeness_score`."
    PRD §3.5: "Submission requires `completeness_score` to equal exactly 100.0; anything less is
    `ERR_OPERATING_PLAN_INCOMPLETE` (HTTP 422)."
    PRD §3.5: "Or they may reject it with a `rejection_reason_code`, moving it
    `UNDER_REVIEW → REJECTED`, which frees the permit-and-`plan_year` slot for a fresh filing."

    Design: Corner/errors/plan_completeness_and_duplicate_year_are_enforced_at_their_own_gates
    """
    context = setup_issued_permit()
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    holder = context["holder_headers"]

    plan_a = create_operating_plan(
        permit_id,
        outfitter_id,
        2027,
        campsite_section={"designated_sites_only": True, "max_nights_per_site": 3},
    )
    assert plan_a["status"] == "DRAFT"
    assert plan_a["completeness_score"] == 75.0, (
        "one missing key costs the whole 25.0-point section, not a fraction of it"
    )

    validate_error(
        api_client.submit_operating_plan(plan_a["id"], holder),
        ApiErrorId.ERR_OPERATING_PLAN_INCOMPLETE,
    )
    assert read_operating_plan(plan_a["id"])["status"] == "DRAFT"

    repaired = validate_success(
        api_client.replace_operating_plan_section(
            plan_a["id"],
            plan_section_payload("campsite_section", campsite_section()),
            holder,
        )
    )
    assert repaired["completeness_score"] == 100.0
    assert repaired["sanitation_section"] == sanitation_section(), (
        "a replacement touches exactly the section it names"
    )

    submitted = validate_success(api_client.submit_operating_plan(plan_a["id"], holder))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["deficiency_sections"] == []

    validate_error(
        api_client.create_operating_plan(permit_id, operating_plan_payload(2027), holder),
        ApiErrorId.ERR_DUPLICATE_PLAN_YEAR,
    )

    start_plan_review(plan_a["id"], SPECIALIST_USER_ID)
    rejected = validate_success(
        api_client.reject_operating_plan(
            plan_a["id"], {"rejection_reason_code": "INSUFFICIENT_DETAIL"}, OFFICER_ALT
        )
    )
    assert rejected["status"] == "REJECTED"

    set_clock("2027-01-06T00:00:00Z")
    plan_b = validate_success(
        api_client.create_operating_plan(permit_id, operating_plan_payload(2027), holder),
        201,
    )
    assert plan_b["status"] == "DRAFT"
    assert plan_b["completeness_score"] == 100.0

    validate_error(
        api_client.create_operating_plan(permit_id, operating_plan_payload(2027), holder),
        ApiErrorId.ERR_DUPLICATE_PLAN_YEAR,
    )

    set_clock("2027-01-07T00:00:00Z")
    plan_c = validate_success(
        api_client.create_operating_plan(
            permit_id,
            operating_plan_payload(
                2028,
                sanitation_section={
                    "human_waste_method": "PORTABLE_TOILET",
                    "packout_commitment": "ALL_SOLID_WASTE",
                },
            ),
            holder,
        ),
        201,
    )
    assert plan_c["completeness_score"] == 75.0, (
        "the same 25.0-point rule bites in a different section"
    )
    validate_error(
        api_client.submit_operating_plan(plan_c["id"], holder),
        ApiErrorId.ERR_OPERATING_PLAN_INCOMPLETE,
    )

    rows, meta = validate_paginated(
        api_client.list_operating_plans(permit_id, SPECIALIST_ONE)
    )
    assert meta["total_count"] == 3
    assert [(row["id"], row["plan_year"], row["status"]) for row in rows] == [
        (plan_a["id"], 2027, "REJECTED"),
        (plan_b["id"], 2027, "DRAFT"),
        (plan_c["id"], 2028, "DRAFT"),
    ]


def test_one_user_id_may_neither_review_and_dispose_nor_issue_and_decide():
    """PRD §2.1: "Those recorded identifiers are what the two duty separations are enforced
    against: the `X-User-ID` that took an operating plan under review may not approve or reject
    it, and the officer whose `X-User-ID` issued a noncompliance action may not decide its
    appeal. Both violations return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.5: "An `AuthorizedOfficer` or `ProgramAdministrator` may approve the plan, moving it
    `UNDER_REVIEW → APPROVED` and stamping `approved_by_user_id` from the acting `X-User-ID`"
    PRD §3.5: "For both approval and rejection the acting `X-User-ID` must differ from the plan's
    `reviewed_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "A pending appeal is then decided by an `AuthorizedOfficer` or
    `ProgramAdministrator` supplying a `decision` of `UPHELD` or `RESCINDED`; the action must be
    `APPEALED`, else `ERR_ACTION_NOT_APPEALABLE`, and the deciding `X-User-ID` must differ from
    `issued_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "`UPHELD` keeps the points exactly where they were"
    PRD §3.8: "It sums the `points` of that permit's actions whose `status` is `ISSUED`,
    `APPEALED` or `UPHELD`"
    PRD §3.8: "Otherwise, if `open_noncompliance_points` is at or above **5**, or
    `insurance_current` is false, or `fee_delinquent` is true, the permit is on `PROBATION`."

    Design: Corner/rbac/the_same_user_id_cannot_review_and_approve_or_issue_and_decide_its_own_action
    """
    context, plan = _issued_permit_with_a_complete_draft_plan()
    plan_id = plan["id"]
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]

    submit_operating_plan(plan_id, outfitter_id)
    custody = validate_success(api_client.start_operating_plan_review(plan_id, OFFICER))
    assert custody["status"] == "UNDER_REVIEW"
    assert custody["reviewed_by_user_id"] == OFFICER_USER_ID

    validate_error(
        api_client.approve_operating_plan(plan_id, OFFICER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api_client.reject_operating_plan(
            plan_id, {"rejection_reason_code": "INSUFFICIENT_DETAIL"}, OFFICER
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api_client.approve_operating_plan(plan_id, ADMIN_WEARING_THE_OFFICERS_ID),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    barred = read_operating_plan(plan_id)
    assert barred["status"] == "UNDER_REVIEW", (
        "the reviewer is barred from both dispositions, favourable or not"
    )
    assert barred["approved_by_user_id"] is None
    assert barred["rejection_reason_code"] is None

    approved = validate_success(api_client.approve_operating_plan(plan_id, OFFICER_ALT))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == OFFICER_USER_ID_ALT
    assert approved["reviewed_by_user_id"] == OFFICER_USER_ID

    action = issue_noncompliance_action(permit_id, officer_user_id=OFFICER_USER_ID)
    assert action["status"] == "ISSUED"
    assert action["points"] == 2
    assert action["issued_by_user_id"] == OFFICER_USER_ID

    appealed = appeal_action(action["id"], outfitter_id)
    assert appealed["status"] == "APPEALED"
    assert read_permit(permit_id)["open_noncompliance_points"] == 2, (
        "appealing is not a stay, so the points keep counting while it is pending"
    )

    validate_error(
        api_client.decide_noncompliance_appeal(
            action["id"], {"decision": "RESCINDED"}, OFFICER
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api_client.decide_noncompliance_appeal(
            action["id"], {"decision": "UPHELD"}, ADMIN_WEARING_THE_OFFICERS_ID
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    open_rows, open_meta = list_noncompliance_actions(permit_id)
    assert open_meta["total_count"] == 1
    assert open_rows[0]["status"] == "APPEALED", (
        "a refused decision leaves the appeal pending"
    )
    assert open_rows[0]["appeal_decided_by_user_id"] is None

    decided = validate_success(
        api_client.decide_noncompliance_appeal(
            action["id"], {"decision": "UPHELD"}, OFFICER_ALT
        )
    )
    assert decided["status"] == "UPHELD"
    assert decided["appeal_decided_by_user_id"] == OFFICER_USER_ID_ALT

    permit = read_permit(permit_id)
    assert permit["open_noncompliance_points"] == 2
    assert permit["insurance_current"] is False
    assert permit["compliance_status"] == "PROBATION", (
        "two points are below the five-point bar; the missing certificate is what bites"
    )
