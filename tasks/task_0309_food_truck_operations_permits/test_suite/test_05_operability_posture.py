"""Operability posture: soft-gate boundaries, the OPERABLE revenue gate, and the
condition-change recomputes (staffing, permit sweep, OCC version bump).

Queue A: boundary_precision_check/operability_psi_at_exact_threshold,
         cross_entity_state_dependency/booking_arrive_requires_truck_operable.
Queue B: cross_cutting_complexity_layers + entities (system field / initial state) corner instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_operable_truck, set_clock, add_propane,
    create_commissary, create_truck, issue_permit, add_shift,
    create_spot, create_event, reserve_booking, read_truck_version,
    api_client, TEST_USERS, make_operator_truck_headers,
    create_booking_payload, create_truck_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
HEALTH_INSPECTOR = TEST_USERS["health_inspector_headers"]


# ─── boundary_precision_check / operability_psi_at_exact_threshold ───────────

def test_operability_psi_at_exact_threshold_is_operable(api):
    """PRD §3.8: "Propane soft gate S1 holds when the truck's propane_psi is at least 20 (the
    minimum operating pressure); below 20 the gate fails."
    PRD §2.5: "If all hard gates hold and all soft gates hold, the truck is OPERABLE."

    With all other gates satisfied, propane at exactly 20 PSI satisfies S1 (>=) and the truck
    is OPERABLE.

    Design: Difficulty/boundary_precision_check/operability_psi_at_exact_threshold
    """
    # Build the truck with no propane, then set exactly the threshold.
    set_clock("2026-06-11T18:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    add_shift(truck["id"], "DRIVER", "2026-06-11T16:00:00.000Z", "2026-06-11T23:00:00.000Z", staff_name="Dee")
    add_shift(truck["id"], "COOK", "2026-06-11T16:00:00.000Z", "2026-06-11T23:00:00.000Z", staff_name="Coe")
    add_propane(truck["id"], 20)
    fresh = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert fresh["propane_psi"] == 20
    assert fresh["operability"] == "OPERABLE"


def test_operability_psi_just_below_threshold_is_restricted(api):
    """PRD §3.8: "Propane soft gate S1 holds when the truck's propane_psi is at least 20 (the
    minimum operating pressure); below 20 the gate fails."
    PRD §2.5: "If all hard gates hold but at least one soft gate fails, the truck is RESTRICTED."

    Propane at 19 (one below the 20-PSI minimum) fails S1, so the otherwise-ready truck is
    RESTRICTED, not OPERABLE — the X-1 side of the boundary.

    Design: Difficulty/boundary_precision_check/operability_psi_at_exact_threshold
    """
    set_clock("2026-06-25T18:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    add_shift(truck["id"], "DRIVER", "2026-06-25T16:00:00.000Z", "2026-06-25T23:00:00.000Z", staff_name="Dee")
    add_shift(truck["id"], "COOK", "2026-06-25T16:00:00.000Z", "2026-06-25T23:00:00.000Z", staff_name="Coe")
    add_propane(truck["id"], 19)
    fresh = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert fresh["propane_psi"] == 19
    assert fresh["operability"] == "RESTRICTED"


# ─── cross_entity_state_dependency / booking_arrive_requires_truck_operable ──

def test_arrive_rejected_when_truck_restricted(api):
    """PRD §3.4: "the owning truck's `operability` must be `OPERABLE` (else
    `ERR_TRUCK_NOT_OPERABLE`)."
    PRD §2.5: "A truck must be OPERABLE to mark a booking as arrived and to open a
    point-of-sale order."

    A RESTRICTED truck (missing its COOK shift) cannot arrive a RESERVED booking whose window
    contains the clock; the booking stays RESERVED.

    Design: Difficulty/cross_entity_state_dependency/booking_arrive_requires_truck_operable
    """
    set_clock("2026-06-13T18:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    add_propane(truck["id"], 50)
    add_shift(truck["id"], "DRIVER", "2026-06-13T16:00:00.000Z", "2026-06-13T23:00:00.000Z", staff_name="Dee")
    # No COOK shift -> soft gate S2 fails -> RESTRICTED.
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=0)
    event = create_event("2026-06-13T17:00:00.000Z", "2026-06-13T22:00:00.000Z")
    booking = reserve_booking(truck["id"], spot["id"], event["id"],
                              "2026-06-13T17:30:00.000Z", "2026-06-13T21:00:00.000Z")
    truck_fresh = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert truck_fresh["operability"] == "RESTRICTED"
    h = make_operator_truck_headers(truck["id"])
    res = api.arrive_booking(booking["id"], h)
    validate_error(res, "ERR_TRUCK_NOT_OPERABLE")
    after = validate_success(api.get_booking(booking["id"], DISPATCHER), 200)
    assert after["status"] == "RESERVED"


def test_arrive_succeeds_when_truck_operable(api):
    """PRD §3.4: "Arrive. The truck arrives at its spot, the transition RESERVED -> ARRIVED ...
    the owning truck's operability must be OPERABLE (else ERR_TRUCK_NOT_OPERABLE)."

    The positive side of the operability gate: an OPERABLE truck arrives a RESERVED booking
    whose window contains the clock, moving it to ARRIVED.

    Design: Difficulty/cross_entity_state_dependency/booking_arrive_requires_truck_operable
    """
    ctx = make_operable_truck("2026-06-26", "2026-06-26T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    assert ctx["truck"]["operability"] == "OPERABLE"
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=0)
    event = create_event("2026-06-26T17:00:00.000Z", "2026-06-26T22:00:00.000Z")
    booking = reserve_booking(truck_id, spot["id"], event["id"],
                              "2026-06-26T17:30:00.000Z", "2026-06-26T21:00:00.000Z")
    h = make_operator_truck_headers(truck_id)
    arrived = validate_success(api.arrive_booking(booking["id"], h), 200)
    assert arrived["status"] == "ARRIVED"


# ─── Corner: cross_cutting_complexity_layers ────────────────────────────────

def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §2.7: "If `expected_truck_version` does not equal the truck's current `version`, the
    booking create is rejected with `ERR_STALE_TRUCK_VERSION` (HTTP 412)."
    PRD §3.4: "The create also increments the truck's `version` by 1."

    A booking create carrying the truck's current version succeeds (201, RESERVED) and bumps
    the truck version by exactly 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    set_clock("2026-07-14T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=500)
    event = create_event("2026-07-14T17:00:00.000Z", "2026-07-14T22:00:00.000Z")
    version = read_truck_version(truck["id"])
    h = make_operator_truck_headers(truck["id"])
    res = api.create_booking(
        create_booking_payload(truck["id"], spot["id"], event["id"],
                               "2026-07-14T18:00:00.000Z", "2026-07-14T19:00:00.000Z", version), h)
    booking = validate_success(res, 201)
    assert booking["status"] == "RESERVED"
    after = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert after["version"] == version + 1


def test_permit_expiry_clock_sweep_grounds_truck(api):
    """PRD §3.2: "the permit lapses on its own when the wall clock advances to or past its
    expires_at: the clock sweep transitions it ACTIVE -> EXPIRED ... so hard gate H2 now fails
    and the truck is recomputed toward GROUNDED."
    PRD §3.10: "any ACTIVE permit whose expires_at is now at or before the clock transitions
    to EXPIRED, its truck's operability is recomputed."

    Advancing the clock to a permit's expires_at flips the permit EXPIRED and grounds its
    previously-OPERABLE truck.

    Design: Corner/cross_cutting_complexity_layers/permit_expiry_clock_sweep_grounds_truck
    """
    set_clock("2026-07-15T18:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    permit = issue_permit(truck["id"], expires_at="2026-07-15T20:00:00.000Z")
    add_propane(truck["id"], 50)
    add_shift(truck["id"], "DRIVER", "2026-07-15T16:00:00.000Z", "2026-07-15T23:00:00.000Z", staff_name="Dee")
    add_shift(truck["id"], "COOK", "2026-07-15T16:00:00.000Z", "2026-07-15T23:00:00.000Z", staff_name="Coe")
    before = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert before["operability"] == "OPERABLE"
    set_clock("2026-07-15T20:00:00.000Z")
    permit_after = validate_success(api.get_health_permit(permit["id"], HEALTH_INSPECTOR), 200)
    assert permit_after["status"] == "EXPIRED"
    truck_after = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert truck_after["operability"] == "GROUNDED"


def test_shift_cancel_lowers_operability(api):
    """PRD §3.8: "Cancelling a shift recomputes the owning truck's operability, which may drop
    the truck to RESTRICTED if the cancellation removed the last covering driver or cook."

    Cancelling the only covering COOK shift on an OPERABLE truck fails soft gate S2 and drops
    the truck to RESTRICTED.

    Design: Corner/cross_cutting_complexity_layers/shift_cancel_lowers_operability
    """
    set_clock("2026-07-17T18:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    add_propane(truck["id"], 50)
    add_shift(truck["id"], "DRIVER", "2026-07-17T16:00:00.000Z", "2026-07-17T23:00:00.000Z", staff_name="Dee")
    cook = add_shift(truck["id"], "COOK", "2026-07-17T16:00:00.000Z", "2026-07-17T23:00:00.000Z", staff_name="Coe")
    before = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert before["operability"] == "OPERABLE"
    h = make_operator_truck_headers(truck["id"])
    validate_success(api.cancel_staff_shift(cook["id"], h), 200)
    after = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert after["operability"] == "RESTRICTED"


# ─── Corner: entities (system field, initial state) ─────────────────────────

def test_truck_operability_system_field_input_ignored(api):
    """PRD §3.1: "On creation the truck's derived fields are initialized: operability is
    GROUNDED."
    PRD §2.5: "A truck's operability is never set directly by a client request."

    A freshly created truck (no permit / staffing) is GROUNDED regardless of client input.

    Design: Corner/entities/truck_operability_system_field_input_ignored
    """
    commissary = create_commissary()
    res = api.create_truck(create_truck_payload(commissary["id"]), DISPATCHER)
    truck = validate_success(res, 201)
    assert truck["operability"] == "GROUNDED"
