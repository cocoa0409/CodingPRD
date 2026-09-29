"""Compensating writes: voiding a controlled record and releasing a seat must each put
the conserved counter back to exactly the value it held before the write."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import medication_record_payload, visit_assignment_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS, make_health_care_staff_headers
from test_helpers.types import (
    AdministeredByRole,
    AssignmentStatus,
    CampType,
    Certification,
    HealthStaffingLevel,
    MedRecordStatus,
    MedicationClass,
    PopulationServed,
    StandardDomain,
    TeamRole,
)
from prd_bench_local_runner.testing import validate_error, validate_success

P_STANDARDS = [fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION)]

MICA_CAMP = {
    "name": "Mica Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 55,
    "health_staffing_level": HealthStaffingLevel.RN_ONSITE,
    "prior_accredited_cycle_count": 0,
}

MICA_CLOCK = "2026-08-11T12:00:00Z"

NORTH_CAMP = {
    "name": "North Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 50,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 0,
}


def _mica_at_the_dosing_ceiling(api):
    """Two 2-unit controlled doses for CR-88 leave the camper at the window ceiling."""
    camp = fx.register_camp(api, **MICA_CAMP)
    fx.set_clock(api, MICA_CLOCK)
    fx.receive_controlled_stock(api, camp["id"], 100)

    first = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-88",
        medication_class=MedicationClass.CONTROLLED,
        dose_units=2,
        administered_at="2026-08-11T08:00:00.000Z",
        administered_by_role=AdministeredByRole.RN,
        second_signature_present=True,
    )
    second = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-88",
        medication_class=MedicationClass.CONTROLLED,
        dose_units=2,
        administered_at="2026-08-11T09:00:00.000Z",
        administered_by_role=AdministeredByRole.RN,
        second_signature_present=True,
    )
    return {"camp": camp, "first": first, "second": second}


def _third_dose(api, camp_id):
    """The third 2-unit dose for CR-88, inside the same twenty-four hour window."""
    return api.create_medication_record(
        medication_record_payload(
            camp_id,
            camper_reference="CR-88",
            medication_class=MedicationClass.CONTROLLED,
            dose_units=2,
            administered_at="2026-08-11T10:00:00.000Z",
            administered_by_role=AdministeredByRole.RN,
            second_signature_present=True,
        ),
        make_health_care_staff_headers(camp_id),
    )


def _north_with_a_full_team(api):
    """A lead and a member both seated on one draft visit for the same travel block."""
    edition, _standards = fx.publish_edition_with_standards(api, "ACA-2026-P", P_STANDARDS)
    camp = fx.register_camp(api, **NORTH_CAMP)
    cycle = fx.open_cycle(api, camp["id"], edition["id"])
    visit = fx.open_visit(api, cycle["id"], "2026-09-01", "2026-09-10")

    captain = fx.add_visitor(
        api, "Captain Visitor", "PA", certifications=[Certification.LEAD_VISITOR]
    )
    crew = fx.add_visitor(api, "Crew Visitor", "NY")
    lead_seat = fx.seat_visitor(
        api, visit["id"], captain["id"], TeamRole.LEAD, "2026-09-01", "2026-09-03"
    )
    crew_seat = fx.seat_visitor(
        api, visit["id"], crew["id"], TeamRole.MEMBER, "2026-09-01", "2026-09-03"
    )
    return {
        "visit": visit,
        "captain": captain,
        "crew": crew,
        "lead_seat": lead_seat,
        "crew_seat": crew_seat,
    }


def test_voiding_a_dose_restores_the_controlled_ledger_to_the_cent(api):
    """PRD §3.9: "Voiding a record takes an optional `void_reason` and moves it
    `RECORDED → VOIDED`. Voided records leave the consumed set entirely, so the
    compensating write restores `controlled_on_hand_units` exactly to its pre-record value;
    the invariant that on-hand units plus consumed units equal `controlled_intake_units`
    holds after every request."

    Design: Difficulty/compensating_invariant/controlled_ledger_and_dosing_window_restored_exactly_after_void
    """
    world = _mica_at_the_dosing_ceiling(api)
    camp_id = world["camp"]["id"]
    assert fx.read_camp(api, camp_id)["controlled_on_hand_units"] == 96

    validate_error(
        _third_dose(api, camp_id), ApiErrorId.CONTROLLED_DOSE_WINDOW_EXCEEDED, 422
    )

    voided = fx.void_medication_record(
        api, camp_id, world["second"]["id"], "wrong camper handle transcribed"
    )
    assert voided["record_status"] == MedRecordStatus.VOIDED

    camp = fx.read_camp(api, camp_id)
    assert camp["controlled_on_hand_units"] == 98
    assert camp["controlled_intake_units"] == 100


def test_voiding_a_dose_also_frees_the_window_slot_for_a_replay(api):
    """PRD §3.9: "Last, the per-camper dosing window: at most two `RECORDED`
    `CONTROLLED` records may already exist for the same `camper_reference` in the
    twenty-four hours ending at the new `administered_at`, counting the window as
    half-open — it includes the instant twenty-four hours earlier and excludes
    `administered_at` itself."

    Design: Difficulty/compensating_invariant/controlled_ledger_and_dosing_window_restored_exactly_after_void
    """
    world = _mica_at_the_dosing_ceiling(api)
    camp_id = world["camp"]["id"]

    validate_error(
        _third_dose(api, camp_id), ApiErrorId.CONTROLLED_DOSE_WINDOW_EXCEEDED, 422
    )
    fx.void_medication_record(
        api, camp_id, world["second"]["id"], "wrong camper handle transcribed"
    )

    replayed = validate_success(_third_dose(api, camp_id), 201)
    assert replayed["record_status"] == MedRecordStatus.RECORDED

    camp = fx.read_camp(api, camp_id)
    assert camp["controlled_on_hand_units"] == 96
    assert camp["controlled_intake_units"] == 100

    assert (
        fx.read_medication_record(api, world["first"]["id"])["record_status"]
        == MedRecordStatus.RECORDED
    )
    assert (
        fx.read_medication_record(api, world["second"]["id"])["record_status"]
        == MedRecordStatus.VOIDED
    )


def test_withdrawing_a_seat_returns_the_visitors_commitment_to_zero(api):
    """PRD §3.5: "It moves the seat `ASSIGNED → WITHDRAWN`, decrements the visitor's
    `committed_travel_days` by that seat's `travel_days`, decrements the visit's `team_size` by
    one, and clears `lead_visitor_id` to null when the released seat was the `LEAD`."

    Design: Difficulty/compensating_invariant/visitor_committed_travel_days_restored_exactly_after_withdrawal
    """
    world = _north_with_a_full_team(api)
    assert fx.read_visitor(api, world["captain"]["id"])["committed_travel_days"] == 3

    double_booked = api.create_visit_assignment(
        visit_assignment_payload(
            world["visit"]["id"],
            world["captain"]["id"],
            TeamRole.MEMBER,
            "2026-09-02",
            "2026-09-04",
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(double_booked, ApiErrorId.VISITOR_TRAVEL_CONFLICT, 422)

    released = fx.withdraw_seat(api, world["lead_seat"]["id"], "family emergency")
    assert released["status"] == AssignmentStatus.WITHDRAWN
    assert released["withdrawal_reason"] == "family emergency"

    assert fx.read_visitor(api, world["captain"]["id"])["committed_travel_days"] == 0
    visit = fx.read_visit(api, world["visit"]["id"])
    assert visit["team_size"] == 1
    assert visit["lead_visitor_id"] is None

    # The other seat is untouched by the compensating write.
    assert (
        fx.read_assignment(api, world["crew_seat"]["id"])["status"]
        == AssignmentStatus.ASSIGNED
    )
    assert fx.read_visitor(api, world["crew"]["id"])["committed_travel_days"] == 3


def test_reseating_the_released_visitor_rebuilds_the_identical_commitment(api):
    """PRD §3.5: "Seats begin in `status` `ASSIGNED` with `withdrawal_reason` null;
    creating one recomputes the visitor's `committed_travel_days` and the visit's
    `team_size`, and a `LEAD` seat sets the visit's `lead_visitor_id`."

    Design: Difficulty/compensating_invariant/visitor_committed_travel_days_restored_exactly_after_withdrawal
    """
    world = _north_with_a_full_team(api)
    fx.withdraw_seat(api, world["lead_seat"]["id"], "family emergency")

    reseated = fx.seat_visitor(
        api,
        world["visit"]["id"],
        world["captain"]["id"],
        TeamRole.LEAD,
        "2026-09-01",
        "2026-09-03",
    )
    assert reseated["status"] == AssignmentStatus.ASSIGNED
    assert reseated["travel_days"] == 3
    assert reseated["withdrawal_reason"] is None

    assert fx.read_visitor(api, world["captain"]["id"])["committed_travel_days"] == 3
    visit = fx.read_visit(api, world["visit"]["id"])
    assert visit["team_size"] == 2
    assert visit["lead_visitor_id"] == world["captain"]["id"]
