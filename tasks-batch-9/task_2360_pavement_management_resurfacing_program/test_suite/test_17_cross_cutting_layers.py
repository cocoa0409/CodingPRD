"""Optimistic concurrency across two entities, and the two disagreeing lateness reads."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_area,
    assert_money,
    assert_project_estimate,
    assert_project_scope,
    assert_scenario_totals,
    assert_version_advanced,
)
from test_helpers.constants import (
    AREA_MAPLE,
    AREA_OAK,
    FUNDING_STANDARD,
    MAPLE_BUNDLE_BASE,
    MAPLE_CANDIDATE_COST,
    MAPLE_OAK_AREA,
    MAPLE_OAK_BASE,
    MAPLE_OAK_CONTINGENCY,
    MAPLE_OAK_TOTAL,
    OAK_CANDIDATE_COST,
    OAK_LINE_COST,
)
from test_helpers.factories import allocation_payload, project_segment_payload
from test_helpers.test_users import ENGINEER, OFFICER

# ----------------------------------------------------------------------
# Pinned literals
# ----------------------------------------------------------------------
MAPLE_LINE_WINDOW = ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")
OAK_LINE_WINDOW = ("2026-09-16T00:00:00Z", "2026-09-30T00:00:00Z")

MAPLE_ONLY_LINES = [("Maple St", *MAPLE_LINE_WINDOW)]
MAPLE_AND_OAK_FUNDED = 15343298

# planned_end_date is 2026-09-30, so this instant is exactly five whole days late.
LATE_COMPLETION_CLOCK = "2026-10-05T00:00:00Z"
LATE_COMPLETION_INSTANT = "2026-10-05T00:00:00"
LATE_DAYS = 5
LATE_SCHEDULE_COMPONENT = 87.50
FULL_COMPONENT = 100.00
FULL_COMPOSITE = 100.0
LATE_COMPOSITE = 96.3


def _oak_line_body(project_id, segment_id, candidate_id, version):
    return project_segment_payload(
        project_id,
        segment_id,
        candidate_id,
        version,
        work_window_start=OAK_LINE_WINDOW[0],
        work_window_end=OAK_LINE_WINDOW[1],
    )


# ----------------------------------------------------------------------
# The scenario token is spent by the caller's own previous add
# ----------------------------------------------------------------------


def test_a_manual_allocation_replaying_a_spent_scenario_version_is_refused(api):
    """The caller's own first add invalidates the token it captured for the second.

    PRD: "A `POST /pavement/scenario-allocations` request must carry
    `expected_scenario_version` matching the target `BudgetScenario`'s current
    `version`. Adding a manual allocation is legitimately repeatable — a second,
    strictly later request carrying a fresh version would itself succeed — so the
    stale-version check is the only deterministic guard available. Every scenario run,
    adoption, award, award cancellation and prior manual add advances that `version`;
    if the value supplied no longer equals the scenario's current `version`, the create
    is rejected with `ERR_STALE_SCENARIO_VERSION` and HTTP 412, preventing a client
    from adding to a funding picture it has not observed."

    PRD: "The manual row is created with `source` `MANUAL_ADD`, `allocation_status`
    `FUNDED`, `allocated_cents` equal to the candidate's `estimated_cost_cents`, and a
    `rank` one greater than the highest existing rank on the scenario; the parent then
    recomputes `allocation_count`, `funded_cost_cents` and `uncommitted_cents`, and its
    `version` increments."

    PRD: "A scenario's `allocation_count` counts its allocations that are funded or
    deferred, `funded_cost_cents` sums the allocated amounts of the funded ones,
    `backlog_cents` sums the estimated costs of the deferred ones"

    PRD: "`updated_at` is refreshed and `version` is incremented on every mutation of
    that resource, including mutations that only change derived fields."

    Design: Corner/cross_cutting_complexity_layers/manual_allocation_with_a_stale_scenario_version_returns_412
    """
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_AND_OAK)
    scenario = fixtures.create_scenario(
        api, ctx["survey"]["id"], funding_cents=FUNDING_STANDARD
    )
    scenario_id = scenario["id"]
    captured = scenario["version"]
    maple_candidate = fixtures.candidate_for(ctx, "Maple St")
    oak_candidate = fixtures.candidate_for(ctx, "Oak St")

    first = validate_success(
        api.create_allocation(
            allocation_payload(scenario_id, maple_candidate["id"], captured), OFFICER
        ),
        201,
    )
    assert first["rank"] == 1
    assert first["source"] == "MANUAL_ADD"
    assert first["allocation_status"] == "FUNDED"
    assert_money(first["allocated_cents"], MAPLE_CANDIDATE_COST)

    after_first = fixtures.read_scenario(api, scenario_id)
    assert_version_advanced(scenario, after_first)
    assert_scenario_totals(after_first, 1, MAPLE_CANDIDATE_COST, 0)

    validate_error(
        api.create_allocation(
            allocation_payload(scenario_id, oak_candidate["id"], captured), OFFICER
        ),
        ApiErrorId.STALE_SCENARIO_VERSION,
        412,
    )

    untouched = fixtures.read_scenario(api, scenario_id)
    assert untouched["version"] == after_first["version"]
    assert_scenario_totals(untouched, 1, MAPLE_CANDIDATE_COST, 0)

    second = validate_success(
        api.create_allocation(
            allocation_payload(scenario_id, oak_candidate["id"], untouched["version"]),
            OFFICER,
        ),
        201,
    )
    assert second["rank"] == first["rank"] + 1
    assert second["source"] == "MANUAL_ADD"
    assert second["allocation_status"] == "FUNDED"
    assert_money(second["allocated_cents"], OAK_CANDIDATE_COST)

    final = fixtures.read_scenario(api, scenario_id)
    assert_version_advanced(untouched, final)
    assert_scenario_totals(final, 2, MAPLE_AND_OAK_FUNDED, 0)


# ----------------------------------------------------------------------
# The project token is spent by the line the same client just added
# ----------------------------------------------------------------------


def test_a_second_line_added_on_a_superseded_project_read_is_refused(api):
    """The client's view of area and cost is stale, so the append is refused at 412.

    PRD: "A `POST /pavement/project-segments` request must carry
    `expected_project_version` matching the target `ResurfacingProject`'s current
    `version`. Adding lines is also legitimately repeatable, since each add names a
    different segment, so no state precondition can reject the later writer; the
    stale-version check is what protects a bundle whose cost, area and segment roster
    the client is reasoning about from a superseded read. A mismatch with the project's
    current `version` is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP 412."

    PRD: "Creation copies `treatment_type` from the candidate and `line_area_sy` from
    the segment's `area_sy`, computes the line's `line_cost_cents`, and starts the line
    at `work_state` `PLANNED`, `notice_state` `PENDING` and `notice_round` 1, with
    `parking_restriction_start`, `parking_restriction_end`, `driveway_access_plan`,
    `notice_delivered_at` and `pay_factor` all null and `test_count` zero."

    PRD: "The parent project increments `segment_count`, adds the line's
    `line_area_sy` to `planned_area_sy`, recomputes its estimate and increments its
    `version`; the referenced segment increments `active_project_count`."

    PRD: "One mobilisation charge is then added for the whole bundle: 250,000 cents
    when *every* non-removed line is a `CRACK_SEAL` line, and 850,000 cents
    otherwise."

    PRD: "`contingency_cents` is the base multiplied by that percentage, rounded to
    whole cents."

    Both segments sit in Z1 and the two windows are disjoint, so no zone, duplicate or
    occupancy rule can be what answered.

    Design: Corner/cross_cutting_complexity_layers/second_line_added_with_a_stale_project_version_returns_412
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, MAPLE_ONLY_LINES)
    project_id = ctx["project"]["id"]
    oak_segment = fixtures.segment_for(ctx, "Oak St")
    oak_candidate = fixtures.candidate_for(ctx, "Oak St")

    after_first = fixtures.read_project(api, project_id)
    captured = after_first["version"]
    assert_project_scope(after_first, 1, AREA_MAPLE)
    assert_money(after_first["bundle_base_cents"], MAPLE_BUNDLE_BASE)

    stale = captured - 1
    validate_error(
        api.create_project_segment(
            _oak_line_body(project_id, oak_segment["id"], oak_candidate["id"], stale),
            ENGINEER,
        ),
        ApiErrorId.STALE_PROJECT_VERSION,
        412,
    )

    untouched = fixtures.read_project(api, project_id)
    assert untouched["version"] == captured
    assert_project_scope(untouched, 1, AREA_MAPLE)

    line = validate_success(
        api.create_project_segment(
            _oak_line_body(project_id, oak_segment["id"], oak_candidate["id"], captured),
            ENGINEER,
        ),
        201,
    )
    assert_area(line["line_area_sy"], AREA_OAK)
    assert_money(line["line_cost_cents"], OAK_LINE_COST)

    final = fixtures.read_project(api, project_id)
    assert_project_scope(final, 2, MAPLE_OAK_AREA)
    assert_project_estimate(
        final, MAPLE_OAK_BASE, MAPLE_OAK_CONTINGENCY, 0, MAPLE_OAK_TOTAL
    )
    assert_version_advanced(untouched, final)


