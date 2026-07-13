"""Composite setup helpers.

Each test runs against a freshly-booted, empty database, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient 2xx) so a broken precondition surfaces as a clear
"Setup step failed" rather than a confusing downstream assertion error.

Identity threading: the Operator role is entity_backed, so every ownership-gated
call (register vehicle, queue, dispatch, drive trip, appeal/pay, settle) uses
make_operator_headers(operator_id) with the real operator id — never the shared
constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_operator_headers,
)
from .factories import (
    create_operator_payload,
    create_vehicle_payload,
    create_permit_payload,
    create_staging_lot_payload,
    create_queue_entry_payload,
    create_curb_zone_payload,
    create_curb_assignment_payload,
    create_trip_payload,
    create_violation_payload,
    create_settlement_payload,
)

AA = TEST_USERS["airport_authority_headers"]
CC = TEST_USERS["curb_coordinator_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Move the logical clock to an absolute UTC instant."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, AA))


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------
def create_operator(api, operator_type="TNC", *, legal_name="Test Co",
                    contact_email="t@x.com", wheelchair_pledge_pct=None,
                    activate=False) -> dict:
    payload = create_operator_payload(
        legal_name=legal_name, operator_type=operator_type, contact_email=contact_email
    )
    if wheelchair_pledge_pct is not None:
        payload["wheelchair_pledge_pct"] = wheelchair_pledge_pct
    op = get_success_data(api.create_operator(payload, AA))
    if activate:
        op = get_success_data(
            api.transition_operator(op["id"], {"action": "ACTIVATE"}, AA)
        )
    return op


def transition_operator(api, operator_id, action, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api.transition_operator(operator_id, payload, AA))


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------
def register_vehicle(api, operator_id, *, plate="P1",
                     is_wheelchair_accessible=False) -> dict:
    payload = create_vehicle_payload(operator_id, plate=plate)
    if is_wheelchair_accessible:
        payload["is_wheelchair_accessible"] = True
    return get_success_data(
        api.create_vehicle(payload, make_operator_headers(operator_id))
    )


# ---------------------------------------------------------------------------
# Permit
# ---------------------------------------------------------------------------
def issue_permit(api, vehicle_id, expected_vehicle_version, *,
                 avi_tag_id="AVI-1", valid_from="2026-01-01T00:00:00Z",
                 valid_until="2027-01-01T00:00:00Z", fee_paid_cents=10000,
                 activate=False) -> dict:
    payload = create_permit_payload(
        vehicle_id, expected_vehicle_version,
        avi_tag_id=avi_tag_id, valid_from=valid_from,
        valid_until=valid_until, fee_paid_cents=fee_paid_cents,
    )
    permit = get_success_data(api.create_permit(payload, AA))
    if activate:
        permit = get_success_data(
            api.transition_permit(permit["id"], {"action": "ACTIVATE"}, AA)
        )
    return permit


# ---------------------------------------------------------------------------
# Staging lot / queue
# ---------------------------------------------------------------------------
def create_lot(api, *, name="Lot", capacity=5, geofence_center_lat=40.64,
               geofence_center_lng=-73.78, geofence_radius_m=5000) -> dict:
    payload = create_staging_lot_payload(
        name=name, capacity=capacity,
        geofence_center_lat=geofence_center_lat,
        geofence_center_lng=geofence_center_lng,
        geofence_radius_m=geofence_radius_m,
    )
    return get_success_data(api.create_staging_lot(payload, AA))


def queue_vehicle(api, operator_id, lot_id, vehicle_id, *, lat=40.64, lng=-73.78) -> dict:
    payload = create_queue_entry_payload(lot_id, vehicle_id, lat=lat, lng=lng)
    return get_success_data(
        api.create_queue_entry(payload, make_operator_headers(operator_id))
    )


# ---------------------------------------------------------------------------
# Curb
# ---------------------------------------------------------------------------
def create_curb_zone(api, *, name="Zone", terminal="T1", capacity=1) -> dict:
    payload = create_curb_zone_payload(name=name, terminal=terminal, capacity=capacity)
    return get_success_data(api.create_curb_zone(payload, AA))


def create_curb_assignment(api, curb_zone_id, trip_id, start_ts, end_ts) -> dict:
    payload = create_curb_assignment_payload(curb_zone_id, trip_id, start_ts, end_ts)
    return get_success_data(api.create_curb_assignment(payload, CC))


# ---------------------------------------------------------------------------
# Trip
# ---------------------------------------------------------------------------
def dispatch_trip(api, operator_id, vehicle_id, lot_id, *,
                  trip_kind=None, is_wheelchair_trip=None) -> dict:
    payload = create_trip_payload(vehicle_id, lot_id)
    if trip_kind is not None:
        payload["trip_kind"] = trip_kind
    if is_wheelchair_trip is not None:
        payload["is_wheelchair_trip"] = is_wheelchair_trip
    return get_success_data(
        api.create_trip(payload, make_operator_headers(operator_id))
    )


def transition_trip(api, operator_id, trip_id, action) -> dict:
    """Operator-driven trip transition (PICKUP, COMPLETE, CANCEL)."""
    return get_success_data(
        api.transition_trip(trip_id, {"action": action}, make_operator_headers(operator_id))
    )


def void_trip(api, trip_id) -> dict:
    """VOID is an AirportAuthority action."""
    return get_success_data(api.transition_trip(trip_id, {"action": "VOID"}, AA))


# ---------------------------------------------------------------------------
# Violation
# ---------------------------------------------------------------------------
def issue_violation(api, operator_id, violation_type, *, trip_id=None) -> dict:
    payload = create_violation_payload(operator_id, violation_type)
    if trip_id is not None:
        payload["trip_id"] = trip_id
    return get_success_data(api.create_violation(payload, AA))


def transition_violation_authority(api, violation_id, action) -> dict:
    """ASSESS, DISMISS, UPHOLD, OVERTURN, WAIVE."""
    return get_success_data(api.transition_violation(violation_id, {"action": action}, AA))


def transition_violation_operator(api, operator_id, violation_id, action) -> dict:
    """APPEAL, PAY (must own the violation's operator)."""
    return get_success_data(
        api.transition_violation(violation_id, {"action": action}, make_operator_headers(operator_id))
    )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
def open_settlement(api, operator_id, period_year, period_month) -> dict:
    payload = create_settlement_payload(operator_id, period_year, period_month)
    return get_success_data(api.create_settlement(payload, AA))


def close_settlement(api, settlement_id) -> dict:
    return get_success_data(api.transition_settlement(settlement_id, {"action": "CLOSE"}, AA))


def settle_settlement(api, operator_id, settlement_id, payment_amount_cents) -> dict:
    return get_success_data(
        api.transition_settlement(
            settlement_id,
            {"action": "SETTLE", "payment_amount_cents": payment_amount_cents},
            make_operator_headers(operator_id),
        )
    )


# ---------------------------------------------------------------------------
# High-level composite setups
# ---------------------------------------------------------------------------
def setup_queued_vehicle(api, *, operator_type="TNC", clock=None, wav_vehicle=False,
                         pledge=None, lot_capacity=5, avi_tag="AVI-1", plate="P1",
                         legal_name="Test Co", lat=40.64, lng=-73.78) -> dict:
    """Active operator + active-permitted vehicle staged at the head (position 1)
    of a lot's FIFO queue. This is the shared preamble for dispatch, fee, cascade,
    and curb scenarios. Returns dict(operator, vehicle, permit, lot, queue_entry)."""
    if clock:
        set_clock(api, clock)
    op = create_operator(api, operator_type=operator_type, legal_name=legal_name,
                         wheelchair_pledge_pct=pledge, activate=True)
    veh = register_vehicle(api, op["id"], plate=plate, is_wheelchair_accessible=wav_vehicle)
    permit = issue_permit(api, veh["id"], veh["version"], avi_tag_id=avi_tag, activate=True)
    lot = create_lot(api, capacity=lot_capacity)
    qe = queue_vehicle(api, op["id"], lot["id"], veh["id"], lat=lat, lng=lng)
    return {"operator": op, "vehicle": veh, "permit": permit, "lot": lot, "queue_entry": qe}


def setup_active_permitted_vehicle(api, *, operator_type="TNC", clock=None,
                                   wav_vehicle=False, avi_tag="AVI-1", plate="P1") -> dict:
    """Active operator + active-permitted vehicle + a lot, but NOT yet queued.
    Returns dict(operator, vehicle, permit, lot)."""
    if clock:
        set_clock(api, clock)
    op = create_operator(api, operator_type=operator_type, activate=True)
    veh = register_vehicle(api, op["id"], plate=plate, is_wheelchair_accessible=wav_vehicle)
    permit = issue_permit(api, veh["id"], veh["version"], avi_tag_id=avi_tag, activate=True)
    lot = create_lot(api)
    return {"operator": op, "vehicle": veh, "permit": permit, "lot": lot}


def setup_completed_trip(api, *, operator_type="TNC", clock=None, wav_vehicle=False,
                         trip_kind=None, is_wheelchair_trip=None, avi_tag="AVI-1") -> dict:
    """Full lifecycle: staged vehicle -> dispatch -> PICKUP -> COMPLETE. Returns
    dict(operator, vehicle, permit, lot, trip) with trip in COMPLETED state."""
    ctx = setup_queued_vehicle(api, operator_type=operator_type, clock=clock,
                               wav_vehicle=wav_vehicle, avi_tag=avi_tag)
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind=trip_kind, is_wheelchair_trip=is_wheelchair_trip)
    transition_trip(api, ctx["operator"]["id"], trip["id"], "PICKUP")
    trip = transition_trip(api, ctx["operator"]["id"], trip["id"], "COMPLETE")
    ctx["trip"] = trip
    return ctx


