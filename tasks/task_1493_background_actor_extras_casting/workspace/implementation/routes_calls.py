"""CastingCall endpoints (publish/lock/start-shooting/wrap/cancel)."""
from flask import Blueprint, request

from db import STORE, logical_now, parse_date, parse_dt
from domain import _base, call_bookings, ser_call, touch
from errors import (
    ApiError,
    ERR_CALL_INVALID_STATE,
    ERR_CASTING_CALL_NOT_FOUND,
    ERR_COMPLIANCE_INDEX_TOO_LOW,
    ERR_PRODUCTION_NOT_ACTIVE,
    ERR_SHOOT_DATE_MISMATCH,
    ERR_UNION_RATIO_SHORTFALL,
    ERR_VALIDATION,
)
from middleware import ALL_ROLES, auth, body, opt_str, req_int, req_str
from response import ok_list, ok_obj, paginate
from routes_productions import get_production
from services import NONCOMPLIANT_WRAP_PENALTY, PUBLISH_GATE_MINIMUM

bp = Blueprint("casting_calls", __name__)


def get_call(cid):
    c = STORE.casting_calls.get(cid)
    if c is None:
        raise ApiError(ERR_CASTING_CALL_NOT_FOUND, 404, "Casting call not found")
    return c


@bp.post("/central-casting/casting-calls")
def create_call():
    auth(["CastingDirector"])
    data = body()
    production_id = req_str(data, "production_id")
    production = get_production(production_id)
    shoot_date_raw = req_str(data, "shoot_date")
    shoot_date = parse_date(shoot_date_raw)
    if shoot_date is None:
        raise ApiError(ERR_VALIDATION, 400, "shoot_date must be an ISO date YYYY-MM-DD")
    general_call_time_raw = req_str(data, "general_call_time")
    general_call_time = parse_dt(general_call_time_raw)
    if general_call_time is None:
        raise ApiError(ERR_VALIDATION, 400, "general_call_time must be an ISO 8601 datetime")
    duration = req_int(data, "scheduled_duration_minutes", minimum=1)
    location = req_str(data, "location")
    union_slots = req_int(data, "union_slots", minimum=0)
    nonunion_slots = req_int(data, "nonunion_slots", minimum=0)
    union_rate = req_int(data, "union_rate_cents", minimum=1)
    nonunion_rate = req_int(data, "nonunion_rate_cents", minimum=1)
    wardrobe_notes = opt_str(data, "wardrobe_notes")
    if production["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production must be ACTIVE to create calls")
    c = _base()
    c.update(
        {
            "production_id": production_id,
            "shoot_date": shoot_date.isoformat(),
            "general_call_time": general_call_time,
            "scheduled_duration_minutes": duration,
            "location": location,
            "union_slots": union_slots,
            "nonunion_slots": nonunion_slots,
            "union_rate_cents": union_rate,
            "nonunion_rate_cents": nonunion_rate,
            "wardrobe_notes": wardrobe_notes,
            "status": "DRAFT",
            "approved_waiver_reduction": 0,
            "projected_compliant": None,
            "actual_union_checkins": 0,
            "actual_compliant": None,
        }
    )
    STORE.casting_calls[c["id"]] = c
    return ok_obj(ser_call(c), code=201)


@bp.get("/central-casting/casting-calls")
def list_calls():
    auth(ALL_ROLES)
    rows = sorted(STORE.casting_calls.values(), key=lambda c: c["_seq"])
    production_id = request.args.get("production_id")
    status = request.args.get("status")
    shoot_date = request.args.get("shoot_date")
    if production_id is not None:
        rows = [c for c in rows if c["production_id"] == production_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if shoot_date is not None:
        rows = [c for c in rows if c["shoot_date"] == shoot_date]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_call(c) for c in page], total, limit, offset)


@bp.get("/central-casting/casting-calls/<cid>")
def get_call_route(cid):
    auth(ALL_ROLES)
    return ok_obj(ser_call(get_call(cid)))


@bp.post("/central-casting/casting-calls/<cid>/publish")
def publish_call(cid):
    auth(["CastingDirector"])
    c = get_call(cid)
    # Publish gate order (PRD section 3.3): combined headcount, production
    # ACTIVE, call DRAFT, then compliance index >= 30 (exactly 30 passes).
    if c["union_slots"] + c["nonunion_slots"] <= 0:
        raise ApiError(ERR_VALIDATION, 400, "union_slots + nonunion_slots must be > 0")
    production = get_production(c["production_id"])
    if production["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production must be ACTIVE to publish")
    if c["status"] != "DRAFT":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Only a DRAFT call can be published")
    if production["compliance_index"] < PUBLISH_GATE_MINIMUM:
        raise ApiError(
            ERR_COMPLIANCE_INDEX_TOO_LOW,
            409,
            "Production compliance_index is below the publish gate",
        )
    c["status"] = "PUBLISHED"
    touch(c)
    return ok_obj(ser_call(c))


