"""Writes refused because of a state living on some entirely different row."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_money,
    assert_project_estimate,
    assert_scenario_funding,
)
from test_helpers.constants import (
    CLOCK_2026_10_01,
    FUNDING_STANDARD,
    MAPLE_BUNDLE_BASE,
    MAPLE_CONTINGENCY,
    MAPLE_TOTAL,
    OAK_TOTAL,
    UNCOMMITTED_AFTER_MAPLE_AWARD,
)
from test_helpers.factories import award_payload, cut_decide_payload
from test_helpers.test_users import COORDINATOR, ENGINEER, OFFICER_AWARDER

WAIVER_REASON = "emergency valve replacement authorised by the city engineer"
OAK_WINDOW_START = "2026-10-01T00:00:00Z"
OAK_WINDOW_END = "2026-10-31T00:00:00Z"


def _three_of_four_utilities_cleared(api):
    """A COORDINATING project whose only outstanding row belongs to the telecom."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx)
    for utility in ("WATER", "SEWER", "FRANCHISE_GAS"):
        fixtures.respond_coordination(
            api,
            fixtures.coordination_for(ctx, utility)["id"],
            "CLEAR",
            response_note="no facilities in conflict",
        )
    return ctx


def test_bid_ready_is_refused_while_one_sibling_clearance_row_is_open(api):
    """The project's own fields are all in order; a related row holds the gate shut.

    PRD: "Advancing with an `action` of `BID_READY` moves the project from
    `COORDINATING` to `BID_READY` and prices the bundle, recomputing
    `bundle_base_cents`, `contingency_cents`, `utility_share_cents` and
    `project_total_estimate_cents`. It requires the project to be in
    `COORDINATING`, else `ERR_PROJECT_NOT_COORDINATING`; it requires at least one
    non-removed line, else `ERR_PROJECT_HAS_NO_SEGMENTS`; and it requires
    `clearance_outstanding_count` to have reached zero, meaning every utility row on
    the project is either `CLEARED` or `CLEARED_AFTER_WORK`, else
    `ERR_UTILITY_CLEARANCE_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/bid_ready_blocked_until_every_utility_coordination_cleared
    """
    ctx = _three_of_four_utilities_cleared(api)
    project = fixtures.read_project(api, ctx["project"]["id"])
    telecom = validate_success(
        api.get_coordination(fixtures.coordination_for(ctx, "FRANCHISE_TELECOM")["id"], COORDINATOR)
    )
    assert project["clearance_outstanding_count"] == 1
    assert project["segment_count"] == 1
    assert telecom["coordination_status"] == "CLEARANCE_REQUESTED"

    validate_error(
        api.advance_project(ctx["project"]["id"], {"action": "BID_READY"}, ENGINEER),
        ApiErrorId.UTILITY_CLEARANCE_PENDING,
        409,
    )

    refused = fixtures.read_project(api, ctx["project"]["id"])
    assert refused["delivery_status"] == "COORDINATING"
    assert refused["clearance_outstanding_count"] == 1
    assert refused["project_total_estimate_cents"] == project["project_total_estimate_cents"]


def test_clearing_the_last_row_lets_the_identical_advance_through(api):
    """Nothing about the project changed, yet the same request now prices the bundle.

    PRD: "A `response` of `CLEAR` from a first-round row moves it to `CLEARED`; a
    `CLEAR` from a row whose `round_count` is 2 or more — meaning the utility
    already performed work in an earlier round — moves it to
    `CLEARED_AFTER_WORK` instead, which is what switches on the project's utility
    restoration share at the next estimate recompute."

    No row ever performed work, so the restoration share stays zero and the priced
    total is 11817655.

    Design: Difficulty/cross_entity_state_dependency/bid_ready_blocked_until_every_utility_coordination_cleared
    """
    ctx = _three_of_four_utilities_cleared(api)
    validate_error(
        api.advance_project(ctx["project"]["id"], {"action": "BID_READY"}, ENGINEER),
        ApiErrorId.UTILITY_CLEARANCE_PENDING,
        409,
    )

    cleared = fixtures.respond_coordination(
        api,
        fixtures.coordination_for(ctx, "FRANCHISE_TELECOM")["id"],
        "CLEAR",
        response_note="telecom has no work here",
    )
    project = fixtures.advance(api, ctx["project"]["id"], "BID_READY")

    assert cleared["coordination_status"] == "CLEARED"
    assert project["delivery_status"] == "BID_READY"
    assert project["clearance_outstanding_count"] == 0
    assert_project_estimate(project, MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL)


