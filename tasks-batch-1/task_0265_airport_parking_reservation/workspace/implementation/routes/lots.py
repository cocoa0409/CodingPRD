"""Lot, RatePlan, CancellationPolicy endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_principal, require_roles
from response import success_array, success_object
from services.pagination import paginate
from services.records import make_record, touch
from services.serialize import (
    serialize_cancellation_policy,
    serialize_lot,
    serialize_rate_plan,
    serialize_shuttle_trip,
    serialize_stall_hold,
)
from services.validate import (
    optional_bool,
    optional_int,
    require_enum,
    require_int,
    require_object,
    require_str,
)

bp = Blueprint("lots", __name__)


# ---- Lot ----
@bp.post("/lots")
def create_lot():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin"})

    body = require_object(request.get_json(silent=True) or {})
    name = require_str(body, "name")
    kind = require_enum(body, "kind", {"SURFACE_LOT", "GARAGE", "VALET_GARAGE"})
    standard_capacity = require_int(body, "standard_capacity", minimum=0)
    oversized_capacity = require_int(body, "oversized_capacity", minimum=0)
    ev_capacity = require_int(body, "ev_capacity", minimum=0)
    in_out_allowed = optional_bool(body, "in_out_allowed", False)

    rec = make_record(
        {
            "name": name,
            "kind": kind,
            "standard_capacity": standard_capacity,
            "oversized_capacity": oversized_capacity,
            "ev_capacity": ev_capacity,
            "available_standard_count": standard_capacity,
            "available_oversized_count": oversized_capacity,
            "available_ev_count": ev_capacity,
            "in_out_allowed": in_out_allowed,
        }
    )
    store.lots[rec["id"]] = rec
    return success_object(serialize_lot(rec), status=201)


@bp.get("/lots/<lid>")
def get_lot(lid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator", "Customer"})
    rec = store.lots.get(lid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return success_object(serialize_lot(rec))


@bp.get("/lots")
def list_lots():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator", "Customer"})
    page, total, limit, offset = paginate(list(store.lots.values()))
    return success_array([serialize_lot(r) for r in page], limit, offset, total)


@bp.get("/lots/<lid>/rate-plans")
def list_lot_rate_plans(lid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator", "Customer"})
    if lid not in store.lots:
        raise err("ERR_NOT_FOUND")
    matches = [p for p in store.rate_plans.values() if p["lot_id"] == lid]
    page, total, limit, offset = paginate(matches)
    return success_array([serialize_rate_plan(r) for r in page], limit, offset, total)


@bp.get("/lots/<lid>/cancellation-policies")
def list_lot_policies(lid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator", "Customer"})
    if lid not in store.lots:
        raise err("ERR_NOT_FOUND")
    matches = [p for p in store.cancellation_policies.values() if p["lot_id"] == lid]
    page, total, limit, offset = paginate(matches)
    return success_array(
        [serialize_cancellation_policy(r) for r in page], limit, offset, total
    )


@bp.get("/lots/<lid>/stall-holds")
def list_lot_stall_holds(lid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator"})
    if lid not in store.lots:
        raise err("ERR_NOT_FOUND")
    matches = [h for h in store.stall_holds.values() if h["lot_id"] == lid]
    page, total, limit, offset = paginate(matches)
    return success_array([serialize_stall_hold(r) for r in page], limit, offset, total)


@bp.get("/lots/<lid>/shuttle-trips")
def list_lot_shuttle_trips(lid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator", "Customer"})
    if lid not in store.lots:
        raise err("ERR_NOT_FOUND")
    matches = [t for t in store.shuttle_trips.values() if t["lot_id"] == lid]
    page, total, limit, offset = paginate(matches)
    return success_array(
        [serialize_shuttle_trip(r) for r in page], limit, offset, total
    )


# ---- RatePlan ----
@bp.post("/rate-plans")
def create_rate_plan():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator"})

    body = require_object(request.get_json(silent=True) or {})
    lot_id = require_str(body, "lot_id")
    rate_mode = require_enum(body, "rate_mode", {"DAILY", "HOURLY", "VALET"})
    hourly_cents = optional_int(body, "hourly_cents", 0, minimum=0)
    daily_cap_cents = require_int(body, "daily_cap_cents", minimum=0)
    valet_surcharge_cents = optional_int(body, "valet_surcharge_cents", 0, minimum=0)
    oversized_multiplier_bps = optional_int(
        body, "oversized_multiplier_bps", 10000, minimum=10000
    )
    ev_surcharge_cents_per_day = optional_int(
        body, "ev_surcharge_cents_per_day", 0, minimum=0
    )

    if lot_id not in store.lots:
        raise err("ERR_NOT_FOUND")

    rec = make_record(
        {
            "lot_id": lot_id,
            "rate_mode": rate_mode,
            "hourly_cents": hourly_cents,
            "daily_cap_cents": daily_cap_cents,
            "valet_surcharge_cents": valet_surcharge_cents,
            "oversized_multiplier_bps": oversized_multiplier_bps,
            "ev_surcharge_cents_per_day": ev_surcharge_cents_per_day,
            "active": True,
        }
    )
    store.rate_plans[rec["id"]] = rec
    return success_object(serialize_rate_plan(rec), status=201)


@bp.get("/rate-plans/<rid>")
def get_rate_plan(rid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator", "Customer"})
    rec = store.rate_plans.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return success_object(serialize_rate_plan(rec))


@bp.post("/rate-plans/<rid>/retire")
def retire_rate_plan(rid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator"})
    rec = store.rate_plans.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    rec["active"] = False
    touch(rec)
    return success_object(serialize_rate_plan(rec))


# ---- CancellationPolicy ----
@bp.post("/cancellation-policies")
def create_cancellation_policy():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator"})

    body = require_object(request.get_json(silent=True) or {})
    lot_id = require_str(body, "lot_id")
    free_cancel_hours = require_int(body, "free_cancel_hours", minimum=0)
    late_cancel_fee_bps = optional_int(
        body, "late_cancel_fee_bps", 0, minimum=0, maximum=10000
    )
    prepay_discount_bps = optional_int(
        body, "prepay_discount_bps", 0, minimum=0, maximum=10000
    )

    if lot_id not in store.lots:
        raise err("ERR_NOT_FOUND")

    rec = make_record(
        {
            "lot_id": lot_id,
            "free_cancel_hours": free_cancel_hours,
            "late_cancel_fee_bps": late_cancel_fee_bps,
            "prepay_discount_bps": prepay_discount_bps,
        }
    )
    store.cancellation_policies[rec["id"]] = rec
    return success_object(serialize_cancellation_policy(rec), status=201)
