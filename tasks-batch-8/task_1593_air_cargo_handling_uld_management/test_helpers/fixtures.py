"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before each test, so nothing carries over). Setup
calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_BUILD_END,
    DEFAULT_BUILD_START,
    DG_INSPECTOR_USER,
    FWD_USER_1,
)
from .factories import (
    create_booking_payload,
    create_claim_payload,
    create_clock_payload,
    create_complete_repair_payload,
    create_customs_hold_payload,
    create_dg_declaration_payload,
    create_dg_rejection_payload,
    create_flight_payload,
    create_hold_release_payload,
    create_plan_payload,
    create_report_damage_payload,
    create_settle_payload,
    create_temperature_log_payload,
    create_uld_payload,
    create_uld_type_payload,
    create_weight_restriction_payload,
)
from .test_users import (
    TEST_USERS,
    make_dg_inspector_headers,
    make_forwarder_headers,
)

CC = TEST_USERS["capacity_controller_headers"]
RAMP = TEST_USERS["ramp_operator_headers"]
CUSTOMS = TEST_USERS["customs_officer_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# Single-call wrappers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers=None) -> None:
    get_success_data(api_client.set_clock(create_clock_payload(to_iso8601), headers or CC))


def make_flight(**overrides) -> dict:
    return get_success_data(api_client.create_flight(create_flight_payload(**overrides), CC))


def open_flight(flight_id: str) -> dict:
    return get_success_data(api_client.open_flight(flight_id, CC))


def make_open_flight(**overrides) -> dict:
    """Create a flight and open its booking window. Returns the flight."""
    flight = make_flight(**overrides)
    return open_flight(flight["id"])


def get_flight(flight_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_flight(flight_id, headers or CC))


def close_flight(flight_id: str) -> dict:
    return get_success_data(api_client.close_flight(flight_id, CC))


def depart_flight(flight_id: str) -> dict:
    return get_success_data(api_client.depart_flight(flight_id, CC))


def impose_weight_restriction(flight_id: str, restricted_payload_kg: float) -> dict:
    return get_success_data(
        api_client.impose_weight_restriction(
            flight_id, create_weight_restriction_payload(restricted_payload_kg), CC
        )
    )


def make_uld_type(**overrides) -> dict:
    return get_success_data(
        api_client.create_uld_type(create_uld_type_payload(**overrides), RAMP)
    )


def make_uld(uld_type_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_uld(create_uld_payload(uld_type_id, **overrides), RAMP)
    )


def make_uld_type_and_unit(type_overrides=None, **uld_overrides):
    """Register a ULD type and one physical unit. Returns (uld_type, uld)."""
    uld_type = make_uld_type(**(type_overrides or {}))
    uld = make_uld(uld_type["id"], **uld_overrides)
    return uld_type, uld


def get_uld(uld_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_uld(uld_id, headers or RAMP))


def make_booking(flight_id: str, user_id: str = FWD_USER_1, **overrides) -> dict:
    return get_success_data(
        api_client.create_booking(
            create_booking_payload(flight_id, **overrides),
            make_forwarder_headers(user_id),
        )
    )


def accept_booking(booking_id: str) -> dict:
    return get_success_data(api_client.accept_booking(booking_id, CC))


def make_accepted_booking(flight_id: str, user_id: str = FWD_USER_1, **overrides) -> dict:
    booking = make_booking(flight_id, user_id=user_id, **overrides)
    return accept_booking(booking["id"])


def get_booking(booking_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_booking(booking_id, headers or CC))


def create_build_up_plan(
    flight_id: str,
    uld_id: str,
    build_start: str = DEFAULT_BUILD_START,
    build_end: str = DEFAULT_BUILD_END,
) -> dict:
    """Create a DRAFT plan, reading the flight's current version for the OCC
    token (PRD §2.8) immediately before the write."""
    flight = get_flight(flight_id, RAMP)
    return get_success_data(
        api_client.create_build_up_plan(
            create_plan_payload(
                flight_id,
                uld_id,
                flight["version"],
                build_start=build_start,
                build_end=build_end,
            ),
            RAMP,
        )
    )


def get_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_build_up_plan(plan_id, headers or RAMP))


def assign_booking(plan_id: str, booking_id: str) -> dict:
    """Assign a booking, reading the plan's current version for the OCC token
    (PRD §2.8) immediately before the write. Returns the updated plan."""
    plan = get_plan(plan_id)
    return get_success_data(
        api_client.assign_booking_to_plan(
            plan_id,
            {
                "booking_id": booking_id,
                "expected_build_up_plan_version": plan["version"],
            },
            RAMP,
        )
    )


def seal_plan(plan_id: str) -> dict:
    return get_success_data(api_client.seal_plan(plan_id, RAMP))


