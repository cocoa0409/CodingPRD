"""Reservation endpoints: booking, reads, transitions (PRD §3.3 - §3.10)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_principal, require_roles
from response import success_array, success_object
from services import calculations as calc
from services import reservation_ops as ops
from services.inventory import available_count, recompute_lot_availability
from services.pagination import paginate
from services.records import make_payment_txn, make_record, touch
from services.serialize import (
    serialize_payment_txn,
    serialize_reservation,
    serialize_stall_hold,
)
from services.validate import (
    optional_bool,
    require_int,
    require_object,
    require_str,
)
from timeutil import parse_iso

bp = Blueprint("reservations", __name__)


def _derive_stall_class(vehicle):
    if vehicle["is_ev"]:
        return "EV"
    if vehicle["size_class"] == "OVERSIZED":
        return "OVERSIZED"
    return "STANDARD"


def _snapshot_rate_plan(plan):
    return {
        "rate_mode": plan["rate_mode"],
        "hourly_cents": plan["hourly_cents"],
        "daily_cap_cents": plan["daily_cap_cents"],
        "valet_surcharge_cents": plan["valet_surcharge_cents"],
        "oversized_multiplier_bps": plan["oversized_multiplier_bps"],
        "ev_surcharge_cents_per_day": plan["ev_surcharge_cents_per_day"],
    }


@bp.post("/reservations")
def create_reservation():
    user_id, role = get_principal()
    # priority 2: role.
    require_roles(role, {"Customer", "FacilityAdmin"})

    body = require_object(request.get_json(silent=True) or {})
    # Body well-formedness (ERR_VALIDATION) precedes business checks.
    customer_id = require_str(body, "customer_id")
    lot_id = require_str(body, "lot_id")
    vehicle_id = require_str(body, "vehicle_id")
    rate_plan_id = require_str(body, "rate_plan_id")
    scheduled_start_raw = require_str(body, "scheduled_start")
    scheduled_end_raw = require_str(body, "scheduled_end")
    scheduled_start = parse_iso(scheduled_start_raw)
    scheduled_end = parse_iso(scheduled_end_raw)
    prepaid = optional_bool(body, "prepaid", False)
    expected_lot_version = require_int(body, "expected_lot_version")

    # priority 3: ownership (Customer booking for own customer_id only).
    if role == "Customer" and user_id != customer_id:
        raise err("ERR_NOT_RESOURCE_OWNER")

    # priority 4: existence of every referenced resource.
    customer = store.customers.get(customer_id)
    lot = store.lots.get(lot_id)
    vehicle = store.vehicles.get(vehicle_id)
    plan = store.rate_plans.get(rate_plan_id)
    if customer is None or lot is None or vehicle is None or plan is None:
        raise err("ERR_NOT_FOUND")

    # priority 5: cross-reference.
    if vehicle["customer_id"] != customer_id or plan["lot_id"] != lot_id:
        raise err("ERR_CROSS_REFERENCE_MISMATCH")

    # priority 6: quotability.
    if not plan["active"]:
        raise err("ERR_RATE_PLAN_NOT_QUOTABLE")
    if plan["rate_mode"] == "VALET" and lot["kind"] != "VALET_GARAGE":
        raise err("ERR_RATE_PLAN_NOT_QUOTABLE")

    # priority 7: interval.
    now = store.current_utc()
    if not (scheduled_end > scheduled_start):
        raise err("ERR_INVALID_INTERVAL")
    if not (scheduled_start > now):
        raise err("ERR_INVALID_INTERVAL")

    # priority 9: customer suspension.
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_SUSPENDED")

    # priority 11: stale-lot version (OCC).
    if expected_lot_version != lot["version"]:
        raise err("ERR_STALE_LOT_VERSION")

    # priority 13: capacity for the derived class.
    stall_class = _derive_stall_class(vehicle)
    if available_count(lot, stall_class) < 1:
        raise err("ERR_NO_STALL_AVAILABLE")

    # ---- Commit atomic cascade ----
    snapshot = _snapshot_rate_plan(plan)

    reservation = make_record(
        {
            "customer_id": customer_id,
            "lot_id": lot_id,
            "vehicle_id": vehicle_id,
            "rate_plan_id": rate_plan_id,
            "shuttle_trip_id": None,
            "stall_class": stall_class,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "actual_in": None,
            "actual_out": None,
            "prepaid": prepaid,
            "occupancy_status": "BOOKED",
            "settlement_status": "UNSETTLED",
            "rate_snapshot": snapshot,
            "provisional_quote_cents": 0,
            "final_charge_cents": None,
            "overstay_cents": 0,
        }
    )

    # Create StallHold (HELD) -> recompute availability -> bump Lot.version.
    hold = make_record(
        {
            "lot_id": lot_id,
            "reservation_id": reservation["id"],
            "stall_class": stall_class,
            "hold_start": scheduled_start,
            "hold_end": scheduled_end,
            "status": "HELD",
        }
    )
    store.stall_holds[hold["id"]] = hold
    recompute_lot_availability(lot)

    # Provisional charge over planned interval + prepay discount.
    gross = calc.compute_parking_charge(
        snapshot, stall_class, scheduled_start, scheduled_end
    )
    policy = ops._policy_for_lot(lot_id)
    prepay_discount_bps = policy["prepay_discount_bps"] if policy else 0
    lead_minutes = (scheduled_start - now).total_seconds() / 60.0
    provisional, _discount = calc.compute_prepay_discount(
        gross, prepaid, lead_minutes, customer["no_show_strikes"], prepay_discount_bps
    )
    reservation["provisional_quote_cents"] = provisional

    store.reservations[reservation["id"]] = reservation

    # Prepaid: authorize the full provisional quote.
    if prepaid:
        reservation["settlement_status"] = "AUTHORIZED"
        make_payment_txn(
            reservation["id"], "AUTHORIZATION", provisional, "prepay authorization"
        )
        touch(reservation)

    return success_object(serialize_reservation(reservation), status=201)


@bp.get("/reservations/<rid>")
def get_reservation(rid):
    _, role = get_principal()
    require_roles(role, {"Customer", "LotOperator", "FacilityAdmin"})
    rec = store.reservations.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return success_object(serialize_reservation(rec))


@bp.get("/reservations")
def list_reservations():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator"})
    items = list(store.reservations.values())
    for field in ("lot_id", "vehicle_id", "rate_plan_id", "shuttle_trip_id"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    page, total, limit, offset = paginate(items)
    return success_array(
        [serialize_reservation(r) for r in page], limit, offset, total
    )


@bp.get("/reservations/<rid>/payment-txns")
def list_payment_txns(rid):
    _, role = get_principal()
    require_roles(role, {"Customer", "LotOperator", "FacilityAdmin"})
    if rid not in store.reservations:
        raise err("ERR_NOT_FOUND")
    matches = [t for t in store.payment_txns.values() if t["reservation_id"] == rid]
    page, total, limit, offset = paginate(matches)
    return success_array(
        [serialize_payment_txn(t) for t in page], limit, offset, total
    )


@bp.get("/reservations/<rid>/stall-holds")
def list_reservation_stall_holds(rid):
    _, role = get_principal()
    require_roles(role, {"Customer", "LotOperator", "FacilityAdmin"})
    if rid not in store.reservations:
        raise err("ERR_NOT_FOUND")
    matches = [h for h in store.stall_holds.values() if h["reservation_id"] == rid]
    page, total, limit, offset = paginate(matches)
    return success_array(
        [serialize_stall_hold(h) for h in page], limit, offset, total
    )


@bp.post("/reservations/<rid>/assign-shuttle")
def assign_shuttle(rid):
    user_id, role = get_principal()
    require_roles(role, {"Customer", "FacilityAdmin"})

    reservation = store.reservations.get(rid)
    if reservation is None:
        raise err("ERR_NOT_FOUND")

    # Ownership (priority 3) precedes body/FK existence here per §1.4 ordering.
    if role == "Customer" and user_id != reservation["customer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER")

    body = require_object(request.get_json(silent=True) or {})
    shuttle_trip_id = require_str(body, "shuttle_trip_id")
    expected_version = require_int(body, "expected_shuttle_trip_version")

    trip = store.shuttle_trips.get(shuttle_trip_id)
    if trip is None:
        raise err("ERR_NOT_FOUND")

    # OCC (priority 12) precedes the seat-acceptance business check (priority 14).
    if expected_version != trip["version"]:
        raise err("ERR_STALE_SHUTTLE_VERSION")

    # priority 14: serves the lot, seat-accepting state, not full.
    if (
        trip["lot_id"] != reservation["lot_id"]
        or trip["status"] not in ("SCHEDULED", "BOARDING")
        or trip["seats_taken"] >= trip["seat_capacity"]
    ):
        raise err("ERR_SHUTTLE_FULL")

    reservation["shuttle_trip_id"] = shuttle_trip_id
    touch(reservation)
    trip["seats_taken"] += 1
    touch(trip)

    return success_object(serialize_reservation(reservation))


def _load_reservation_for_transition(rid, allowed_roles):
    _, role = get_principal()
    require_roles(role, allowed_roles)
    rec = store.reservations.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return rec


@bp.post("/reservations/<rid>/check-in")
def check_in(rid):
    rec = _load_reservation_for_transition(rid, {"LotOperator", "FacilityAdmin"})
    ops.check_in(rec)
    return success_object(serialize_reservation(rec))


@bp.post("/reservations/<rid>/gate-exit")
def gate_exit(rid):
    rec = _load_reservation_for_transition(rid, {"LotOperator", "FacilityAdmin"})
    ops.gate_exit(rec)
    return success_object(serialize_reservation(rec))


@bp.post("/reservations/<rid>/gate-reentry")
def gate_reentry(rid):
    rec = _load_reservation_for_transition(rid, {"LotOperator", "FacilityAdmin"})
    ops.gate_reentry(rec)
    return success_object(serialize_reservation(rec))


@bp.post("/reservations/<rid>/check-out")
def check_out(rid):
    rec = _load_reservation_for_transition(rid, {"LotOperator", "FacilityAdmin"})
    ops.check_out(rec)
    return success_object(serialize_reservation(rec))


@bp.post("/reservations/<rid>/cancel")
def cancel(rid):
    user_id, role = get_principal()
    require_roles(role, {"Customer", "FacilityAdmin"})
    rec = store.reservations.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    # Ownership for Customer.
    if role == "Customer" and user_id != rec["customer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER")
    ops.cancel(rec)
    return success_object(serialize_reservation(rec))


@bp.post("/reservations/<rid>/mark-no-show")
def mark_no_show(rid):
    rec = _load_reservation_for_transition(rid, {"LotOperator", "FacilityAdmin"})
    ops.mark_no_show(rec)
    return success_object(serialize_reservation(rec))
