"""A write can be refused purely because a different entity is in the wrong state."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_values


def _draft_plan_for_discharged_resident(api, director):
    """A valid DRAFT plan whose resident has since left the census."""
    resident, assessment = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Harold Vance", "room_number": "140A",
                         "admission_date": "2026-01-11"},
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL"],
        effective_date="2026-07-20",
    )
    plan = fx.draft_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=2, cognitive=1),
    )
    validate_success(api.update_resident(resident["id"], {"status": "DISCHARGED"}, director), 200)
    return resident, plan


def test_plan_activation_requires_admitted_resident(api, therapist, director):
    """The plan's own DRAFT status admits ACTIVATE, so the refusal can only come from the
    resident's census status, and it must name that reason.

    PRD: "A plan activation blocked because the resident is `ON_LEAVE` reports
    `ERR_RESIDENT_NOT_ADMITTED`, never `ERR_PLAN_INVALID_STATE` — the latter speaks only
    about the plan's own status."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_requires_admitted_resident
    """
    _, plan = _draft_plan_for_discharged_resident(api, director)
    assert_values(fx.read_plan(api, plan["id"]), status="DRAFT")

    response = api.transition_activity_plan(plan["id"], {"action": "ACTIVATE"}, therapist)
    validate_error(response, ApiErrorId.RESIDENT_NOT_ADMITTED, 409)


def test_plan_activation_requires_admitted_resident_no_state_change(api, therapist, director):
    """The rejected activation leaves the dependent plan in DRAFT with no activation stamp,
    while the gating resident stays DISCHARGED.

    PRD: "a resident who is not `ADMITTED` may not be given a plan, may not have a plan
    activated, may not be enrolled in a session, and may not be added to an outing
    manifest, and each of those four refusals reports `ERR_RESIDENT_NOT_ADMITTED`."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_requires_admitted_resident
    """
    resident, plan = _draft_plan_for_discharged_resident(api, director)

    validate_error(
        api.transition_activity_plan(plan["id"], {"action": "ACTIVATE"}, therapist),
        ApiErrorId.RESIDENT_NOT_ADMITTED,
        409,
    )

    stored_plan = fx.read_plan(api, plan["id"])
    assert_values(stored_plan, status="DRAFT")
    assert stored_plan["activated_at"] is None, (
        f"A refused activation must leave activated_at null, got {stored_plan['activated_at']!r}"
    )
    assert_values(fx.read_resident(api, resident["id"]), status="DISCHARGED")


def _planning_outing_on_grounded_vehicle(api, director):
    """A PLANNING outing whose vehicle has been taken out of service, with a freshly read
    vehicle version so the concurrency guard cannot fire first."""
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Pearl Adeyemi", "room_number": "121A",
                         "admission_date": "2026-04-04"},
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-20",
    )
    program = fx.create_program(
        api, name="Museum Outing", domain="COGNITIVE", max_group_size=12
    )
    vehicle = fx.create_vehicle(
        api, label="Van 2", ambulatory_seats=8, wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="County Art Museum",
        departure_at="2026-08-14T09:00:00Z",
        return_at="2026-08-14T14:00:00Z",
        escort_count=1,
    )
    fx.add_rider(
        api,
        outing["id"],
        resident["id"],
        responsible_party_name="Femi Adeyemi",
        responsible_party_relation="ADULT_CHILD",
    )
    validate_success(
        api.update_vehicle(vehicle["id"], {"status": "OUT_OF_SERVICE"}, director), 200
    )
    return outing, vehicle, fx.vehicle_version(api, vehicle["id"])


def test_transport_booking_requires_available_vehicle(api, director):
    """The booking carries a matching vehicle version and a manifest that fits, so the only
    live objection is the vehicle's own status.

    PRD: "the vehicle must have `status` `AVAILABLE` at booking time, otherwise
    `ERR_VEHICLE_OUT_OF_SERVICE`"

    Design: Difficulty/cross_entity_state_dependency/transport_booking_requires_available_vehicle
    """
    outing, vehicle, fresh_version = _planning_outing_on_grounded_vehicle(api, director)
    assert_values(fx.read_vehicle(api, vehicle["id"]), status="OUT_OF_SERVICE")

    response = api.book_transport(
        outing["id"], {"expected_vehicle_version": fresh_version}, director
    )
    validate_error(response, ApiErrorId.VEHICLE_OUT_OF_SERVICE, 409)


def test_transport_booking_requires_available_vehicle_reserves_nothing(api, director):
    """The refused booking reserves no seat: the outing stays in PLANNING with no stored
    allocation and the vehicle's reservation counters stay at zero.

    PRD: "**No seat is reserved at planning time.**"

    Design: Difficulty/cross_entity_state_dependency/transport_booking_requires_available_vehicle
    """
    outing, vehicle, fresh_version = _planning_outing_on_grounded_vehicle(api, director)

    validate_error(
        api.book_transport(
            outing["id"], {"expected_vehicle_version": fresh_version}, director
        ),
        ApiErrorId.VEHICLE_OUT_OF_SERVICE,
        409,
    )

    stored_outing = fx.read_outing(api, outing["id"])
    assert_values(stored_outing, logistics_status="PLANNING", ambulatory_seats_required=0)
    stored_vehicle = fx.read_vehicle(api, vehicle["id"])
    assert_values(stored_vehicle, reserved_ambulatory_seats=0,
                  reserved_wheelchair_stations=0)
