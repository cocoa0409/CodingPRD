"""Loops, backward edges and orthogonal axes inside the delivery lifecycle."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_four_decimals,
    assert_money,
    assert_project_estimate,
    assert_project_states,
)
from test_helpers.constants import (
    CLOCK_2026_09_15,
    MAPLE_BUNDLE_BASE,
    MAPLE_CONTINGENCY,
    MAPLE_TOTAL,
    MAPLE_TOTAL_WITH_UTILITY,
    MAPLE_UTILITY_SHARE,
)
from test_helpers.factories import notice_payload, schedule_notice_payload
from test_helpers.test_users import COORDINATOR, ENGINEER


def _maple_under_test(api):
    """An in-construction Maple St bundle with no acceptance test on it yet."""
    ctx = fixtures.maple_in_construction(api)
    assert_project_states(ctx["project"], "IN_CONSTRUCTION", "NOT_STARTED")
    assert ctx["lines"]["Maple St"]["work_state"] == "IN_PROGRESS"
    return ctx


def test_submitting_a_test_moves_only_the_quality_axis(api):
    """The first test opens the quality track and leaves delivery where it stood.

    PRD: "The first test submitted anywhere on a project moves the project's
    `quality_status` from `NOT_STARTED` to `TESTING`, leaving `delivery_status`
    untouched — the two dimensions advance independently — and if the project's
    quality had bounced to `REMEDIATION_REQUIRED`, it returns to `TESTING` once
    `open_remediation_count` reaches zero again."

    Design: Difficulty/non_linear_state_machine/project_delivery_and_quality_dimensions_advance_independently
    """
    ctx = _maple_under_test(api)

    fixtures.submit_test(
        api, ctx["lines"]["Maple St"]["id"], core_density_pct=96.0, iri_in_per_mi=60.0,
        thickness_in=2.0,
    )
    project = fixtures.read_project(api, ctx["project"]["id"])

    assert_project_states(project, "IN_CONSTRUCTION", "TESTING")


def test_pass_decision_accepts_quality_while_delivery_stands_still(api):
    """Quality reaches its own terminal state with delivery still in construction.

    PRD: "A `ResurfacingProject` carries `delivery_status` (the contracting and
    construction track) alongside `quality_status` (the pavement-acceptance
    track); a test submitted on the first line moves `quality_status` without
    touching `delivery_status`."

    PRD: "The project's quality dimension may then bubble from `TESTING` to
    `QUALITY_ACCEPTED`, which happens exactly when `open_remediation_count` is
    zero and every non-removed line on the project has reached `WORK_COMPLETE`;
    reaching `QUALITY_ACCEPTED` is what unlocks final acceptance."

    Design: Difficulty/non_linear_state_machine/project_delivery_and_quality_dimensions_advance_independently
    """
    ctx = _maple_under_test(api)
    line_id = ctx["lines"]["Maple St"]["id"]
    submitted = fixtures.submit_test(
        api, line_id, core_density_pct=96.0, iri_in_per_mi=60.0, thickness_in=2.0
    )

    fixtures.decide_test(api, submitted["id"], "PASS", "test decision recorded")
    project = fixtures.read_project(api, ctx["project"]["id"])
    line = fixtures.read_line(api, line_id)

    assert_project_states(project, "IN_CONSTRUCTION", "QUALITY_ACCEPTED")
    assert project["open_remediation_count"] == 0
    assert line["work_state"] == "WORK_COMPLETE"
    assert_four_decimals(line["pay_factor"], 1.0200, "pay_factor")


def test_substantial_completion_moves_only_the_delivery_axis(api):
    """The delivery track advances alone, leaving the quality track already settled.

    PRD: "Substantial completion is declared by the awarded `Contractor` itself
    and moves `delivery_status` from `IN_CONSTRUCTION` to
    `SUBSTANTIALLY_COMPLETE`."

    The declaration is made on 2026-09-15, inside the planned window that opens
    2026-09-01 and closes 2026-09-30, so no late days are recorded.

    Design: Difficulty/non_linear_state_machine/project_delivery_and_quality_dimensions_advance_independently
    """
    ctx = _maple_under_test(api)
    line_id = ctx["lines"]["Maple St"]["id"]
    submitted = fixtures.submit_test(
        api, line_id, core_density_pct=96.0, iri_in_per_mi=60.0, thickness_in=2.0
    )
    fixtures.decide_test(api, submitted["id"], "PASS", "test decision recorded")
    fixtures.set_clock(api, CLOCK_2026_09_15)

    declared = fixtures.declare_substantial_completion(
        api, ctx["project"]["id"], ctx["contractor"]["id"]
    )

    assert_project_states(declared, "SUBSTANTIALLY_COMPLETE", "QUALITY_ACCEPTED")
    assert declared["days_late"] == 0


def _water_looped_roster(api):
    """Three utilities clear at once; WATER runs a full dig-and-re-request loop."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx)
    for utility in ("SEWER", "FRANCHISE_GAS", "FRANCHISE_TELECOM"):
        fixtures.respond_coordination(
            api,
            fixtures.coordination_for(ctx, utility)["id"],
            "CLEAR",
            response_note=f"{utility.lower()} has no work in this block",
        )
    water = fixtures.coordination_for(ctx, "WATER")
    fixtures.respond_coordination(
        api, water["id"], "CONFLICT", response_note="6-inch main replacement required first"
    )
    fixtures.respond_coordination(
        api,
        water["id"],
        "SCHEDULE_WORK",
        response_note="main replacement scheduled",
        planned_work_start="2026-08-10T00:00:00Z",
        planned_work_end="2026-08-20T00:00:00Z",
    )
    completed = validate_success(api.complete_coordination_work(water["id"], COORDINATOR))
    fixtures.respond_coordination(
        api, water["id"], "RE_REQUEST", response_note="main replaced, re-requesting clearance"
    )
    return ctx, water, completed