# ----------------------------------------------------------------------
# A refused write must not burn the token
# ----------------------------------------------------------------------


def test_two_refused_writes_leave_both_parents_versions_and_stamps_untouched(api):
    """A 422 on the project and a 409 on the scenario both spend nothing.

    PRD: "`updated_at` is refreshed and `version` is incremented on every mutation of
    that resource, including mutations that only change derived fields."

    PRD: "The candidate must reference the same segment as the line, else
    `ERR_CANDIDATE_SEGMENT_MISMATCH`."

    PRD: "Manual adds require the scenario to be `DRAFT` or `COMPUTED`, since an
    `ADOPTED` or `SUPERSEDED` scenario is frozen and reports `ERR_SCENARIO_FROZEN`."

    PRD: "**Stale-read protection**, else `ERR_STALE_SCENARIO_VERSION` or
    `ERR_STALE_PROJECT_VERSION`."

    PRD: "Creation copies `treatment_type` from the candidate and `line_area_sy` from
    the segment's `area_sy`, computes the line's `line_cost_cents`, and starts the line
    at `work_state` `PLANNED`, `notice_state` `PENDING` and `notice_round` 1, with
    `parking_restriction_start`, `parking_restriction_end`, `driveway_access_plan`,
    `notice_delivered_at` and `pay_factor` all null and `test_count` zero."

    The frozen-scenario refusal is itself proof that the version check passed before
    it, and the token the caller still holds is accepted by the corrected line add.

    Design: Corner/cross_cutting_complexity_layers/rejected_writes_leave_the_project_and_scenario_versions_untouched
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, MAPLE_ONLY_LINES)
    project_id = ctx["project"]["id"]
    scenario_id = ctx["scenario"]["id"]
    oak_segment = fixtures.segment_for(ctx, "Oak St")
    oak_candidate = fixtures.candidate_for(ctx, "Oak St")
    maple_candidate = fixtures.candidate_for(ctx, "Maple St")

    project_before = fixtures.read_project(api, project_id)
    scenario_before = fixtures.read_scenario(api, scenario_id)
    held_token = project_before["version"]

    validate_error(
        api.create_project_segment(
            _oak_line_body(
                project_id, oak_segment["id"], maple_candidate["id"], held_token
            ),
            ENGINEER,
        ),
        ApiErrorId.CANDIDATE_SEGMENT_MISMATCH,
        422,
    )

    project_after = fixtures.read_project(api, project_id)
    assert project_after["version"] == project_before["version"]
    assert project_after["updated_at"] == project_before["updated_at"]
    assert project_after["segment_count"] == 1

    validate_error(
        api.create_allocation(
            allocation_payload(
                scenario_id, oak_candidate["id"], scenario_before["version"]
            ),
            OFFICER,
        ),
        ApiErrorId.SCENARIO_FROZEN,
        409,
    )

    scenario_after = fixtures.read_scenario(api, scenario_id)
    assert scenario_after["version"] == scenario_before["version"]
    assert scenario_after["updated_at"] == scenario_before["updated_at"]
    assert scenario_after["allocation_count"] == scenario_before["allocation_count"]

    line = validate_success(
        api.create_project_segment(
            _oak_line_body(
                project_id, oak_segment["id"], oak_candidate["id"], held_token
            ),
            ENGINEER,
        ),
        201,
    )
    assert_area(line["line_area_sy"], AREA_OAK)
    assert line["work_state"] == "PLANNED"


# ----------------------------------------------------------------------
# Two lateness numbers that are supposed to disagree
# ----------------------------------------------------------------------


def test_a_late_completion_charges_the_interim_score_but_not_the_accepted_total(api):
    """The interim schedule component drops five days while `days_late_total` holds at zero.

    PRD: "The transition stamps `substantial_completion_at` from the logical clock and
    computes `days_late` as the number of whole days from `planned_end_date` to
    `substantial_completion_at`, floored at zero — an early or on-time finish records
    zero."

    PRD: "It counts test decisions and remediation events across *all* of the
    contractor's projects regardless of `delivery_status`, but counts schedule lateness
    only for projects that have reached `SUBSTANTIALLY_COMPLETE` or `ACCEPTED` — an
    in-flight project contributes zero late days even when the logical clock has
    already passed its `planned_end_date`."

    PRD: "The schedule component is 100 less 2.5 points per late day, clamped into 0.00
    through 100.00 and rounded to two decimal places."

    PRD: "The composite score is 0.45 times the quality component plus 0.30 times the
    schedule component plus 0.25 times the remediation component, rounded to one
    decimal place."

    PRD: "The rounding order is pinned: each component rounds to two decimal places
    first, and only then does the weighted sum round to one."

    PRD: "The **final** variant, stored as `final_performance_score`, is written on
    project acceptance and is restricted to projects whose `delivery_status` is
    `ACCEPTED`: only tests on lines of accepted projects feed its quality component,
    only remediation events on accepted projects feed its remediation component, and
    `days_late_total` — which sums `days_late` over accepted projects only — feeds its
    schedule component."

    PRD: "It remains null while `accepted_project_count` is zero."

    PRD: "`standing` is derived from `interim_performance_score` alone: `GOOD_STANDING`
    when the interim score is at least 80.0, `WATCH` when it is at least 60.0 but below
    80.0, and `SUSPENDED` when it is below 60.0."

    Design: Corner/cross_cutting_complexity_layers/late_completion_reconciles_the_interim_schedule_component_but_not_days_late_total
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.quality_accepted_project(api, ctx)
    contractor_id = ctx["contractor"]["id"]

    before = validate_success(api.get_contractor_scorecard(contractor_id, ENGINEER))
    assert before["interim_performance_score"] == FULL_COMPOSITE
    assert before["interim_schedule_component"] == FULL_COMPONENT

    fixtures.set_clock(api, LATE_COMPLETION_CLOCK)
    declared = fixtures.declare_substantial_completion(
        api, ctx["project"]["id"], contractor_id
    )
    assert declared["delivery_status"] == "SUBSTANTIALLY_COMPLETE"
    assert declared["substantial_completion_at"].startswith(LATE_COMPLETION_INSTANT)
    assert declared["days_late"] == LATE_DAYS

    after = validate_success(api.get_contractor_scorecard(contractor_id, ENGINEER))
    assert after["interim_quality_component"] == FULL_COMPONENT
    assert after["interim_schedule_component"] == LATE_SCHEDULE_COMPONENT
    assert after["interim_remediation_component"] == FULL_COMPONENT
    assert after["interim_performance_score"] == LATE_COMPOSITE
    assert after["standing"] == "GOOD_STANDING"
    assert after["passed_test_count"] == 1
    assert after["failed_test_count"] == 0
    assert after["days_late_total"] == 0
    assert after["accepted_project_count"] == 0
    assert after["final_performance_score"] is None

    row = fixtures.read_contractor(api, contractor_id)
    assert row["interim_performance_score"] == LATE_COMPOSITE
    assert row["days_late_total"] == 0
    assert row["final_performance_score"] is None