def cancel_plan(plan_id: str) -> dict:
    return get_success_data(api_client.cancel_plan(plan_id, RAMP))


def file_dg_declaration(booking_id: str, user_id: str = FWD_USER_1, **overrides) -> dict:
    return get_success_data(
        api_client.create_dg_declaration(
            booking_id,
            create_dg_declaration_payload(**overrides),
            make_forwarder_headers(user_id),
        )
    )


def accept_dg_declaration(declaration_id: str, inspector_id: str = DG_INSPECTOR_USER) -> dict:
    return get_success_data(
        api_client.accept_dg_declaration(
            declaration_id, make_dg_inspector_headers(inspector_id)
        )
    )


def reject_dg_declaration(
    declaration_id: str,
    inspector_id: str = DG_INSPECTOR_USER,
    rejection_reason: str = "paperwork incomplete",
) -> dict:
    return get_success_data(
        api_client.reject_dg_declaration(
            declaration_id,
            create_dg_rejection_payload(rejection_reason),
            make_dg_inspector_headers(inspector_id),
        )
    )


def record_temperature(booking_id: str, recorded_at: str, temperature_c: float) -> dict:
    return get_success_data(
        api_client.create_temperature_log(
            booking_id, create_temperature_log_payload(recorded_at, temperature_c), RAMP
        )
    )


def place_customs_hold(booking_id: str, reason_code: str = "DOC_CHECK") -> dict:
    return get_success_data(
        api_client.create_customs_hold(
            booking_id, create_customs_hold_payload(reason_code), CUSTOMS
        )
    )


def release_customs_hold(hold_id: str, release_note: str = "cleared") -> dict:
    return get_success_data(
        api_client.release_customs_hold(
            hold_id, create_hold_release_payload(release_note), CUSTOMS
        )
    )


def file_claim(booking_id: str, user_id: str = FWD_USER_1, **overrides) -> dict:
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(booking_id, **overrides),
            make_forwarder_headers(user_id),
        )
    )


def approve_claim(claim_id: str) -> dict:
    return get_success_data(api_client.approve_claim(claim_id, ADJUSTER))


def settle_claim(claim_id: str, settlement_ref: str = "PAY-1001") -> dict:
    return get_success_data(
        api_client.settle_claim(claim_id, create_settle_payload(settlement_ref), ADJUSTER)
    )


def get_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers or ADJUSTER))


def get_uld_charge(charge_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_uld_charge(charge_id, headers or RAMP))


def list_uld_charges(uld_id: str, params=None, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_uld_charges(uld_id, headers or RAMP, params=params)
    )
    return data


def list_serviceable_ulds() -> list:
    data, _meta = validate_paginated(
        api_client.list_ulds(RAMP, params={"status": "SERVICEABLE"})
    )
    return data


def return_uld(uld_id: str) -> dict:
    return get_success_data(api_client.return_uld(uld_id, RAMP))


def report_uld_damage(uld_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.report_uld_damage(uld_id, create_report_damage_payload(**overrides), RAMP)
    )


def complete_uld_repair(uld_id: str, final_repair_cost: float = 275.5) -> dict:
    return get_success_data(
        api_client.complete_uld_repair(
            uld_id, create_complete_repair_payload(final_repair_cost), RAMP
        )
    )


# ---------------------------------------------------------------------------
# Composite chains
# ---------------------------------------------------------------------------

def setup_sealed_plan_scenario(
    flight_overrides=None,
    booking_overrides=None,
    uld_type_overrides=None,
    uld_code=None,
    build_start: str = DEFAULT_BUILD_START,
    build_end: str = DEFAULT_BUILD_END,
    user_id: str = FWD_USER_1,
) -> dict:
    """Open flight + ULD type/unit + one ACCEPTED booking BUILT_UP on a plan
    that is then SEALED. Returns every artifact keyed by name."""
    flight = make_open_flight(**(flight_overrides or {}))
    uld_type, uld = make_uld_type_and_unit(
        uld_type_overrides, **({"uld_code": uld_code} if uld_code else {})
    )
    booking = make_accepted_booking(flight["id"], user_id=user_id, **(booking_overrides or {}))
    plan = create_build_up_plan(flight["id"], uld["id"], build_start, build_end)
    assign_booking(plan["id"], booking["id"])
    plan = seal_plan(plan["id"])
    return {
        "flight": get_flight(flight["id"]),
        "uld_type": uld_type,
        "uld": get_uld(uld["id"]),
        "booking": get_booking(booking["id"]),
        "plan": plan,
    }


