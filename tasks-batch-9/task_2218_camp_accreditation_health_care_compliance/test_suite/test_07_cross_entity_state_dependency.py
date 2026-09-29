"""Transitions guarded by a status living on another entity: the state licensing axis
against visit confirmation, and a written plan's status against a self score."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import self_assessment_payload
from test_helpers.test_users import (
    OFFICER_ONE_HEADERS,
    OFFICER_ONE_ID,
    make_camp_director_headers,
)
from test_helpers.types import (
    CampType,
    Certification,
    CompliancePosture,
    CycleStatus,
    HealthStaffingLevel,
    PlanType,
    PopulationServed,
    SelfScore,
    SelfStatus,
    StandardDomain,
    StateLicenseStatus,
    TeamRole,
    VisitStatus,
    WrittenPlanStatus,
)
from prd_bench_local_runner.testing import is_iso8601_timestamp, validate_error

LARCH_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, requires_state_licensed=False
    )
]

WILLOW_STANDARDS = [
    fx.universal_mandatory_standard(
        "HW.7",
        domain=StandardDomain.HEALTH_WELLNESS,
        written_plan_type_required=PlanType.HEALTH_CARE,
    )
]


def _day_camp(name: str, max_daily_census: int) -> dict:
    return {
        "name": name,
        "camp_type": CampType.DAY,
        "state_code": "OH",
        "population_served": PopulationServed.YOUTH_ONLY,
        "program_elements": [],
        "resident_census": 0,
        "distance_to_hospital_km": 0,
        "max_daily_census": max_daily_census,
        "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
        "prior_accredited_cycle_count": 0,
    }


def _larch_ready_to_confirm(api):
    """A complete team seated on a draft visit while the licence sits at PENDING."""
    edition, standards = fx.publish_edition_with_standards(api, "ACA-2026-L", LARCH_STANDARDS)
    camp = fx.register_camp(api, **_day_camp("Larch Day Camp", 50))
    fx.move_state_license(api, camp["id"], StateLicenseStatus.PENDING)

    cycle = fx.open_cycle(api, camp["id"], edition["id"])
    evaluation = fx.evaluation_for_standard(
        api, cycle["id"], standards["SU.1"]["id"], camp["id"]
    )
    fx.record_self_score(api, evaluation["id"], camp["id"], SelfScore.MET)
    fx.submit_self_assessment(api, cycle["id"], camp["id"])

    lead = fx.add_visitor(api, "Lead One", "PA", certifications=[Certification.LEAD_VISITOR])
    member = fx.add_visitor(api, "Member Two", "NY")
    visit = fx.open_visit(api, cycle["id"])
    fx.seat_visitor(api, visit["id"], lead["id"], TeamRole.LEAD)
    fx.seat_visitor(api, visit["id"], member["id"], TeamRole.MEMBER)
    return {"camp": camp, "cycle": cycle, "visit": visit, "lead": lead}


def _willow_with_two_plans(api):
    """A HEALTH_CARE plan left at SUBMITTED beside a VERIFIED SUPERVISION plan."""
    edition, standards = fx.publish_edition_with_standards(api, "ACA-2026-W", WILLOW_STANDARDS)
    camp = fx.register_camp(api, **_day_camp("Willow Day Camp", 40))
    cycle = fx.open_cycle(api, camp["id"], edition["id"])

    health_plan = fx.file_plan(
        api,
        camp["id"],
        PlanType.HEALTH_CARE,
        body_ref="WILLOW-HC-2026",
        physician_reviewed=True,
        as_health_care_staff=True,
    )
    supervision_plan = fx.file_plan(
        api, camp["id"], PlanType.SUPERVISION, body_ref="WILLOW-SUP-2026"
    )
    fx.verify_plan(api, supervision_plan["id"], "supervision plan accepted")

    evaluation = fx.evaluation_for_standard(
        api, cycle["id"], standards["HW.7"]["id"], camp["id"]
    )
    return {
        "camp": camp,
        "cycle": cycle,
        "evaluation": evaluation,
        "health_plan": health_plan,
        "supervision_plan": supervision_plan,
    }


def test_pending_state_licence_blocks_confirmation_of_a_complete_team(api):
    """PRD §3.5: "The camp's `state_license_status` must be one of `NONE`, `ACTIVE` or
    `PROBATION`; both `PENDING` and `SUSPENDED` block confirmation with
    `ERR_STATE_LICENSE_BLOCKS_VISIT` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/visit_schedule_blocked_by_pending_state_license_then_allowed_after_reinstatement
    """
    world = _larch_ready_to_confirm(api)
    camp = fx.read_camp(api, world["camp"]["id"])
    assert camp["state_license_status"] == StateLicenseStatus.PENDING
    assert camp["compliance_posture"] == CompliancePosture.RESTRICTED

    rejected = api.schedule_visit(world["visit"]["id"], OFFICER_ONE_HEADERS)
    validate_error(rejected, ApiErrorId.STATE_LICENSE_BLOCKS_VISIT, 422)

    visit = fx.read_visit(api, world["visit"]["id"])
    assert visit["status"] == VisitStatus.DRAFT
    assert visit["scheduled_by_user_id"] is None
    # The team was never the blocker: both seats are in place with a lead.
    assert visit["team_size"] == 2
    assert visit["lead_visitor_id"] == world["lead"]["id"]
    assert fx.read_cycle(api, world["cycle"]["id"])["status"] == CycleStatus.SELF_ASSESSMENT


def test_reinstated_licence_lets_the_same_confirmation_through(api):
    """PRD §3.5: "Confirmation is an officer act with no body, moving the visit
    `DRAFT → SCHEDULED`, stamping `scheduled_by_user_id` with the acting `X-User-ID` — the
    value the segregation-of-duties rule will later compare against — and driving the
    cycle `SELF_ASSESSMENT → VISIT_SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/visit_schedule_blocked_by_pending_state_license_then_allowed_after_reinstatement
    """
    world = _larch_ready_to_confirm(api)
    validate_error(
        api.schedule_visit(world["visit"]["id"], OFFICER_ONE_HEADERS),
        ApiErrorId.STATE_LICENSE_BLOCKS_VISIT,
        422,
    )

    licensed = fx.move_state_license(
        api, world["camp"]["id"], StateLicenseStatus.ACTIVE, "OH-CAMP-44190"
    )
    assert licensed["state_license_status"] == StateLicenseStatus.ACTIVE
    assert licensed["state_license_number"] == "OH-CAMP-44190"
    assert licensed["compliance_posture"] == CompliancePosture.OPEN

    confirmed = fx.confirm_visit(api, world["visit"]["id"])
    assert confirmed["status"] == VisitStatus.SCHEDULED
    assert confirmed["scheduled_by_user_id"] == OFFICER_ONE_ID
    assert fx.read_cycle(api, world["cycle"]["id"])["status"] == CycleStatus.VISIT_SCHEDULED


def test_met_self_score_refuses_an_unverified_plan_and_a_verified_plan_of_the_wrong_type(api):
    """PRD §3.4: "And a `self_score` of `MET` on a standard whose pinned
    `written_plan_type_required` is not null requires `written_plan_id` to name a plan of
    that exact `plan_type`, belonging to the same camp, whose `status` is `VERIFIED`;
    otherwise the write is rejected with `ERR_WRITTEN_PLAN_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/self_score_met_requires_verified_written_plan_of_the_named_type
    """
    world = _willow_with_two_plans(api)
    director = make_camp_director_headers(world["camp"]["id"])
    assert fx.read_plan(api, world["health_plan"]["id"])["status"] == WrittenPlanStatus.SUBMITTED

    right_type_unverified = api.patch_self_assessment(
        world["evaluation"]["id"],
        self_assessment_payload(SelfScore.MET, world["health_plan"]["id"]),
        director,
    )
    validate_error(right_type_unverified, ApiErrorId.WRITTEN_PLAN_NOT_VERIFIED, 422)

    verified_wrong_type = api.patch_self_assessment(
        world["evaluation"]["id"],
        self_assessment_payload(SelfScore.MET, world["supervision_plan"]["id"]),
        director,
    )
    validate_error(verified_wrong_type, ApiErrorId.WRITTEN_PLAN_NOT_VERIFIED, 422)

    row = fx.read_evaluation(api, world["evaluation"]["id"])
    assert row["self_score"] is None
    assert row["written_plan_id"] is None
    assert row["self_status"] == SelfStatus.DRAFT
    assert (
        fx.read_plan(api, world["supervision_plan"]["id"])["status"]
        == WrittenPlanStatus.VERIFIED
    )


def test_verifying_the_named_plan_unblocks_the_met_self_score(api):
    """PRD §3.4: "`VERIFY` is accepted from `SUBMITTED` and from
    `REVALIDATION_REQUIRED`, moves the plan to `VERIFIED`, and stamps `verified_at` with
    the current logical clock instant and `reviewer_user_id` with the acting `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/self_score_met_requires_verified_written_plan_of_the_named_type
    """
    world = _willow_with_two_plans(api)

    verified = fx.verify_plan(api, world["health_plan"]["id"], "physician signature confirmed")
    assert verified["status"] == WrittenPlanStatus.VERIFIED
    assert is_iso8601_timestamp(verified["verified_at"])
    assert verified["reviewer_user_id"] == OFFICER_ONE_ID

    accepted = fx.record_self_score(
        api,
        world["evaluation"]["id"],
        world["camp"]["id"],
        SelfScore.MET,
        written_plan_id=world["health_plan"]["id"],
    )
    assert accepted["self_score"] == SelfScore.MET
    assert accepted["written_plan_id"] == world["health_plan"]["id"]
    assert accepted["self_status"] == SelfStatus.SUBMITTED