def test_second_round_clear_lands_in_cleared_after_work(api):
    """The same CLEAR trigger resolves to two target states on the round counter.

    PRD: "A `response` of `CLEAR` from a first-round row moves it to `CLEARED`; a
    `CLEAR` from a row whose `round_count` is 2 or more — meaning the utility
    already performed work in an earlier round — moves it to
    `CLEARED_AFTER_WORK` instead, which is what switches on the project's utility
    restoration share at the next estimate recompute."

    WATER runs the whole cycle and its second CLEAR lands in `CLEARED_AFTER_WORK`
    at round 2, while the SEWER row that answered once sits in `CLEARED` at
    round 1.

    Design: Difficulty/non_linear_state_machine/utility_coordination_cycle_ends_in_cleared_after_work_not_cleared
    """
    ctx, water, completed = _water_looped_roster(api)
    assert completed["coordination_status"] == "WORK_COMPLETE"
    assert completed["work_completed_at"] is not None

    cleared = fixtures.respond_coordination(
        api, water["id"], "CLEAR", response_note="clear after main replacement"
    )
    sewer = validate_success(
        api.get_coordination(fixtures.coordination_for(ctx, "SEWER")["id"], COORDINATOR)
    )

    assert cleared["coordination_status"] == "CLEARED_AFTER_WORK"
    assert cleared["round_count"] == 2
    assert sewer["coordination_status"] == "CLEARED"
    assert sewer["round_count"] == 1


def test_the_looped_row_switches_on_the_utility_restoration_share(api):
    """Only the looped outcome puts a restoration share into the priced estimate.

    PRD: "`utility_share_cents` covers the city's share of trench restoration and
    is the base multiplied by 3 percent, rounded to whole cents, but only when the
    project has at least one utility clearance row in `CLEARED_AFTER_WORK`;
    otherwise it is zero."

    The Maple St base of 10743323 yields a 322300-cent share, so the total lands
    at 12139955 rather than the 11817655 a four-times-CLEARED roster produces.

    Design: Difficulty/non_linear_state_machine/utility_coordination_cycle_ends_in_cleared_after_work_not_cleared
    """
    ctx, water, _completed = _water_looped_roster(api)
    fixtures.respond_coordination(
        api, water["id"], "CLEAR", response_note="clear after main replacement"
    )

    project = fixtures.advance(api, ctx["project"]["id"], "BID_READY")

    assert project["clearance_outstanding_count"] == 0
    assert_project_estimate(
        project,
        MAPLE_BUNDLE_BASE,
        MAPLE_CONTINGENCY,
        MAPLE_UTILITY_SHARE,
        MAPLE_TOTAL_WITH_UTILITY,
    )
    assert (
        project["project_total_estimate_cents"] - MAPLE_TOTAL == MAPLE_UTILITY_SHARE
    ), "the restoration share is the only difference from an all-CLEARED roster"


