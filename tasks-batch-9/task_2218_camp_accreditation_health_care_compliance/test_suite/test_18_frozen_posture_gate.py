"""A suspended licence alone freezes a camp with a clean penalty ledger, and the freeze gate
reaches the cycle, the schedule and controlled dosing while leaving over-the-counter care open.
"""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import cycle_payload, medication_record_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import (
    AdministeredByRole,
    CampType,
    Certification,
    CompliancePosture,
    CycleStatus,
    HealthIntakeStatus,
    HealthStaffingLevel,
    MedRecordStatus,
    MedicationClass,
    PopulationServed,
    SelfScore,
    StandardDomain,
    StateLicenseStatus,
    TeamRole,
    VisitStatus,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

FROZEN_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    )
]

FROZEN_TEAM = [
    {
        "key": "lead",
        "full_name": "Frozen Lead",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "member",
        "full_name": "Frozen Member",
        "home_state_code": "PA",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
    },
]


def _frozen_camp_holding_a_ready_draft_visit(api):
    """A complete team waits on a DRAFT visit when the state pulls the licence."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-FRZ",
        standards=FROZEN_STANDARDS,
        camp={
            "name": "Frozen Posture Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "health_staffing_level": HealthStaffingLevel.RN_ONSITE,
        },
        self_scores={"SU.1": SelfScore.MET},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        team=FROZEN_TEAM,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
    )
    fx.move_state_license(api, scenario.camp_id, StateLicenseStatus.ACTIVE, "OH-CAMP-77001")
    fx.move_state_license(api, scenario.camp_id, StateLicenseStatus.SUSPENDED)
    return scenario.refresh(api)


def test_a_suspended_licence_freezes_a_camp_that_owes_no_penalty_points(api):
    """PRD §2.7: "The posture is `FROZEN` when the camp's `penalty_point_balance` is at least
    12, or its `state_license_status` is `SUSPENDED`, or at least one deficiency of the camp
    sits in `ESCALATED`."

    Design: Corner/validations/frozen_posture_blocks_cycles_scheduling_and_controlled_records_but_not_over_the_counter_doses
    """
    scenario = _frozen_camp_holding_a_ready_draft_visit(api)

    assert scenario.camp["state_license_status"] == StateLicenseStatus.SUSPENDED
    assert scenario.camp["penalty_point_balance"] == 0
    assert scenario.camp["compliance_posture"] == CompliancePosture.FROZEN
    assert scenario.camp["health_intake_status"] == HealthIntakeStatus.SUSPENDED

    # The posture gate is read before the licence-specific scheduling rule.
    validate_error(
        api.schedule_visit(scenario.visit_id, OFFICER_ONE_HEADERS),
        ApiErrorId.CAMP_POSTURE_FROZEN,
        409,
    )
    held = fx.read_visit(api, scenario.visit_id)
    assert held["status"] == VisitStatus.DRAFT
    assert held["scheduled_by_user_id"] is None
    assert held["team_size"] == 2
    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.SELF_ASSESSMENT


def test_the_freeze_stops_a_controlled_dose_but_over_the_counter_care_continues(api):
    """PRD §3.9: "while the camp's posture is `FROZEN` — equivalently while its
    `health_intake_status` is `SUSPENDED` — a `CONTROLLED` or `PRESCRIPTION` record is refused
    with `ERR_CAMP_POSTURE_FROZEN`; an `OTC` record is still accepted."

    Design: Corner/validations/frozen_posture_blocks_cycles_scheduling_and_controlled_records_but_not_over_the_counter_doses
    """
    scenario = _frozen_camp_holding_a_ready_draft_visit(api)

    validate_error(
        api.create_medication_record(
            medication_record_payload(
                scenario.camp_id,
                camper_reference="CR-F1",
                medication_class=MedicationClass.CONTROLLED,
                dose_units=1,
                administered_at="2026-08-01T09:00:00.000Z",
                administered_by_role=AdministeredByRole.RN,
                second_signature_present=True,
            ),
            scenario.health_staff_headers,
        ),
        ApiErrorId.CAMP_POSTURE_FROZEN,
        409,
    )

    over_the_counter = fx.administer_medication(
        api,
        scenario.camp_id,
        camper_reference="CR-F2",
        medication_class=MedicationClass.OTC,
        dose_units=1,
        administered_at="2026-08-01T09:30:00.000Z",
        administered_by_role=AdministeredByRole.RN,
    )
    assert over_the_counter["record_status"] == MedRecordStatus.RECORDED
    assert over_the_counter["medication_class"] == MedicationClass.OTC


def test_the_freeze_refuses_a_new_cycle_that_could_not_collide_on_its_year(api):
    """PRD §3.3: "If the camp's posture is `FROZEN`, it is rejected with
    `ERR_CAMP_POSTURE_FROZEN`."

    Design: Corner/validations/frozen_posture_blocks_cycles_scheduling_and_controlled_records_but_not_over_the_counter_doses
    """
    scenario = _frozen_camp_holding_a_ready_draft_visit(api)

    validate_error(
        api.create_cycle(
            cycle_payload(
                scenario.camp_id,
                scenario.edition["id"],
                fx.read_camp(api, scenario.camp_id)["version"],
                2027,
            ),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.CAMP_POSTURE_FROZEN,
        409,
    )

    rows, meta = validate_paginated(
        api.list_cycles({"camp_id": scenario.camp_id}, OFFICER_ONE_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario.cycle_id


def test_restoring_the_licence_lets_the_same_schedule_through_unchanged(api):
    """PRD §3.1: "Restoring the licence with `SUSPENDED → ACTIVE` recomputes the posture and,
    only when the recomputed posture is not `FROZEN`, reopens `health_intake_status` to `OPEN`
    — a camp whose penalty balance is at least 12 or which holds an escalated deficiency stays
    frozen and stays closed to medication intake even after the licence is restored."

    Design: Corner/validations/frozen_posture_blocks_cycles_scheduling_and_controlled_records_but_not_over_the_counter_doses
    """
    scenario = _frozen_camp_holding_a_ready_draft_visit(api)

    # The stored licence number carries the restore, so no number is supplied again.
    restored = fx.move_state_license(api, scenario.camp_id, StateLicenseStatus.ACTIVE)
    assert restored["state_license_status"] == StateLicenseStatus.ACTIVE
    assert restored["state_license_number"] == "OH-CAMP-77001"
    assert restored["compliance_posture"] == CompliancePosture.OPEN
    assert restored["health_intake_status"] == HealthIntakeStatus.OPEN

    scheduled = validate_success(api.schedule_visit(scenario.visit_id, OFFICER_ONE_HEADERS))
    assert scheduled["status"] == VisitStatus.SCHEDULED
    assert scheduled["team_size"] == 2
    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.VISIT_SCHEDULED