def setup_dispatched_trip(api, *, operator_type="TNC", clock=None,
                          trip_kind=None, avi_tag="AVI-1") -> dict:
    """Staged vehicle -> dispatch. Returns dict(operator, vehicle, permit, lot, trip)
    with the trip in DISPATCHED state."""
    ctx = setup_queued_vehicle(api, operator_type=operator_type, clock=clock, avi_tag=avi_tag)
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind=trip_kind)
    ctx["trip"] = trip
    return ctx


def setup_two_dispatched_trips(api, *, clock=None) -> dict:
    """Active operator with two active-permitted vehicles, each dispatched off a
    shared lot. Returns dict(operator, lot, trip1, trip2)."""
    if clock:
        set_clock(api, clock)
    op = create_operator(api, operator_type="TNC", activate=True)
    lot = create_lot(api, capacity=5)
    v1 = register_vehicle(api, op["id"], plate="V1")
    issue_permit(api, v1["id"], v1["version"], avi_tag_id="AVI-T1", activate=True)
    queue_vehicle(api, op["id"], lot["id"], v1["id"])
    t1 = dispatch_trip(api, op["id"], v1["id"], lot["id"], trip_kind="PICKUP")
    v2 = register_vehicle(api, op["id"], plate="V2")
    issue_permit(api, v2["id"], v2["version"], avi_tag_id="AVI-T2", activate=True)
    queue_vehicle(api, op["id"], lot["id"], v2["id"])
    t2 = dispatch_trip(api, op["id"], v2["id"], lot["id"], trip_kind="PICKUP")
    return {"operator": op, "lot": lot, "trip1": t1, "trip2": t2}


def setup_assessed_violation(api, operator_id, violation_type) -> dict:
    """Issue a violation of the given type against operator_id and ASSESS it.
    Returns the violation in ASSESSED state (may trigger auto-suspension)."""
    vio = issue_violation(api, operator_id, violation_type)
    return transition_violation_authority(api, vio["id"], "ASSESS")