def _delivered_notice(api):
    """An awarded Maple St bundle whose single notice has been delivered once."""
    ctx = fixtures.maple_awarded(api)
    line_id = ctx["lines"]["Maple St"]["id"]
    scheduled = validate_success(
        api.notice(
            line_id,
            schedule_notice_payload(
                "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z", "MAINTAINED"
            ),
            ENGINEER,
        )
    )
    delivered = validate_success(api.notice(line_id, notice_payload("DELIVER"), ENGINEER))
    return ctx, line_id, scheduled, delivered


def test_reschedule_returns_the_delivered_notice_to_scheduled(api):
    """A backward edge out of the delivered sink, overwriting the whole window.

    PRD: "`RESCHEDULE` moves `notice_state` from `DELIVERED` back to `SCHEDULED`
    when a window has to move, and requires the line to be in `DELIVERED`, else
    `ERR_NOTICE_NOT_DELIVERED`; it also requires that the line's `work_state` is
    not yet `ACCEPTED`. A reschedule supplies a fresh window that must clear both
    gates again — at least 72 hours of lead time from the current logical clock,
    checked first, and no buffered closed-interval overlap with any sibling line's
    scheduled or delivered window on the same segment. It overwrites
    `parking_restriction_start`, `parking_restriction_end` and
    `driveway_access_plan`, clears `notice_delivered_at` back to null, and
    increments `notice_round` by 1."

    Design: Difficulty/non_linear_state_machine/notice_reschedule_cycle_rearms_construction_gate
    """
    _ctx, line_id, scheduled, delivered = _delivered_notice(api)
    assert scheduled["notice_state"] == "SCHEDULED"
    assert scheduled["notice_round"] == 1
    assert delivered["notice_state"] == "DELIVERED"
    assert delivered["notice_delivered_at"] is not None

    rescheduled = validate_success(
        api.notice(
            line_id,
            notice_payload(
                "RESCHEDULE",
                parking_restriction_start="2026-09-10T00:00:00Z",
                parking_restriction_end="2026-09-20T00:00:00Z",
                driveway_access_plan="LIMITED_NIGHTLY",
            ),
            ENGINEER,
        )
    )

    assert rescheduled["notice_state"] == "SCHEDULED"
    assert rescheduled["notice_round"] == 2
    assert rescheduled["notice_delivered_at"] is None
    assert rescheduled["parking_restriction_start"].startswith("2026-09-10T00:00:00")
    assert rescheduled["driveway_access_plan"] == "LIMITED_NIGHTLY"


def test_reschedule_revokes_the_already_earned_construction_permission(api):
    """The gate that a moment earlier was satisfied now rejects the same advance.

    PRD: "Every non-removed line must have `notice_state` `DELIVERED`, else
    `ERR_NOTICES_NOT_DELIVERED`."

    Design: Difficulty/non_linear_state_machine/notice_reschedule_cycle_rearms_construction_gate
    """
    ctx, line_id, _scheduled, _delivered = _delivered_notice(api)
    validate_success(
        api.notice(
            line_id,
            notice_payload(
                "RESCHEDULE",
                parking_restriction_start="2026-09-10T00:00:00Z",
                parking_restriction_end="2026-09-20T00:00:00Z",
                driveway_access_plan="LIMITED_NIGHTLY",
            ),
            ENGINEER,
        )
    )

    validate_error(
        api.advance_project(ctx["project"]["id"], {"action": "START_CONSTRUCTION"}, ENGINEER),
        ApiErrorId.NOTICES_NOT_DELIVERED,
        409,
    )

    assert fixtures.read_project(api, ctx["project"]["id"])["delivery_status"] == "AWARDED"
    assert fixtures.read_line(api, line_id)["work_state"] == "PLANNED"
    assert_money(ctx["award_amount_cents"], MAPLE_TOTAL)
