"""Two interval resources with different arithmetic: buffered travel-day blocks on a
visitor, and the half-open per-camper controlled dosing window on a health centre."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import medication_record_payload, visit_assignment_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS, make_health_care_staff_headers
from test_helpers.types import (
    AdministeredByRole,
    AssignmentStatus,
    CampType,
    ComplianceFlag,
    CompliancePosture,
    HealthStaffingLevel,
    MedRecordStatus,
    MedicationClass,
    PopulationServed,
    StandardDomain,
    TeamRole,
)
from prd_bench_local_runner.testing import validate_error, validate_success

P_STANDARDS = [fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION)]

MESA_CAMP = {
    "name": "Mesa Day Camp",
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

MESA_CLOCK = "2026-08-11T12:00:00Z"


def _day_camp(name: str, state_code: str) -> dict:
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


def _rover_holding_one_block(api):
    """One visitor holds a 2026-09-01..2026-09-03 seat, with a second draft visit open."""
    edition, _standards = fx.publish_edition_with_standards(api, "ACA-2026-P", P_STANDARDS)

    east = fx.register_camp(api, **_day_camp("East Day Camp", "OH"))
    west = fx.register_camp(api, **_day_camp("West Day Camp", "PA"))
    cycle_east = fx.open_cycle(api, east["id"], edition["id"])
    cycle_west = fx.open_cycle(api, west["id"], edition["id"])

    visit_east = fx.open_visit(api, cycle_east["id"], "2026-09-01", "2026-09-10")
    visit_west = fx.open_visit(api, cycle_west["id"], "2026-09-05", "2026-09-14")

    rover = fx.add_visitor(api, "Rover Visitor", "NY")
    first_seat = fx.seat_visitor(
        api, visit_east["id"], rover["id"], TeamRole.MEMBER, "2026-09-01", "2026-09-03"
    )
    return {
        "visit_east": visit_east,
        "visit_west": visit_west,
        "rover": rover,
        "first_seat": first_seat,
    }


def _mesa_with_two_doses(api):
    """Two controlled doses already recorded for one camper handle."""
    camp = fx.register_camp(api, **MESA_CAMP)
    fx.set_clock(api, MESA_CLOCK)
    fx.receive_controlled_stock(api, camp["id"], 100)

    first = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-77",
        medication_class=MedicationClass.CONTROLLED,
        dose_units=1,
        administered_at="2026-08-10T08:00:00.000Z",
        administered_by_role=AdministeredByRole.RN,
        second_signature_present=True,
    )
    second = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-77",
        medication_class=MedicationClass.CONTROLLED,
        dose_units=1,
        administered_at="2026-08-10T14:00:00.000Z",
        administered_by_role=AdministeredByRole.RN,
        second_signature_present=True,
    )
    return {"camp": camp, "first": first, "second": second}


def _controlled_dose(api, camp_id, administered_at):
    """Attempt one more 1-unit controlled dose for CR-77 and return the raw response."""
    return api.create_medication_record(
        medication_record_payload(
            camp_id,
            camper_reference="CR-77",
            medication_class=MedicationClass.CONTROLLED,
            dose_units=1,
            administered_at=administered_at,
            administered_by_role=AdministeredByRole.RN,
            second_signature_present=True,
        ),
        make_health_care_staff_headers(camp_id),
    )


def test_two_day_gap_between_travel_blocks_is_inside_the_buffer(api):
    """PRD §3.5: "Then the travel-calendar rule: the visitor must hold no other seat in
    `ASSIGNED` or `COMPLETED` whose travel block, widened by two buffer days on each
    side, overlaps the requested block — a visitor released on the 10th cannot be seated
    again before the 13th — or the request is rejected with `ERR_VISITOR_TRAVEL_CONFLICT`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/visitor_travel_buffer_rejects_two_day_gap_and_admits_three_day_gap
    """
    world = _rover_holding_one_block(api)
    assert world["first_seat"]["travel_days"] == 3
    assert fx.read_visitor(api, world["rover"]["id"])["committed_travel_days"] == 3

    # The raw blocks 09-01..09-03 and 09-05..09-07 do not intersect at all.
    rejected = api.create_visit_assignment(
        visit_assignment_payload(
            world["visit_west"]["id"],
            world["rover"]["id"],
            TeamRole.MEMBER,
            "2026-09-05",
            "2026-09-07",
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(rejected, ApiErrorId.VISITOR_TRAVEL_CONFLICT, 422)

    assert fx.read_visitor(api, world["rover"]["id"])["committed_travel_days"] == 3
    _rows, meta = fx.list_seats_for_visitor(api, world["rover"]["id"])
    assert meta["total_count"] == 1


def test_three_day_gap_clears_the_buffer_and_adds_to_the_commitment(api):
    """PRD §3.5: "Seats begin in `status` `ASSIGNED` with `withdrawal_reason` null;
    creating one recomputes the visitor's `committed_travel_days` and the visit's
    `team_size`, and a `LEAD` seat sets the visit's `lead_visitor_id`."

    Design: Difficulty/resource_temporal_overlap/visitor_travel_buffer_rejects_two_day_gap_and_admits_three_day_gap
    """
    world = _rover_holding_one_block(api)

    second_seat = fx.seat_visitor(
        api,
        world["visit_west"]["id"],
        world["rover"]["id"],
        TeamRole.MEMBER,
        "2026-09-06",
        "2026-09-08",
    )
    assert second_seat["travel_days"] == 3
    assert second_seat["status"] == AssignmentStatus.ASSIGNED

    assert fx.read_visitor(api, world["rover"]["id"])["committed_travel_days"] == 6
    assert fx.read_visit(api, world["visit_west"]["id"])["team_size"] == 1
    assert fx.read_visit(api, world["visit_east"]["id"])["team_size"] == 1


def test_dose_at_exactly_twenty_four_hours_still_sees_the_earliest_dose(api):
    """PRD §3.9: "Last, the per-camper dosing window: at most two `RECORDED`
    `CONTROLLED` records may already exist for the same `camper_reference` in the
    twenty-four hours ending at the new `administered_at`, counting the window as
    half-open — it includes the instant twenty-four hours earlier and excludes
    `administered_at` itself."

    Design: Difficulty/resource_temporal_overlap/controlled_dose_window_half_open_boundary_at_exactly_24_hours
    """
    world = _mesa_with_two_doses(api)
    camp_id = world["camp"]["id"]

    camp = fx.read_camp(api, camp_id)
    assert camp["controlled_intake_units"] == 100
    assert camp["controlled_on_hand_units"] == 98
    assert camp["compliance_posture"] == CompliancePosture.OPEN
    for key in ("first", "second"):
        assert world[key]["compliance_flag"] == ComplianceFlag.COMPLIANT

    rejected = _controlled_dose(api, camp_id, "2026-08-11T08:00:00.000Z")
    validate_error(rejected, ApiErrorId.CONTROLLED_DOSE_WINDOW_EXCEEDED, 422)

    assert fx.read_camp(api, camp_id)["controlled_on_hand_units"] == 98
    _rows, meta = fx.list_medication_records_for_camp(api, camp_id)
    assert meta["total_count"] == 2


def test_one_millisecond_later_drops_the_earliest_dose_out_of_the_window(api):
    """PRD §3.9: "A successful `CONTROLLED` record recomputes the camp's
    controlled-substance balance, reducing `controlled_on_hand_units` by the dose."

    Design: Difficulty/resource_temporal_overlap/controlled_dose_window_half_open_boundary_at_exactly_24_hours
    """
    world = _mesa_with_two_doses(api)
    camp_id = world["camp"]["id"]

    validate_error(
        _controlled_dose(api, camp_id, "2026-08-11T08:00:00.000Z"),
        ApiErrorId.CONTROLLED_DOSE_WINDOW_EXCEEDED,
        422,
    )

    accepted = validate_success(
        _controlled_dose(api, camp_id, "2026-08-11T08:00:00.001Z"), 201
    )
    assert accepted["record_status"] == MedRecordStatus.RECORDED
    assert accepted["compliance_flag"] == ComplianceFlag.COMPLIANT

    camp = fx.read_camp(api, camp_id)
    assert camp["controlled_on_hand_units"] == 97
    assert camp["controlled_intake_units"] == 100
