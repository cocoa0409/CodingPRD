"""One write reaching three and four entity types away from the row it names."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_four_decimals,
    assert_index,
    assert_money,
    assert_pay_factor,
    assert_project_states,
    assert_scenario_totals,
    assert_segment_condition,
)
from test_helpers.constants import (
    CLOCK_2026_09_15,
    CLOCK_2026_10_01,
    MAPLE_CANDIDATE_COST,
    OBS_CS75,
    SOURCE_MODEL_PROJECTED,
    SOURCE_SURVEY_MEASURED,
)
from test_helpers.factories import accept_payload, service_request_payload
from test_helpers.test_users import ENGINEER, INSPECTOR_ACCEPTOR, OFFICER, RESIDENT


def _submitted_failing_test(api):
    """A pristine contractor and one SUBMITTED test that already reads FAIL."""
    ctx = fixtures.maple_in_construction(api)
    line_id = ctx["lines"]["Maple St"]["id"]
    submitted = fixtures.submit_test(
        api, line_id, core_density_pct=91.9, iri_in_per_mi=60.0, thickness_in=2.0
    )
    assert_pay_factor(submitted, 0.0000, "FAIL")
    assert submitted["test_round"] == 1

    contractor = fixtures.read_contractor(api, ctx["contractor"]["id"])
    assert contractor["standing"] == "GOOD_STANDING"
    assert contractor["interim_performance_score"] == 100.0
    return ctx, line_id, submitted


def test_fail_decision_cascades_from_the_test_to_the_line_and_the_project(api):
    """Levels one and two: the line breaks and the project's quality axis follows.

    PRD: "**First**, the line — again, provided the decided test holds the highest
    `test_round` on it — moves from `IN_PROGRESS` to `REMEDIATION_REQUIRED` with
    its `pay_factor` set to the failed test's `computed_pay_factor`. **Second**,
    the parent project's `open_remediation_count` increases by 1 and its
    `quality_status` moves from `TESTING` to `REMEDIATION_REQUIRED`, recounted as
    the number of its lines sitting in `REMEDIATION_REQUIRED`."

    Design: Difficulty/transitive_cascade/test_fail_cascades_line_to_project_quality_to_contractor_standing
    """
    ctx, line_id, submitted = _submitted_failing_test(api)

    decided = fixtures.decide_test(api, submitted["id"], "FAIL", "test decision recorded")
    line = fixtures.read_line(api, line_id)
    project = fixtures.read_project(api, ctx["project"]["id"])

    assert decided["test_status"] == "FAILED"
    assert decided["decided_by_user_id"] == "insp-decider-1"
    assert line["work_state"] == "REMEDIATION_REQUIRED"
    assert_four_decimals(line["pay_factor"], 0.0000, "pay_factor")
    assert line["test_count"] == 1
    assert_project_states(project, "IN_CONSTRUCTION", "REMEDIATION_REQUIRED")
    assert project["open_remediation_count"] == 1


def test_fail_decision_reaches_the_contractor_counters_and_its_standing(api):
    """Levels three and four: counters move, then the band derived from them moves.

    PRD: "**Third**, the contractor's `remediation_event_count` and
    `failed_test_count` each increase by 1 and its `interim_performance_score` is
    recomputed. **Fourth**, because the interim score dropped, the contractor's
    `standing` is re-derived into whichever band the new score implies —
    `GOOD_STANDING → WATCH` when the score lands at or above 60.0 but below 80.0,
    `GOOD_STANDING → SUSPENDED` when a contractor's only decided test fails and
    the score lands below 60.0, or `WATCH → SUSPENDED`."

    The firm's only decided test fails, so quality is 0.00, schedule stays 100.00
    on an in-flight project and remediation drops to 92.00: the composite is
    0.45*0.00 + 0.30*100.00 + 0.25*92.00 = 53.0, which is below the 60.0 floor.

    Design: Difficulty/transitive_cascade/test_fail_cascades_line_to_project_quality_to_contractor_standing
    """
    ctx, _line_id, submitted = _submitted_failing_test(api)

    fixtures.decide_test(api, submitted["id"], "FAIL", "test decision recorded")
    contractor = fixtures.read_contractor(api, ctx["contractor"]["id"])

    assert contractor["failed_test_count"] == 1
    assert contractor["passed_test_count"] == 0
    assert contractor["remediation_event_count"] == 1
    assert contractor["interim_performance_score"] == 53.0
    assert contractor["standing"] == "SUSPENDED"
    assert contractor["final_performance_score"] is None


def _project_ready_for_acceptance(api):
    """A substantially complete Maple St project carrying a permit and a complaint."""
    ctx = fixtures.maple_awarded(api)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]

    permit = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="WATER",
        requested_start="2026-11-01T00:00:00Z",
        requested_end="2026-11-05T00:00:00Z",
        cut_area_sqft=200.0,
        emergency=False,
    )
    assert permit["permit_status"] == "PENDING"
    assert permit["moratorium_remaining_days"] == 0
    assert permit["fee_multiplier"] == 1.0
    assert_money(permit["degradation_fee_cents"], 170000)

    request = validate_success(
        api.create_service_request(
            service_request_payload(
                segment_id,
                complaint_type="POTHOLE",
                reported_severity="HIGH",
                location_note="deep pothole at 1200 block driveway",
            ),
            RESIDENT,
        ),
        201,
    )
    fixtures.triage_service_request(
        api, request["id"], "DEFER_TO_CAPITAL", ctx["project"]["id"]
    )

    before = fixtures.read_segment(api, segment_id)
    assert before["open_service_request_count"] == 1
    assert before["moratorium_until"] is None
    assert_index(before["condition_index"], 69.1)
    assert before["active_project_count"] == 1

    ctx = fixtures.in_construction_project(api, ctx)
    ctx = fixtures.passing_test_on(api, ctx, "Maple St")
    fixtures.set_clock(api, CLOCK_2026_09_15)
    declared = fixtures.declare_substantial_completion(
        api, ctx["project"]["id"], ctx["contractor"]["id"]
    )
    assert declared["days_late"] == 0
    fixtures.set_clock(api, CLOCK_2026_10_01)
    return ctx, segment_id, permit["id"], request["id"]


def test_acceptance_cascades_into_the_line_and_the_resurfaced_segment(api):
    """Levels one and two of the widest cascade: the line, then the pavement itself.

    PRD: "**Second**, because each of those lines was accepted, its segment
    absorbs the new pavement: `last_treatment_type` records the line's
    `treatment_type`, `last_treatment_date` is set to the project's `accepted_at`,
    `baseline_condition_index` is reset to the smaller of 100.0 and the sum of the
    segment's current `condition_index` and the executing candidate's
    `treatment_pci_gain`, `condition_index` is set to that same value,
    `condition_index_source` becomes `MODEL_PROJECTED`, `condition_band` is
    recomputed, `active_project_count` is decremented, and `moratorium_until` is
    set to `accepted_at` plus the moratorium length for the treatment placed — one
    calendar year after a `CRACK_SEAL`, three calendar years after a
    `MILL_AND_OVERLAY`, and five calendar years after a `RECONSTRUCTION`."

    Maple St sat at 69.1 and its mill-and-overlay candidate carried a 30.9-point
    gain, so the rebuilt pavement reads exactly 100.0 and the three-year
    moratorium runs to 2029-10-01.

    Design: Difficulty/transitive_cascade/project_accept_cascades_segment_moratorium_to_cut_permit_to_service_request
    """
    ctx, segment_id, _permit_id, _request_id = _project_ready_for_acceptance(api)

    accepted = validate_success(
        api.accept_project(
            ctx["project"]["id"], accept_payload("final acceptance signed"), INSPECTOR_ACCEPTOR
        )
    )
    line = fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])
    segment = fixtures.read_segment(api, segment_id)

    assert accepted["delivery_status"] == "ACCEPTED"
    assert accepted["accepted_at"].startswith("2026-10-01T00:00:00")
    assert accepted["accepting_inspector_user_id"] == "insp-acceptor-1"
    assert line["work_state"] == "ACCEPTED"
    assert_segment_condition(segment, 100.0, SOURCE_MODEL_PROJECTED, "GOOD")
    assert segment["baseline_condition_index"] == 100.0
    assert segment["last_treatment_type"] == "MILL_AND_OVERLAY"
    assert segment["last_treatment_date"].startswith("2026-10-01T00:00:00")
    assert segment["moratorium_until"].startswith("2029-10-01T00:00:00")
    assert segment["active_project_count"] == 0


def test_acceptance_cascades_on_into_the_cut_permit_and_the_complaint(api):
    """Levels three and four: an untouched permit triples and a complaint closes.

    PRD: "**Third**, because `moratorium_until` advanced on those segments, every
    cut permit on them whose `permit_status` is `PENDING` moves to
    `MORATORIUM_REVIEW`, and its `moratorium_remaining_days`, `fee_multiplier` and
    `degradation_fee_cents` are recomputed against the new moratorium. **Fourth**,
    because those segments were resurfaced under this project, every complaint on
    them whose `request_status` is `DEFERRED_TO_CAPITAL` and whose
    `capital_project_id` is this project moves to `CLOSED_BY_CAPITAL` with
    `closure_code` `CAPITAL_RESURFACED` and `closed_at` set to `accepted_at`, its
    `sla_breached` flag recomputed, and the segment's
    `open_service_request_count` decremented."

    1096 days remain to 2029-10-01, which takes the 3.0 tier, so the 170000-cent
    fee becomes 510000 without the permit itself being touched.

    Design: Difficulty/transitive_cascade/project_accept_cascades_segment_moratorium_to_cut_permit_to_service_request
    """
    ctx, segment_id, permit_id, request_id = _project_ready_for_acceptance(api)

    validate_success(
        api.accept_project(
            ctx["project"]["id"], accept_payload("final acceptance signed"), INSPECTOR_ACCEPTOR
        )
    )
    permit = validate_success(api.get_cut_permit(permit_id, ENGINEER))
    request = validate_success(api.get_service_request(request_id, ENGINEER))
    segment = fixtures.read_segment(api, segment_id)

    assert permit["permit_status"] == "MORATORIUM_REVIEW"
    assert permit["moratorium_remaining_days"] == 1096
    assert permit["fee_multiplier"] == 3.0
    assert_money(permit["degradation_fee_cents"], 510000)
    assert request["request_status"] == "CLOSED_BY_CAPITAL"
    assert request["closure_code"] == "CAPITAL_RESURFACED"
    assert request["closed_at"].startswith("2026-10-01T00:00:00")
    assert segment["open_service_request_count"] == 0


def _later_survey_awaiting_seal(api):
    """A funded 2026 program plus an unsealed 2027 survey over the same block."""
    ctx = fixtures.computed_scenario(api, fixtures.MAPLE_ONLY)
    assert_scenario_totals(ctx["scenario"], 1, MAPLE_CANDIDATE_COST, 0)
    assert ctx["scenario"]["scenario_status"] == "COMPUTED"

    rows, _meta = validate_paginated(
        api.list_allocations(OFFICER, {"scenario_id": ctx["scenario"]["id"], "limit": 100})
    )
    assert len(rows) == 1
    allocation = rows[0]
    assert allocation["allocation_status"] == "FUNDED"
    assert_money(allocation["allocated_cents"], MAPLE_CANDIDATE_COST)
    assert allocation["rank"] == 1
    assert allocation["source"] == "AUTO_RUN"

    later = fixtures.open_survey(api, survey_year=2027)
    observation = fixtures.file_observation(
        api, later["id"], fixtures.segment_for(ctx, "Maple St")["id"], OBS_CS75
    )
    fixtures.accept_observation(api, observation["id"])
    return ctx, allocation, later


def test_sealing_a_later_survey_republishes_pavement_and_supersedes_candidates(api):
    """Levels one and two: the segment is republished and the older candidate dies.

    PRD: "**Second**, because those segments' condition changed, every treatment
    candidate whose `candidate_status` is `RECOMMENDED` or `OVERRIDDEN`, whose
    segment is one of those segments, and whose own `survey_id` is a *different*
    survey, moves to `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/survey_seal_cascades_segment_pci_to_candidate_to_allocation_to_scenario_totals
    """
    ctx, _allocation, later = _later_survey_awaiting_seal(api)
    candidate_id = fixtures.candidate_for(ctx, "Maple St")["id"]

    sealed = fixtures.seal_survey(api, later["id"])
    segment = fixtures.read_segment(api, fixtures.segment_for(ctx, "Maple St")["id"])
    candidate = fixtures.read_candidate(api, candidate_id)

    assert_index(sealed["network_condition_index"], 75.0)
    assert sealed["sealed_at"].startswith("2026-08-01T00:00:00")
    assert_segment_condition(segment, 75.0, SOURCE_SURVEY_MEASURED, "GOOD")
    assert candidate["candidate_status"] == "SUPERSEDED"


def test_sealing_a_later_survey_withdraws_allocations_and_rewrites_scenario_totals(api):
    """Levels three and four: a scenario the request never names loses its money.

    PRD: "**Third**, because those candidates were superseded, every scenario
    allocation referencing them whose `allocation_status` is `FUNDED` or
    `DEFERRED` moves to `WITHDRAWN`, and its `allocated_cents` is set to zero.
    **Fourth**, because those allocations were withdrawn, every affected scenario
    recomputes `allocation_count`, `funded_cost_cents` and `backlog_cents`."

    The 2026 scenario falls from allocation_count 1 and funded_cost_cents
    10743323 to zero on both, and stays `COMPUTED` throughout.

    Design: Difficulty/transitive_cascade/survey_seal_cascades_segment_pci_to_candidate_to_allocation_to_scenario_totals
    """
    ctx, allocation, later = _later_survey_awaiting_seal(api)

    fixtures.seal_survey(api, later["id"])
    withdrawn = validate_success(api.get_allocation(allocation["id"], OFFICER))
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])

    assert withdrawn["allocation_status"] == "WITHDRAWN"
    assert_money(withdrawn["allocated_cents"], 0)
    assert_scenario_totals(scenario, 0, 0, 0)
    assert scenario["scenario_status"] == "COMPUTED"
