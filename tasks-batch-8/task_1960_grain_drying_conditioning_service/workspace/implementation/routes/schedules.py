"""Drying charge schedules: versioned tariff windows (PRD §3.3)."""

from flask import Blueprint, request

from db import parse_date, public, sort_by_creation, stamp_new, store, touch
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import get_schedule
from validation import get_body, opt_int, paginate, req_date, req_enum, req_int, req_num

bp = Blueprint("schedules", __name__)

COMMODITIES = {"CORN", "SOYBEAN", "WHEAT"}
READ_ROLES = {"ElevatorManager", "Grower", "IntakeTechnician"}


@bp.post("/charge-schedules")
def create_schedule():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    body = get_body()
    # priority 5: shape
    commodity = req_enum(body, "commodity", COMMODITIES)
    effective_from = req_date(body, "effective_from")
    effective_to = req_date(body, "effective_to")
    if parse_date(effective_from) > parse_date(effective_to):
        raise_err("ERR_INVALID_REQUEST", "effective_from must be on or before effective_to")
    t1_max = req_num(body, "t1_max_moisture_pct")
    t2_max = req_num(body, "t2_max_moisture_pct")
    rate_t1 = req_int(body, "rate_t1_cents_per_pt_bu", minimum=0)
    rate_t2 = req_int(body, "rate_t2_cents_per_pt_bu", minimum=0)
    rate_t3 = req_int(body, "rate_t3_cents_per_pt_bu", minimum=0)
    fm_threshold = req_num(body, "fm_threshold_pct", minimum=0.0)
    fm_surcharge = req_num(body, "fm_surcharge_pct", minimum=0.0)
    min_charge = req_int(body, "min_charge_cents", minimum=0)
    energy_t1_limit = req_num(body, "energy_t1_limit_therms", minimum=0.0)
    energy_t1_rate = req_int(body, "energy_t1_rate_cents_per_therm", minimum=0)
    energy_t2_rate = req_int(body, "energy_t2_rate_cents_per_therm", minimum=0)
    est_therms = req_num(body, "est_therms_per_hour", minimum=0.0)
    est_factor = req_num(body, "est_point_factor", minimum=0.0)
    # priority 10: closed-interval window overlap per commodity
    new_from, new_to = parse_date(effective_from), parse_date(effective_to)
    for s in store.schedules.values():
        if s["commodity"] != commodity:
            continue
        if new_from <= parse_date(s["effective_to"]) and parse_date(s["effective_from"]) <= new_to:
            raise_err("ERR_SCHEDULE_WINDOW_OVERLAP", "Tariff window overlaps an existing schedule for the same commodity")
    rec = stamp_new(
        {
            "commodity": commodity,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "t1_max_moisture_pct": t1_max,
            "t2_max_moisture_pct": t2_max,
            "rate_t1_cents_per_pt_bu": rate_t1,
            "rate_t2_cents_per_pt_bu": rate_t2,
            "rate_t3_cents_per_pt_bu": rate_t3,
            "fm_threshold_pct": fm_threshold,
            "fm_surcharge_pct": fm_surcharge,
            "min_charge_cents": min_charge,
            "energy_t1_limit_therms": energy_t1_limit,
            "energy_t1_rate_cents_per_therm": energy_t1_rate,
            "energy_t2_rate_cents_per_therm": energy_t2_rate,
            "est_therms_per_hour": est_therms,
            "est_point_factor": est_factor,
        }
    )
    store.schedules[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/charge-schedules")
def list_schedules():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = list(store.schedules.values())
    val = request.args.get("commodity")
    if val is not None:
        records = [r for r in records if r["commodity"] == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/charge-schedules/<sid>")
def get_one_schedule(sid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_schedule(sid)
    return success(public(rec))


@bp.patch("/charge-schedules/<sid>")
def update_schedule(sid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_schedule(sid)
    body = get_body()
    for field in (
        "rate_t1_cents_per_pt_bu",
        "rate_t2_cents_per_pt_bu",
        "rate_t3_cents_per_pt_bu",
        "min_charge_cents",
        "energy_t1_rate_cents_per_therm",
        "energy_t2_rate_cents_per_therm",
    ):
        if field in body and body[field] is not None:
            rec[field] = req_int(body, field, minimum=0)
    touch(rec)  # every revision bumps version, breaking issue pins (§2.7)
    return success(public(rec))
