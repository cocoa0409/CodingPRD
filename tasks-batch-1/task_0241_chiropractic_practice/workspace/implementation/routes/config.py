"""Configuration resources: providers, rooms, fee schedules, wellness plans, clock."""
from flask import Blueprint

import db
from errors import err
from middleware import authenticate, authorize, get_json_body, paginate
from models import new_record, touch, serialize, serialize_list
from lookups import leaf_or_404
from response import ok, created
import validators as V

bp = Blueprint("config", __name__)

READ_ALL = ["PracticeAdmin", "FrontDesk", "Provider", "BillingClerk"]
VISIT_TYPES = {"ADJUSTMENT", "EXAM", "RE_EXAM", "X_RAY", "THERAPY"}
ROOM_TYPES = {"ADJUSTMENT", "IMAGING"}


# ---- Providers ----
@bp.route("/providers", methods=["POST"])
def create_provider():
    _, role = authenticate()
    authorize(role, ["PracticeAdmin"])
    body = get_json_body()
    rec = new_record({
        "full_name": V.require_str(body, "full_name"),
        "npi": V.require_str(body, "npi"),
        "license_state": V.require_str(body, "license_state"),
        "status": "ACTIVE",
    })
    db.providers[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/providers", methods=["GET"])
def list_providers():
    _, role = authenticate()
    authorize(role, READ_ALL)
    from flask import request
    items = list(db.providers.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/providers/<provider_id>", methods=["GET"])
def get_provider(provider_id):
    _, role = authenticate()
    authorize(role, READ_ALL)
    rec = leaf_or_404(db.providers, provider_id)
    return ok(serialize(rec))


@bp.route("/providers/<provider_id>/suspend", methods=["POST"])
def suspend_provider(provider_id):
    _, role = authenticate()
    authorize(role, ["PracticeAdmin"])
    rec = leaf_or_404(db.providers, provider_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Provider is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok(serialize(rec))


# ---- Treatment rooms ----
@bp.route("/treatment-rooms", methods=["POST"])
def create_room():
    _, role = authenticate()
    authorize(role, ["PracticeAdmin"])
    body = get_json_body()
    buffer_min = V.optional_int(body, "turnover_buffer_minutes", 0)
    if buffer_min < 0:
        raise err("ERR_INVALID_REQUEST", "turnover_buffer_minutes must be >= 0")
    rec = new_record({
        "name": V.require_str(body, "name"),
        "room_type": V.require_enum(body, "room_type", ROOM_TYPES),
        "turnover_buffer_minutes": buffer_min,
        "status": "OPEN",
    })
    db.treatment_rooms[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/treatment-rooms", methods=["GET"])
def list_rooms():
    _, role = authenticate()
    authorize(role, READ_ALL)
    from flask import request
    items = list(db.treatment_rooms.values())
    status = request.args.get("status")
    room_type = request.args.get("room_type")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if room_type is not None:
        items = [r for r in items if r["room_type"] == room_type]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/treatment-rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    _, role = authenticate()
    authorize(role, READ_ALL)
    rec = leaf_or_404(db.treatment_rooms, room_id)
    return ok(serialize(rec))


@bp.route("/treatment-rooms/<room_id>/close", methods=["POST"])
def close_room(room_id):
    _, role = authenticate()
    authorize(role, ["PracticeAdmin"])
    rec = leaf_or_404(db.treatment_rooms, room_id)
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Room is not OPEN")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(serialize(rec))


# ---- Fee schedules ----
@bp.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    _, role = authenticate()
    authorize(role, ["PracticeAdmin"])
    body = get_json_body()
    visit_type = V.require_enum(body, "visit_type", VISIT_TYPES)
    cash_rate = V.require_int(body, "cash_rate_cents")
    billed = V.require_int(body, "billed_amount_cents")
    if cash_rate < 0 or billed < 0:
        raise err("ERR_INVALID_REQUEST", "Amounts must be >= 0")
    # Retire any prior ACTIVE schedule for this visit_type.
    for fs in db.fee_schedules.values():
        if fs["visit_type"] == visit_type and fs["status"] == "ACTIVE":
            fs["status"] = "RETIRED"
            touch(fs)
    rec = new_record({
        "visit_type": visit_type,
        "cash_rate_cents": cash_rate,
        "billed_amount_cents": billed,
        "status": "ACTIVE",
    })
    db.fee_schedules[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/fee-schedules", methods=["GET"])
def list_fee_schedules():
    _, role = authenticate()
    authorize(role, READ_ALL)
    from flask import request
    items = list(db.fee_schedules.values())
    visit_type = request.args.get("visit_type")
    status = request.args.get("status")
    if visit_type is not None:
        items = [f for f in items if f["visit_type"] == visit_type]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


# ---- Wellness plans ----
@bp.route("/wellness-plans", methods=["POST"])
def create_wellness_plan():
    _, role = authenticate()
    authorize(role, ["PracticeAdmin"])
    body = get_json_body()
    monthly = V.require_int(body, "monthly_fee_cents")
    included = V.require_int(body, "included_adjustments_per_month")
    overage = V.require_number(body, "overage_discount_pct")
    if monthly < 0 or included < 0:
        raise err("ERR_INVALID_REQUEST", "Amounts must be >= 0")
    if not (0.0 <= overage <= 1.0):
        raise err("ERR_INVALID_REQUEST", "overage_discount_pct must be between 0.0 and 1.0")
    rec = new_record({
        "name": V.require_str(body, "name"),
        "monthly_fee_cents": monthly,
        "included_adjustments_per_month": included,
        "overage_discount_pct": overage,
        "status": "ACTIVE",
    })
    db.wellness_plans[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/wellness-plans", methods=["GET"])
def list_wellness_plans():
    _, role = authenticate()
    authorize(role, READ_ALL)
    from flask import request
    items = list(db.wellness_plans.values())
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


# ---- Practice clock ----
@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, ["PracticeAdmin"])
    body = get_json_body()
    current_utc = V.require_str(body, "current_utc")
    db.practice_clock["current_utc"] = current_utc
    if db.practice_clock["created_at"] is None:
        db.practice_clock["created_at"] = db.now_iso()
    return ok(serialize(db.practice_clock))


@bp.route("/_clock", methods=["GET"])
def get_clock():
    _, role = authenticate()
    authorize(role, READ_ALL)
    return ok(serialize(db.practice_clock))
