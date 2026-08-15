"""FeeSchedule, AuditEvent, and logical-clock endpoints."""
from flask import Blueprint, request

from db import DB, CLOCK, new_id, parse_iso, to_iso_ms
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    get_fee_schedule,
    reevaluate_clock_driven,
    ser_audit_event,
    ser_fee_schedule,
    sorted_created,
    stamp,
)
from util import (
    as_bool,
    as_int,
    as_iso_dt,
    as_list,
    as_str,
    body,
    pagination_args,
    reject_unknown_fields,
    required,
)

bp = Blueprint("admin", __name__)

SCHEDULE_WRITE = ["RegistrarAdmin"]
SCHEDULE_READ = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer"]
AUDIT_READ = ["RegistrarAdmin", "RegistrarReviewer"]


@bp.post("/registrar/fee-schedules")
def create_fee_schedule():
    auth(SCHEDULE_WRITE)
    data = body()
    reject_unknown_fields(
        data,
        {
            "code",
            "official_base_cents",
            "unofficial_base_cents",
            "paper_surcharge_cents",
            "pickup_surcharge_cents",
            "rush_flat_cents",
            "rush_multiplier_bp",
            "volume_tiers",
            "effective_from",
            "effective_to",
            "active",
        },
    )
    code = as_str(required(data, "code"), "code")
    official_base = as_int(required(data, "official_base_cents"), "official_base_cents")
    unofficial_base = as_int(
        required(data, "unofficial_base_cents"), "unofficial_base_cents"
    )
    paper_surcharge = as_int(
        required(data, "paper_surcharge_cents"), "paper_surcharge_cents"
    )
    pickup_surcharge = as_int(
        required(data, "pickup_surcharge_cents"), "pickup_surcharge_cents"
    )
    rush_flat = as_int(required(data, "rush_flat_cents"), "rush_flat_cents")
    rush_mult_bp = as_int(required(data, "rush_multiplier_bp"), "rush_multiplier_bp")
    volume_tiers = as_list(data.get("volume_tiers", []), "volume_tiers")
    effective_from = as_iso_dt(required(data, "effective_from"), "effective_from")
    effective_to = data.get("effective_to")
    if effective_to is not None:
        effective_to = as_iso_dt(effective_to, "effective_to")
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "active must be a boolean")

    # Code unique.
    for s in DB["fee_schedules"].values():
        if s["code"] == code:
            raise ApiError("ERR_INVALID_REQUEST", 400, "code must be unique")

    # Window validity: from < to when to is non-null.
    ef_dt = parse_iso(effective_from)
    et_dt = parse_iso(effective_to) if effective_to else None
    if et_dt is not None and ef_dt >= et_dt:
        raise ApiError(
            "ERR_SCHEDULE_WINDOW_INVALID",
            422,
            "effective_from must be strictly before effective_to",
        )

    # Normalize tiers.
    tiers = []
    for t in volume_tiers:
        if not isinstance(t, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "volume_tiers entries must be objects"
            )
        mc = as_int(t.get("min_copies"), "volume_tiers.min_copies")
        dbp = as_int(t.get("discount_bp"), "volume_tiers.discount_bp")
        tiers.append({"min_copies": mc, "discount_bp": dbp})

    rec = {
        "id": new_id(),
        "code": code,
        "official_base_cents": official_base,
        "unofficial_base_cents": unofficial_base,
        "paper_surcharge_cents": paper_surcharge,
        "pickup_surcharge_cents": pickup_surcharge,
        "rush_flat_cents": rush_flat,
        "rush_multiplier_bp": rush_mult_bp,
        "volume_tiers": tiers,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "active": active,
    }
    stamp(rec)
    DB["fee_schedules"][rec["id"]] = rec

    # Only one schedule may be active at any instant: atomically deactivate
    # any other active schedule whose window overlaps this one.
    if active:
        for s in DB["fee_schedules"].values():
            if s["id"] == rec["id"] or not s["active"]:
                continue
            oef = parse_iso(s["effective_from"])
            oet = parse_iso(s["effective_to"]) if s["effective_to"] else None
            overlap = (oet is None or ef_dt < oet) and (et_dt is None or oef < et_dt)
            if overlap:
                s["active"] = False

    return ok(ser_fee_schedule(rec), status=201)


@bp.get("/registrar/fee-schedules")
def list_fee_schedules():
    auth(SCHEDULE_READ)
    limit, offset = pagination_args()
    items = list(DB["fee_schedules"].values())
    act = request.args.get("active")
    if act is not None:
        want = act.lower() == "true"
        items = [s for s in items if s["active"] == want]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_fee_schedule(s) for s in page], total, limit, offset)


@bp.get("/registrar/fee-schedules/<sid>")
def get_one_fee_schedule(sid):
    auth(SCHEDULE_READ)
    return ok(ser_fee_schedule(get_fee_schedule(sid)))


@bp.get("/registrar/audit-events")
def list_audit_events():
    auth(AUDIT_READ)
    limit, offset = pagination_args()
    items = list(DB["audit_events"].values())
    at = request.args.get("aggregate_type")
    if at is not None:
        items = [e for e in items if e["aggregate_type"] == at]
    aid = request.args.get("aggregate_id")
    if aid is not None:
        items = [e for e in items if e["aggregate_id"] == aid]
    act = request.args.get("action")
    if act is not None:
        items = [e for e in items if e["action"] == act]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_audit_event(e) for e in page], total, limit, offset)


@bp.post("/registrar/_clock/set_current_utc")
def set_clock():
    auth(["RegistrarAdmin"])
    data = body()
    reject_unknown_fields(data, {"to_iso8601"})
    to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    CLOCK["current_utc"] = to_iso_ms(parse_iso(to_iso8601))
    reevaluate_clock_driven()
    return ok({"current_utc": CLOCK["current_utc"]})