def _suspended_firm_with_a_second_bid_ready_project(api):
    """One firm: a failed test on project A, and project B waiting for its award."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.in_construction_project(api, ctx, fixtures.MAPLE_LINE)
    assert_money(ctx["award_amount_cents"], MAPLE_TOTAL)
    ctx = fixtures.failing_test_on(api, ctx, "Maple St")
    assert ctx["contractor"]["standing"] == "SUSPENDED"
    assert ctx["contractor"]["interim_performance_score"] == 53.0

    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])
    assert_scenario_funding(
        scenario, FUNDING_STANDARD, MAPLE_TOTAL, UNCOMMITTED_AFTER_MAPLE_AWARD
    )

    project_b = fixtures.create_project(
        api,
        ctx["scenario"]["id"],
        "Z1",
        project_name="Oak St crack seal",
        planned_start_date=OAK_WINDOW_START,
        planned_end_date=OAK_WINDOW_END,
    )
    fixtures.add_line(
        api,
        project_b["id"],
        fixtures.segment_for(ctx, "Oak St")["id"],
        fixtures.candidate_for(ctx, "Oak St")["id"],
        OAK_WINDOW_START,
        OAK_WINDOW_END,
    )
    fixtures.advance(api, project_b["id"], "START_COORDINATION")
    for row in fixtures.list_coordinations(api, project_b["id"]):
        fixtures.respond_coordination(
            api, row["id"], "CLEAR", response_note="no facilities in conflict"
        )
    project_b = fixtures.advance(api, project_b["id"], "BID_READY")
    assert project_b["delivery_status"] == "BID_READY"
    assert_money(project_b["project_total_estimate_cents"], OAK_TOTAL)
    return ctx, project_b


def test_award_is_refused_for_a_firm_suspended_by_work_on_another_project(api):
    """The blocking state sits on neither the project nor its funding scenario.

    PRD: "The chosen contractor's `standing` must be `GOOD_STANDING`; a firm on
    `WATCH` or `SUSPENDED` cannot take new work and the award reports
    `ERR_CONTRACTOR_NOT_IN_GOOD_STANDING`."

    PRD: "Only `GOOD_STANDING` permits new awards; `WATCH` and `SUSPENDED` both
    refuse them with `ERR_CONTRACTOR_NOT_IN_GOOD_STANDING`, while awards already in
    hand continue undisturbed."

    The 5289971-cent award sits comfortably inside the 8182345 cents the scenario
    still has uncommitted and exactly on the project's own estimate, so no fiscal
    rule is in play.

    Design: Difficulty/cross_entity_state_dependency/award_blocked_when_contractor_standing_not_good
    """
    ctx, project_b = _suspended_firm_with_a_second_bid_ready_project(api)

    error = validate_error(
        api.award_project(
            project_b["id"],
            award_payload(ctx["contractor"]["id"], OAK_TOTAL),
            OFFICER_AWARDER,
        ),
        ApiErrorId.CONTRACTOR_NOT_IN_GOOD_STANDING,
        409,
    )

    assert error["error_id"] != ApiErrorId.SCENARIO_FUNDS_EXCEEDED
    assert OAK_TOTAL < UNCOMMITTED_AFTER_MAPLE_AWARD


def test_the_refused_award_leaves_the_scenario_ledger_untouched(api):
    """The first award stands undisturbed and the second moves not one cent.

    PRD: "The funding total always equals committed plus uncommitted, exactly."

    Design: Difficulty/cross_entity_state_dependency/award_blocked_when_contractor_standing_not_good
    """
    ctx, project_b = _suspended_firm_with_a_second_bid_ready_project(api)

    validate_error(
        api.award_project(
            project_b["id"],
            award_payload(ctx["contractor"]["id"], OAK_TOTAL),
            OFFICER_AWARDER,
        ),
        ApiErrorId.CONTRACTOR_NOT_IN_GOOD_STANDING,
        409,
    )

    after = fixtures.read_project(api, project_b["id"])
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])
    project_a = fixtures.read_project(api, ctx["project"]["id"])

    assert after["delivery_status"] == "BID_READY"
    assert after["award_amount_cents"] is None
    assert after["contractor_id"] is None
    assert_scenario_funding(
        scenario, FUNDING_STANDARD, MAPLE_TOTAL, UNCOMMITTED_AFTER_MAPLE_AWARD
    )
    assert project_a["delivery_status"] == "IN_CONSTRUCTION"
    assert_money(project_a["award_amount_cents"], MAPLE_TOTAL)


def _two_permits_on_fresh_pavement(api):
    """One non-emergency and one emergency cut filed in the same instant."""
    ctx = fixtures.maple_accepted(api)
    segment = fixtures.segment_for(ctx, "Maple St")
    assert segment["moratorium_until"].startswith("2029-10-01T00:00:00")
    assert segment["condition_index"] == 100.0

    ordinary = fixtures.apply_cut_permit(
        api,
        segment["id"],
        requested_start="2026-11-01T00:00:00Z",
        requested_end="2026-11-03T00:00:00Z",
        cut_area_sqft=200.0,
        emergency=False,
    )
    urgent = fixtures.apply_cut_permit(
        api,
        segment["id"],
        requested_start="2026-11-01T00:00:00Z",
        requested_end="2026-11-03T00:00:00Z",
        cut_area_sqft=200.0,
        emergency=True,
    )
    return ordinary, urgent


def test_the_permit_birth_state_branches_on_a_field_of_another_entity(api):
    """The same instant, the same trench: two different initial states and fees.

    PRD: "When the segment's `moratorium_until` is null, or has already passed the
    logical clock, or when the application is flagged as an emergency, the permit
    opens at `permit_status` `PENDING`. When the segment's `moratorium_until` is
    still in the future and the application is not an emergency, the permit opens at
    `MORATORIUM_REVIEW` instead, requiring a written waiver before it can be
    approved."

    PRD: "Third, an emergency application gets relief of half a point off the tier
    multiplier, floored at 1.0, and the result is stored as `fee_multiplier`; a
    non-emergency application stores the tier multiplier unchanged."

    Both permits see 1096 remaining days and a 170000-cent base fee, so the whole
    510000-versus-425000 gap is the half point of emergency relief.

    Design: Difficulty/cross_entity_state_dependency/cut_permit_initial_state_branches_on_segment_moratorium
    """
    ordinary, urgent = _two_permits_on_fresh_pavement(api)

    assert ordinary["permit_status"] == "MORATORIUM_REVIEW"
    assert ordinary["moratorium_remaining_days"] == 1096
    assert ordinary["fee_multiplier"] == 3.0
    assert_money(ordinary["degradation_fee_cents"], 510000)

    assert urgent["permit_status"] == "PENDING"
    assert urgent["moratorium_remaining_days"] == 1096
    assert urgent["fee_multiplier"] == 2.5
    assert_money(urgent["degradation_fee_cents"], 425000)


def test_only_the_moratorium_review_permit_demands_a_written_waiver(api):
    """Identical approvals: one is refused, the other lands with no waiver at all.

    PRD: "Approving a `MORATORIUM_REVIEW` permit requires a non-empty
    `waiver_reason`, which is recorded on the permit; without it the approval
    reports `ERR_MORATORIUM_WAIVER_REQUIRED`. A `PENDING` permit needs no waiver,
    and its `waiver_reason` stays null."

    Design: Difficulty/cross_entity_state_dependency/cut_permit_initial_state_branches_on_segment_moratorium
    """
    ordinary, urgent = _two_permits_on_fresh_pavement(api)

    validate_error(
        api.decide_cut_permit(ordinary["id"], cut_decide_payload("APPROVE"), ENGINEER),
        ApiErrorId.MORATORIUM_WAIVER_REQUIRED,
        422,
    )
    approved_urgent = validate_success(
        api.decide_cut_permit(urgent["id"], cut_decide_payload("APPROVE"), ENGINEER)
    )
    approved_ordinary = validate_success(
        api.decide_cut_permit(
            ordinary["id"],
            cut_decide_payload("APPROVE", waiver_reason=WAIVER_REASON),
            ENGINEER,
        )
    )

    assert approved_urgent["permit_status"] == "APPROVED"
    assert approved_urgent["waiver_reason"] is None
    assert approved_urgent["decided_at"].startswith(CLOCK_2026_10_01[:19])
    assert approved_ordinary["permit_status"] == "APPROVED"
    assert approved_ordinary["waiver_reason"] == WAIVER_REASON
    assert_money(approved_ordinary["degradation_fee_cents"], 510000)


def test_both_undecided_permits_read_back_with_their_branched_fees(api):
    """A read-only cross-check that the two birth states persist on the records.

    PRD: "Permits may be listed and filtered by `segment_id`, `permit_status` and
    `applicant_utility`."

    Design: Difficulty/cross_entity_state_dependency/cut_permit_initial_state_branches_on_segment_moratorium
    """
    ordinary, urgent = _two_permits_on_fresh_pavement(api)

    review = validate_success(api.get_cut_permit(ordinary["id"], COORDINATOR))
    pending = validate_success(api.get_cut_permit(urgent["id"], COORDINATOR))

    assert review["applicant_utility"] == "WATER"
    assert review["permit_status"] == "MORATORIUM_REVIEW"
    assert review["decided_at"] is None
    assert pending["permit_status"] == "PENDING"
    assert pending["decided_at"] is None
    assert review["degradation_fee_cents"] > pending["degradation_fee_cents"]