@bp.post("/central-casting/casting-calls/<cid>/lock")
def lock_call(cid):
    auth(["CastingDirector"])
    c = get_call(cid)
    if c["status"] != "PUBLISHED":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Only a PUBLISHED call can be locked")
    projected = sum(
        1
        for b in call_bookings(cid)
        if b["status"] in ("OFFERED", "CONFIRMED", "CHECKED_IN", "WRAPPED")
        and b["slot_type"] == "UNION"
    )
    if projected < (c["union_slots"] - c["approved_waiver_reduction"]):
        raise ApiError(
            ERR_UNION_RATIO_SHORTFALL,
            422,
            "projected_union_count is below required_union_slots",
        )
    c["status"] = "LOCKED"
    # Frozen verdict: evaluated and stored at lock; later booking changes do not alter it.
    c["projected_compliant"] = True
    touch(c)
    return ok_obj(ser_call(c))


@bp.post("/central-casting/casting-calls/<cid>/start-shooting")
def start_shooting(cid):
    auth(["CastingAssociate"])
    c = get_call(cid)
    if c["status"] != "LOCKED":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Only a LOCKED call can start shooting")
    if logical_now().date().isoformat() != c["shoot_date"]:
        raise ApiError(
            ERR_SHOOT_DATE_MISMATCH,
            409,
            "Logical clock date must equal the call's shoot_date",
        )
    c["status"] = "SHOOTING"
    touch(c)
    return ok_obj(ser_call(c))


@bp.post("/central-casting/casting-calls/<cid>/wrap")
def wrap_call(cid):
    auth(["CastingAssociate"])
    c = get_call(cid)
    if c["status"] != "SHOOTING":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Only a SHOOTING call can wrap")
    bookings = call_bookings(cid)
    if any(
        b["status"] not in ("WRAPPED", "DECLINED", "EXPIRED", "CANCELLED", "NO_SHOW")
        for b in bookings
    ):
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "All bookings must be terminal before wrap")
    cases = [rc for rc in STORE.replacement_cases.values() if rc["casting_call_id"] == cid]
    if any(rc["status"] not in ("FILLED", "EXPIRED") for rc in cases):
        raise ApiError(
            ERR_CALL_INVALID_STATE,
            409,
            "All replacement cases must be FILLED or EXPIRED before wrap",
        )
    # Freeze actuals: union bookings in CHECKED_IN | WRAPPED at this instant.
    actual = sum(
        1
        for b in bookings
        if b["status"] in ("CHECKED_IN", "WRAPPED") and b["slot_type"] == "UNION"
    )
    c["actual_union_checkins"] = actual
    c["actual_compliant"] = actual >= (c["union_slots"] - c["approved_waiver_reduction"])
    if not c["actual_compliant"]:
        production = get_production(c["production_id"])
        production["compliance_index"] = max(
            0, production["compliance_index"] - NONCOMPLIANT_WRAP_PENALTY
        )
        touch(production)
    for s in STORE.standby_entries.values():
        if s["casting_call_id"] == cid and s["status"] == "ACTIVE":
            s["status"] = "EXPIRED"
            touch(s)
    c["status"] = "WRAPPED"
    touch(c)
    return ok_obj(ser_call(c))


@bp.post("/central-casting/casting-calls/<cid>/cancel")
def cancel_call(cid):
    auth(["CastingDirector"])
    body()  # optional reason accepted, not persisted
    c = get_call(cid)
    if c["status"] not in ("DRAFT", "PUBLISHED", "LOCKED"):
        raise ApiError(
            ERR_CALL_INVALID_STATE,
            409,
            "Only DRAFT, PUBLISHED, or LOCKED calls can be cancelled",
        )
    for b in call_bookings(cid):
        if b["status"] in ("OFFERED", "CONFIRMED"):
            b["status"] = "CANCELLED"
            touch(b)
    for s in STORE.standby_entries.values():
        if s["casting_call_id"] == cid and s["status"] == "ACTIVE":
            s["status"] = "EXPIRED"
            touch(s)
    for w in STORE.ratio_waivers.values():
        if w["casting_call_id"] == cid and w["status"] == "REQUESTED":
            w["status"] = "REVOKED"
            touch(w)
    c["status"] = "CANCELLED"
    touch(c)
    return ok_obj(ser_call(c))
