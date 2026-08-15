from datetime import timedelta

from flask import Blueprint

import clock
import db
import services
from auth import (
    authenticate,
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_INTAKE_COORDINATOR,
    ROLE_VETERINARIAN,
    ROLE_FARRIER,
)
from errors import (
    raise_err,
    ERR_HORSE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RELEASE_DATE_NOT_REACHED,
    ERR_CLEARANCE_EXAM_STALE,
    ERR_FEVER_WITHIN_72H,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_enum,
    as_int,
    as_number,
    body,
    get_path_or_404,
    minute_floor,
    opt_str,
    pagination_args,
    parse_dt,
    query_str,
    require_present,
    sorted_page,
)

bp = Blueprint("quarantine", __name__)

EVAL_TYPES = {"MEDICAL", "BEHAVIORAL", "FARRIERY"}
OUTCOMES = {"PASS", "FAIL", "CONDITIONAL"}
APPETITES = {"NORMAL", "REDUCED", "NONE"}
FEVER_THRESHOLD = 103.0

IC_VET_FARRIER = [ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN, ROLE_FARRIER]
READ_ROLES = [ROLE_SANCTUARY_DIRECTOR, ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN]


# --------------------------------------------------------------------------
# Intake evaluations
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/intake-evaluations")
def create_evaluation():
    authenticate(IC_VET_FARRIER)
    data = body()
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    horse_id = require_present(data, "horse_id")
    eval_type = as_enum(require_present(data, "evaluation_type"), "evaluation_type", EVAL_TYPES)
    scheduled_date = parse_dt(require_present(data, "scheduled_date"), "scheduled_date")
    rec = services.new_entity(
        {
            "horse_id": horse_id,
            "evaluation_type": eval_type,
            "scheduled_date": scheduled_date,
            "evaluation_date": None,
            "outcome": None,
            "findings": opt_str(data, "findings"),
            "status": "SCHEDULED",
            "completed_by_user_id": None,
        }
    )
    db.evaluations[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/intake-evaluations")
def list_evaluations():
    authenticate(READ_ROLES + [ROLE_FARRIER])
    limit, offset = pagination_args()
    filters = []
    for param in ("horse_id", "evaluation_type", "status", "outcome"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.evaluations.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/intake-evaluations/<eval_id>")
def get_evaluation(eval_id):
    authenticate(READ_ROLES + [ROLE_FARRIER])
    return ok_object(serialize(get_path_or_404(db.evaluations, eval_id)))


@bp.post("/rescue-ops/intake-evaluations/<eval_id>/complete")
def complete_evaluation(eval_id):
    user_id, _ = authenticate([ROLE_VETERINARIAN, ROLE_FARRIER, ROLE_INTAKE_COORDINATOR])
    rec = get_path_or_404(db.evaluations, eval_id)
    data = body()
    outcome = as_enum(require_present(data, "outcome"), "outcome", OUTCOMES)
    findings = opt_str(data, "findings")
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Evaluation is not SCHEDULED")
    rec["status"] = "COMPLETED"
    rec["outcome"] = outcome
    rec["evaluation_date"] = clock.now()
    rec["completed_by_user_id"] = user_id
    if findings is not None:
        rec["findings"] = findings
    services.touch(rec)
    if rec["evaluation_type"] == "MEDICAL" and outcome == "FAIL":
        services.extend_active_protocol(rec["horse_id"], 7)
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Quarantine protocols
# --------------------------------------------------------------------------
@bp.get("/rescue-ops/quarantine-protocols")
def list_protocols():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("horse_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.protocols.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/quarantine-protocols/<proto_id>")
def get_protocol(proto_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.protocols, proto_id)))


@bp.post("/rescue-ops/quarantine-protocols/<proto_id>/extend")
def extend_protocol(proto_id):
    authenticate([ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN])
    proto = get_path_or_404(db.protocols, proto_id)
    data = body()
    days = as_int(require_present(data, "days"), "days")
    if days < 1:
        raise_err(ERR_INVALID_REQUEST, "days must be a positive integer")
    require_present(data, "reason")
    if proto["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Protocol is not ACTIVE")
    proto["extension_days"] += days
    services.touch(proto)
    return ok_object(serialize(proto))


@bp.post("/rescue-ops/quarantine-protocols/<proto_id>/clear")
def clear_protocol(proto_id):
    authenticate([ROLE_VETERINARIAN])
    proto = get_path_or_404(db.protocols, proto_id)
    if proto["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Protocol is not ACTIVE")
    now = clock.now()
    # Fixed order: release date, then clearance exam, then fever lookback.
    earliest = proto["start_date"] + timedelta(days=proto["min_days"] + proto["extension_days"])
    if minute_floor(now) < minute_floor(earliest):
        raise_err(ERR_RELEASE_DATE_NOT_REACHED, "Minimum quarantine period has not elapsed")
    exam_ok = any(
        e["horse_id"] == proto["horse_id"]
        and e["status"] == "COMPLETED"
        and e["evaluation_type"] == "MEDICAL"
        and minute_floor(e["evaluation_date"]) >= minute_floor(now - timedelta(hours=48))
        for e in db.evaluations.values()
    )
    if not exam_ok:
        raise_err(ERR_CLEARANCE_EXAM_STALE, "No COMPLETED MEDICAL evaluation within 48 hours")
    fever = any(
        log["horse_id"] == proto["horse_id"]
        and log["temp_f"] >= FEVER_THRESHOLD
        and minute_floor(log["recorded_at"]) > minute_floor(now - timedelta(hours=72))
        for log in db.health_logs.values()
    )
    if fever:
        raise_err(ERR_FEVER_WITHIN_72H, "Fever reading recorded within trailing 72 hours")
    proto["status"] = "CLEARED"
    proto["cleared_at"] = now
    services.touch(proto)
    return ok_object(serialize(proto))


# --------------------------------------------------------------------------
# Daily health logs (append-only ledger)
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/daily-health-logs")
def create_health_log():
    authenticate([ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN])
    data = body()
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    horse_id = require_present(data, "horse_id")
    temp = as_number(require_present(data, "temp_f"), "temp_f")
    if temp < 95.0 or temp > 110.0:
        raise_err(ERR_INVALID_REQUEST, "temp_f must be in 95.0..110.0")
    appetite = as_enum(require_present(data, "appetite"), "appetite", APPETITES)
    rec = services.new_entity(
        {
            "horse_id": horse_id,
            "recorded_at": clock.now(),
            "temp_f": temp,
            "appetite": appetite,
            "notes": opt_str(data, "notes"),
        },
        ledger=True,
    )
    db.health_logs[rec["id"]] = rec
    if temp >= FEVER_THRESHOLD:
        services.extend_active_protocol(horse_id, 7)
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/daily-health-logs")
def list_health_logs():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    value = query_str("horse_id")
    if value is not None:
        filters.append(("horse_id", value))
    rows, total = sorted_page(db.health_logs.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/daily-health-logs/<log_id>")
def get_health_log(log_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.health_logs, log_id)))
