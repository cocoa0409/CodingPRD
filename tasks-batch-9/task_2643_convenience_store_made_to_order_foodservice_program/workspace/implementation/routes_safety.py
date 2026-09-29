"""Food safety: probe readings, impairment sweeps and corrective actions."""

from flask import Blueprint

from apihttp import authenticate, created, get_body, ok, paginate, query_flag, query_str
from calc import (
    find_corrective_action,
    find_holding_unit,
    find_temperature_log,
    impairment_sweep,
)
from core import (
    ABSOLUTE_MAX_READING_F,
    ABSOLUTE_MIN_READING_F,
    base_record,
    db,
    sort_created,
    touch,
)
from errors import ApiError
from serialize import corrective_action_out, temperature_log_out

bp = Blueprint("safety", __name__)


@bp.post("/holding-units/<unit_id>/temperature-logs")
def record_temperature_log(unit_id):
    user_id, _role = authenticate(("KitchenAssociate", "ShiftLead", "FoodSafetyLead"))
    body = get_body()
    reading_f = body.number("reading_f")
    unit = find_holding_unit(unit_id)
    if reading_f < ABSOLUTE_MIN_READING_F or reading_f > ABSOLUTE_MAX_READING_F:
        raise ApiError("ERR_TEMP_READING_OUT_OF_SENSOR_RANGE")
    in_range = unit["min_temp_f"] <= reading_f <= unit["max_temp_f"]
    rec = base_record(versioned=False)
    rec.update({
        "holding_unit_id": unit["id"],
        "reading_f": reading_f,
        "in_range": bool(in_range),
        "logged_by_user_id": user_id,
        "recorded_at": db.clock,
    })
    db.temperature_logs[rec["id"]] = rec
    unit["last_temp_log_at"] = rec["recorded_at"]
    escalated = False
    if not in_range:
        if unit["status"] == "OPERATIONAL":
            unit["status"] = "IMPAIRED"
            unit["consecutive_out_of_range_count"] += 1
            escalated = True
        elif unit["status"] == "IMPAIRED":
            unit["status"] = "LOCKED_OUT"
            unit["consecutive_out_of_range_count"] += 1
            escalated = True
    touch(unit)
    if escalated:
        impairment_sweep(unit, db.stores[unit["store_id"]])
    return created(temperature_log_out(rec))


@bp.get("/holding-units/<unit_id>/temperature-logs")
def list_temperature_logs(unit_id):
    authenticate(("ChainAdmin", "StoreManager", "KitchenAssociate", "ShiftLead", "FoodSafetyLead"))
    unit = find_holding_unit(unit_id)
    logs = [t for t in db.temperature_logs.values() if t["holding_unit_id"] == unit["id"]]
    in_range = query_flag("in_range")
    if in_range is not None:
        logs = [t for t in logs if t["in_range"] is in_range]
    newest_first = list(reversed(sort_created(logs)))
    return paginate(newest_first, temperature_log_out)


@bp.post("/corrective-actions")
def open_corrective_action():
    user_id, _role = authenticate(("ShiftLead", "FoodSafetyLead", "KitchenAssociate"))
    body = get_body()
    temperature_log_id = body.string("temperature_log_id")
    action_taken = body.string("action_taken", min_len=1)
    log = find_temperature_log(temperature_log_id)
    rec = base_record()
    rec.update({
        "temperature_log_id": log["id"],
        "action_taken": action_taken,
        "status": "OPEN",
        "opened_by_user_id": user_id,
        "verified_by_user_id": None,
        "verified_at": None,
    })
    db.corrective_actions[rec["id"]] = rec
    return created(corrective_action_out(rec))


@bp.post("/corrective-actions/<action_id>/verify")
def verify_corrective_action(action_id):
    user_id, role = authenticate(("ShiftLead", "FoodSafetyLead"))
    action = find_corrective_action(action_id)
    log = db.temperature_logs[action["temperature_log_id"]]
    unit = db.holding_units[log["holding_unit_id"]]
    if user_id == log["logged_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if unit["status"] == "LOCKED_OUT" and role != "FoodSafetyLead":
        raise ApiError("ERR_LOCKOUT_REQUIRES_SAFETY_LEAD")
    if action["status"] != "OPEN":
        raise ApiError("ERR_ACTION_ALREADY_VERIFIED")
    if unit["status"] not in ("IMPAIRED", "LOCKED_OUT"):
        raise ApiError("ERR_UNIT_NOT_IMPAIRED")
    action["status"] = "VERIFIED"
    action["verified_by_user_id"] = user_id
    action["verified_at"] = db.clock
    touch(action)
    unit["status"] = "OPERATIONAL"
    unit["consecutive_out_of_range_count"] = 0
    touch(unit)
    return ok(corrective_action_out(action))


@bp.get("/corrective-actions")
def list_corrective_actions():
    authenticate(("ChainAdmin", "StoreManager", "ShiftLead", "FoodSafetyLead"))
    actions = list(db.corrective_actions.values())
    temperature_log_id = query_str("temperature_log_id")
    status = query_str("status")
    if temperature_log_id is not None:
        actions = [a for a in actions if a["temperature_log_id"] == temperature_log_id]
    if status is not None:
        actions = [a for a in actions if a["status"] == status]
    return paginate(sort_created(actions), corrective_action_out)


@bp.get("/corrective-actions/<action_id>")
def read_corrective_action(action_id):
    authenticate(("ChainAdmin", "StoreManager", "ShiftLead", "FoodSafetyLead"))
    return ok(corrective_action_out(find_corrective_action(action_id)))
