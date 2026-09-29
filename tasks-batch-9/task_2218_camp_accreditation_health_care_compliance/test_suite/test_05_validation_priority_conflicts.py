"""Requests that break two rules at once, paired with a control call proving the
lower-priority rule was armed."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import self_assessment_payload, visit_assignment_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS, make_camp_director_headers
from test_helpers.types import (
    AssignmentStatus,
    CampType,
    Certification,
    CycleStatus,
    HealthStaffingLevel,
    PlanType,
    PopulationServed,
    SelfScore,
    SelfStatus,
    StandardDomain,
    TeamRole,
)
from prd_bench_local_runner.testing import validate_error

P_STANDARDS = [fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION)]


def _day_camp(name: str, state_code: str = "OH") -> dict:
    return {
        "name": name,
        "camp_type": CampType.DAY,
        "state_code": state_code,
        "population_served": PopulationServed.YOUTH_ONLY,
        "program_elements": [],
        "resident_census": 0,
        "distance_to_hospital_km": 0,
        "max_daily_census": 50,
        "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
        "prior_accredited_cycle_count": 0,
    }


def _two_camps_with_plans(api):
    """Alpha and Beta each hold their own SUPERVISION plan and their own open cycle."""
    edition, standards = fx.publish_edition_with_standards(api, "ACA-2026-P", P_STANDARDS)
    standard_id = standards["SU.1"]["id"]

    alpha = fx.register_camp(api, **_day_camp("Alpha Day Camp"))
    beta = fx.register_camp(api, **_day_camp("Beta Day Camp"))
    plan_alpha = fx.file_plan(
        api, alpha["id"], PlanType.SUPERVISION, body_ref="ALPHA-SUP-2026"
    )
    plan_beta = fx.file_plan(api, beta["id"], PlanType.SUPERVISION, body_ref="BETA-SUP-2026")

    cycle_alpha = fx.open_cycle(api, alpha["id"], edition["id"])
    cycle_beta = fx.open_cycle(api, beta["id"], edition["id"])
    ev_alpha = fx.evaluation_for_standard(api, cycle_alpha["id"], standard_id, alpha["id"])
    ev_beta = fx.evaluation_for_standard(api, cycle_beta["id"], standard_id, beta["id"])

    return {
        "alpha": alpha,
        "beta": beta,
        "plan_alpha": plan_alpha,
        "plan_beta": plan_beta,
        "cycle_alpha": cycle_alpha,
        "cycle_beta": cycle_beta,
        "ev_alpha": ev_alpha,
        "ev_beta": ev_beta,
    }


def _schedule_alphas_visit(api, world):
    """Take Alpha all the way to VISIT_SCHEDULED with a complete team."""
    alpha_id = world["alpha"]["id"]
    fx.record_self_score(api, world["ev_alpha"]["id"], alpha_id, SelfScore.MET)
    fx.submit_self_assessment(api, world["cycle_alpha"]["id"], alpha_id)

    lead = fx.add_visitor(
        api, "Lead One", "PA", certifications=[Certification.LEAD_VISITOR]
    )
    member = fx.add_visitor(api, "Member Two", "NY")
    visit = fx.open_visit(api, world["cycle_alpha"]["id"])
    fx.seat_visitor(api, visit["id"], lead["id"], TeamRole.LEAD)
    fx.seat_visitor(api, visit["id"], member["id"], TeamRole.MEMBER)
    fx.confirm_visit(api, visit["id"])
    return visit


def _host_and_other_camps(api):
    """Two draft visits and two visitors who each already hold an overlapping seat."""
    edition, _standards = fx.publish_edition_with_standards(api, "ACA-2026-P", P_STANDARDS)

    host = fx.register_camp(api, **_day_camp("Host Day Camp", "OH"))
    other = fx.register_camp(api, **_day_camp("Other Day Camp", "PA"))
    cycle_host = fx.open_cycle(api, host["id"], edition["id"])
    cycle_other = fx.open_cycle(api, other["id"], edition["id"])

    visit_host = fx.open_visit(api, cycle_host["id"], "2026-09-01", "2026-09-10")
    visit_other = fx.open_visit(api, cycle_other["id"], "2026-09-01", "2026-09-05")

    conflicted = fx.add_visitor(
        api, "Conflicted Visitor", "NY", employer_camp_id=host["id"]
    )
    clean = fx.add_visitor(api, "Clean Visitor", "NY")

    seats = {
        "conflicted": fx.seat_visitor(
            api, visit_other["id"], conflicted["id"], TeamRole.MEMBER,
            "2026-09-01", "2026-09-03",
        ),
        "clean": fx.seat_visitor(
            api, visit_other["id"], clean["id"], TeamRole.MEMBER,
            "2026-09-01", "2026-09-03",
        ),
    }
    return {
        "host": host,
        "visit_host": visit_host,
        "visit_other": visit_other,
        "conflicted": conflicted,
        "clean": clean,
        "seats": seats,
    }


def test_cycle_state_gate_outranks_the_cited_plans_camp_mismatch(api):
    """PRD §3.4: "The write is refused unless the cycle is in `SELF_ASSESSMENT`
    (`ERR_CYCLE_NOT_IN_SELF_ASSESSMENT`, HTTP 409), unless the row's `self_status` is
    something other than `VERIFIED` (`ERR_EVALUATION_LOCKED`, HTTP 409), and unless the
    row's `applicable` flag is true (`ERR_STANDARD_NOT_APPLICABLE`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_precondition_outranks_plan_camp_mismatch_on_self_assessment
    """
    world = _two_camps_with_plans(api)
    _schedule_alphas_visit(api, world)

    # The state family is settled before referential coherence, so the 409 wins.
    rejected = api.patch_self_assessment(
        world["ev_alpha"]["id"],
        self_assessment_payload(
            SelfScore.MET,
            world["plan_beta"]["id"],
            "wrong camp plan cited after the visit was scheduled",
        ),
        make_camp_director_headers(world["alpha"]["id"]),
    )
    validate_error(rejected, ApiErrorId.CYCLE_NOT_IN_SELF_ASSESSMENT, 409)

    row = fx.read_evaluation(api, world["ev_alpha"]["id"])
    assert row["written_plan_id"] is None
    assert row["self_status"] == SelfStatus.VERIFIED
    assert (
        fx.read_cycle(api, world["cycle_alpha"]["id"])["status"] == CycleStatus.VISIT_SCHEDULED
    )


def test_plan_camp_mismatch_fires_once_the_cycle_state_gate_passes(api):
    """PRD §3.4: "A cited plan must belong to the same camp as the evaluation's cycle, or
    the write is rejected with `ERR_PLAN_CAMP_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_precondition_outranks_plan_camp_mismatch_on_self_assessment
    """
    world = _two_camps_with_plans(api)

    assert fx.read_cycle(api, world["cycle_beta"]["id"])["status"] == CycleStatus.SELF_ASSESSMENT

    rejected = api.patch_self_assessment(
        world["ev_beta"]["id"],
        self_assessment_payload(
            SelfScore.MET,
            world["plan_alpha"]["id"],
            "wrong camp plan cited while still in self-assessment",
        ),
        make_camp_director_headers(world["beta"]["id"]),
    )
    validate_error(rejected, ApiErrorId.PLAN_CAMP_MISMATCH, 422)

    row = fx.read_evaluation(api, world["ev_beta"]["id"])
    assert row["self_status"] == SelfStatus.DRAFT
    assert row["self_score"] is None


def test_conflict_of_interest_outranks_the_overlapping_travel_block(api):
    """PRD §2.5: "And a seat request that violates the conflict-of-interest rule, the
    travel-calendar rule, the training-currency rule and the travel-block window rule all
    together reports the conflict of interest, because safety outranks quantitative
    constraints, which in turn outrank temporal ones."

    Design: Difficulty/priority_pair_validation_conflict/visitor_conflict_of_interest_outranks_travel_overlap_on_assignment
    """
    world = _host_and_other_camps(api)

    rejected = api.create_visit_assignment(
        visit_assignment_payload(
            world["visit_host"]["id"],
            world["conflicted"]["id"],
            TeamRole.MEMBER,
            "2026-09-02",
            "2026-09-04",
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(rejected, ApiErrorId.VISITOR_CONFLICT_OF_INTEREST, 422)

    assert fx.read_visitor(api, world["conflicted"]["id"])["committed_travel_days"] == 3
    host_visit = fx.read_visit(api, world["visit_host"]["id"])
    assert host_visit["team_size"] == 0
    assert host_visit["lead_visitor_id"] is None
    _rows, meta = fx.list_seats_for_visit(api, world["visit_host"]["id"])
    assert meta["total_count"] == 0


def test_travel_calendar_rule_fires_for_the_visitor_with_no_conflict_of_interest(api):
    """PRD §3.5: "Then the travel-calendar rule: the visitor must hold no other seat in
    `ASSIGNED` or `COMPLETED` whose travel block, widened by two buffer days on each
    side, overlaps the requested block — a visitor released on the 10th cannot be seated
    again before the 13th — or the request is rejected with `ERR_VISITOR_TRAVEL_CONFLICT`
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/visitor_conflict_of_interest_outranks_travel_overlap_on_assignment
    """
    world = _host_and_other_camps(api)

    rejected = api.create_visit_assignment(
        visit_assignment_payload(
            world["visit_host"]["id"],
            world["clean"]["id"],
            TeamRole.MEMBER,
            "2026-09-02",
            "2026-09-04",
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(rejected, ApiErrorId.VISITOR_TRAVEL_CONFLICT, 422)

    assert fx.read_visitor(api, world["clean"]["id"])["committed_travel_days"] == 3
    for key in ("conflicted", "clean"):
        assert (
            fx.read_assignment(api, world["seats"][key]["id"])["status"]
            == AssignmentStatus.ASSIGNED
        )
    _rows, meta = fx.list_seats_for_visit(api, world["visit_host"]["id"])
    assert meta["total_count"] == 0