def setup_departed_scenario(
    flight_overrides=None,
    booking_overrides=None,
    uld_type_overrides=None,
    uld_code=None,
    depart_clock: str = None,
    user_id: str = FWD_USER_1,
) -> dict:
    """Sealed-plan scenario driven through close + depart: the plan is
    DEPARTED, the ULD DISPATCHED with a PROVISIONAL demurrage charge, and the
    booking LOADED. When depart_clock is given, the logical clock is set to
    that instant immediately before close/depart."""
    scenario = setup_sealed_plan_scenario(
        flight_overrides=flight_overrides,
        booking_overrides=booking_overrides,
        uld_type_overrides=uld_type_overrides,
        uld_code=uld_code,
        user_id=user_id,
    )
    if depart_clock is not None:
        set_clock(depart_clock)
    close_flight(scenario["flight"]["id"])
    depart_flight(scenario["flight"]["id"])
    charges = list_uld_charges(scenario["uld"]["id"])
    scenario["flight"] = get_flight(scenario["flight"]["id"])
    scenario["uld"] = get_uld(scenario["uld"]["id"])
    scenario["booking"] = get_booking(scenario["booking"]["id"])
    scenario["plan"] = get_plan(scenario["plan"]["id"])
    scenario["charge"] = charges[0] if charges else None
    return scenario


def setup_two_plan_departure(
    arrival: str = "2026-08-20T08:00:00Z",
    depart_clock: str = "2026-08-10T08:00:00Z",
) -> dict:
    """One flight with two ULDs on two SEALED plans (windows separated by the
    PRD §3.4 buffer), departed at depart_clock. Returns both units, plans,
    bookings, and their provisional demurrage charge ids."""
    flight = make_open_flight(
        scheduled_departure="2026-08-10T08:00:00Z",
        scheduled_arrival=arrival,
        max_payload_kg=1000,
        max_volume_m3=10,
        uld_position_count=2,
        dg_certified=True,
    )
    uld_type = make_uld_type(
        type_code="AKE", tare_weight_kg=100, max_gross_weight_kg=5000,
        internal_volume_m3=4.5,
    )
    uld1 = make_uld(uld_type["id"], uld_code="AKE00009CA")
    uld2 = make_uld(uld_type["id"], uld_code="AKE00010CA")
    booking1 = make_accepted_booking(flight["id"], shipper_ref="SHP-D3")
    booking2 = make_accepted_booking(flight["id"], shipper_ref="SHP-D4")
    plan1 = create_build_up_plan(
        flight["id"], uld1["id"], "2026-08-09T10:00:00Z", "2026-08-09T11:00:00Z"
    )
    plan2 = create_build_up_plan(
        flight["id"], uld2["id"], "2026-08-09T12:00:00Z", "2026-08-09T13:00:00Z"
    )
    assign_booking(plan1["id"], booking1["id"])
    assign_booking(plan2["id"], booking2["id"])
    seal_plan(plan1["id"])
    seal_plan(plan2["id"])
    if depart_clock is not None:
        set_clock(depart_clock)
    close_flight(flight["id"])
    depart_flight(flight["id"])
    return {
        "flight": get_flight(flight["id"]),
        "uld1": uld1,
        "uld2": uld2,
        "booking1": booking1,
        "booking2": booking2,
        "plan1": plan1,
        "plan2": plan2,
        "charge1": list_uld_charges(uld1["id"])[0],
        "charge2": list_uld_charges(uld2["id"])[0],
    }


def setup_two_loaded_bookings(declared_value_b: float = 8000) -> dict:
    """One departed flight with two LOADED bookings (100 kg each) on a single
    plan: booking A without declared_value, booking B with one."""
    flight = make_open_flight(
        scheduled_departure="2026-08-10T08:00:00Z",
        scheduled_arrival="2026-08-12T08:00:00Z",
        max_payload_kg=1000,
        max_volume_m3=10,
        uld_position_count=2,
        dg_certified=True,
    )
    uld_type, uld = make_uld_type_and_unit()
    booking_a = make_accepted_booking(
        flight["id"], shipper_ref="SHP-CA", pieces=2,
        gross_weight_kg=100, volume_m3=0.1,
    )
    booking_b = make_accepted_booking(
        flight["id"], shipper_ref="SHP-CB", pieces=2,
        gross_weight_kg=100, volume_m3=0.1, declared_value=declared_value_b,
    )
    plan = create_build_up_plan(flight["id"], uld["id"])
    assign_booking(plan["id"], booking_a["id"])
    assign_booking(plan["id"], booking_b["id"])
    seal_plan(plan["id"])
    close_flight(flight["id"])
    depart_flight(flight["id"])
    return {
        "flight": get_flight(flight["id"]),
        "uld": uld,
        "booking_a": get_booking(booking_a["id"]),
        "booking_b": get_booking(booking_b["id"]),
        "plan": get_plan(plan["id"]),
    }
