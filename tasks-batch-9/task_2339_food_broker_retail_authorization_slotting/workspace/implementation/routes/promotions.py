"""Promotions, samples and demo coordination (PRD section 3.8)."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize
from services import calc, domain

bp = Blueprint("promotions", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "authorization_id": rec["authorization_id"],
        "event_type": rec["event_type"],
        "store_code": rec["store_code"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "planned_funding_cents": rec["planned_funding_cents"],
        "sample_units_requested": rec["sample_units_requested"],
        "actual_funding_cents": rec["actual_funding_cents"],
        "settled_funding_cents": rec["settled_funding_cents"],
        "state": rec["state"],
        "committed_at": rec["committed_at"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/promotion-events")
def plan_promotion():
    authorize("BrokerAccountManager")
    data = v.body()

    authorization_id = v.req_id(data, "authorization_id")
    event_type = v.req_enum(data, "event_type", v.EVENT_TYPES)
    window_start, window_start_text = v.req_instant_raw(data, "window_start")
    window_end, window_end_text = v.req_instant_raw(data, "window_end")
    planned_funding = v.req_int(data, "planned_funding_cents", 0)

    if event_type == "DEMO_SAMPLING":
        store_code = v.req_string(data, "store_code")
        sample_units = v.req_int(data, "sample_units_requested", 1)
    else:
        v.forbid(data, "store_code", "unless event_type is DEMO_SAMPLING")
        store_code = None
        sample_units = v.opt_int(data, "sample_units_requested", 0, 0)

    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'window_end' must be strictly after 'window_start'.",
        )

    auth = db.get("authorizations", authorization_id)

    rec = db.base_record()
    rec.update({
        "authorization_id": auth["id"],
        "event_type": event_type,
        "store_code": store_code,
        "window_start": window_start_text,
        "window_end": window_end_text,
        "planned_funding_cents": planned_funding,
        "sample_units_requested": sample_units,
        "actual_funding_cents": 0,
        "settled_funding_cents": 0,
        "state": "PLANNED",
        "committed_at": None,
    })
    db.insert("promotions", rec)
    return response.created(serialize(rec))


@bp.get("/promotion-events/<promotion_event_id>")
def read_promotion(promotion_event_id):
    authorize(*ALL_ROLES)
    return response.ok(serialize(db.get("promotions", promotion_event_id)))


@bp.get("/promotion-events")
def list_promotions():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    authorization_id = v.filter_value("authorization_id")
    event_type = v.filter_value("event_type")
    store_code = v.filter_value("store_code")
    state = v.filter_value("state")
    rows = []
    for rec in db.ordered("promotions"):
        if authorization_id is not None and rec["authorization_id"] != authorization_id:
            continue
        if event_type is not None and rec["event_type"] != event_type:
            continue
        if store_code is not None and rec["store_code"] != store_code:
            continue
        if state is not None and rec["state"] != state:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/promotion-events/<promotion_event_id>/commit")
def commit_promotion(promotion_event_id):
    authorize("BrokerAccountManager")
    rec = db.get("promotions", promotion_event_id)

    if rec["state"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")

    auth = db.find("authorizations", rec["authorization_id"])
    state = auth["authorization_state"] if auth is not None else None
    if state == "AT_RISK":
        raise ApiError("ERR_AUTHORIZATION_AT_RISK")
    if state != "AUTHORIZED":
        raise ApiError("ERR_AUTHORIZATION_NOT_AUTHORIZED")

    window_start = clock.parse_instant(rec["window_start"])
    window_end = clock.parse_instant(rec["window_end"])
    if window_start < clock.now():
        raise ApiError("ERR_PROMO_WINDOW_IN_PAST")

    if rec["event_type"] == "DEMO_SAMPLING":
        retailer = db.find("retailers", auth["retailer_id"])
        buffer_minutes = retailer["demo_changeover_buffer_minutes"] if retailer else 0
        capacity = retailer["max_concurrent_demos"] if retailer else 1
        buffer = timedelta(minutes=buffer_minutes)
        occupied = 0
        for other in db.ordered("promotions"):
            if other["id"] == rec["id"]:
                continue
            if other["event_type"] != "DEMO_SAMPLING":
                continue
            if other["state"] not in ("COMMITTED", "EXECUTED"):
                continue
            if other["store_code"] != rec["store_code"]:
                continue
            other_auth = db.find("authorizations", other["authorization_id"])
            if other_auth is None or other_auth["retailer_id"] != auth["retailer_id"]:
                continue
            other_start = clock.parse_instant(other["window_start"]) - buffer
            other_end = clock.parse_instant(other["window_end"]) + buffer
            if other_start < window_end and window_start < other_end:
                occupied += 1
        if occupied >= capacity:
            raise ApiError("ERR_DEMO_SLOT_CAPACITY")

    rec["state"] = "COMMITTED"
    rec["committed_at"] = clock.iso_now()
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/promotion-events/<promotion_event_id>/execute")
def execute_promotion(promotion_event_id):
    authorize("BrokerAccountManager")
    data = v.body()
    actual_funding = v.req_int(data, "actual_funding_cents", 0)

    rec = db.get("promotions", promotion_event_id)

    if rec["state"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE")

    if clock.now() < clock.parse_instant(rec["window_end"]):
        raise ApiError("ERR_PROMO_NOT_ELAPSED")

    ceiling = calc.floor_div(rec["planned_funding_cents"] * calc.FUNDING_TOLERANCE_BPS, 10000)
    if actual_funding > ceiling:
        raise ApiError("ERR_PROMO_FUNDING_OVERRUN")

    rec["state"] = "EXECUTED"
    rec["actual_funding_cents"] = actual_funding
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/promotion-events/<promotion_event_id>/cancel")
def cancel_promotion(promotion_event_id):
    authorize("BrokerAccountManager")
    rec = db.get("promotions", promotion_event_id)

    if rec["state"] not in ("PLANNED", "COMMITTED"):
        raise ApiError("ERR_INVALID_STATE")

    rec["state"] = "CANCELLED"
    db.touch(rec)

    auth = db.find("authorizations", rec["authorization_id"])
    if auth is not None:
        domain.recompute_trade_spend(auth)
    return response.ok(serialize(rec))
