"""DataField dictionary and DataQualityRule endpoints."""
from flask import Blueprint, request

from errors import ApiError
from serialize import ser_data_field, ser_dq_rule
from services import CHANNELS, GOVERNABLE_KEYS, bump, get_or_404
from store import db
from util import ALL_ROLES, auth, body, inv, list_page, new_entity, ok, req_field

bp = Blueprint("dict", __name__)

SENSITIVITIES = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"}
HISTORY_POLICIES = {"CORRECTABLE", "APPEND_ONLY"}
RULE_TYPES = {"RANGE", "REQUIRED", "REGEX"}
SEVERITIES = {"WARNING", "CRITICAL"}


@bp.post("/hris/data-fields")
def create_data_field():
    auth(["DataSteward"])
    b = body()
    field_key = req_field(b, "field_key")
    display_name = req_field(b, "display_name")
    sensitivity = req_field(b, "sensitivity")
    history_policy = req_field(b, "history_policy")
    owner_team = req_field(b, "owner_team")
    if not isinstance(field_key, str) or field_key not in GOVERNABLE_KEYS:
        raise inv("field_key must name a governable attribute")
    if any(f["field_key"] == field_key for f in db.data_fields.values()):
        raise inv("field_key must be unique across the dictionary")
    if sensitivity not in SENSITIVITIES:
        raise inv("Invalid sensitivity")
    if history_policy not in HISTORY_POLICIES:
        raise inv("Invalid history_policy")
    channels = b.get("downstream_channels", [])
    if channels is None:
        channels = []
    if not isinstance(channels, list) or any(c not in CHANNELS for c in channels):
        raise inv("downstream_channels must be a subset of [PAYROLL, BENEFITS, IDENTITY]")
    deduped = []
    for c in channels:
        if c not in deduped:
            deduped.append(c)
    f = new_entity(db.data_fields)
    f.update({"field_key": field_key, "display_name": display_name,
              "sensitivity": sensitivity, "history_policy": history_policy,
              "downstream_channels": deduped, "owner_team": owner_team,
              "status": "DRAFT"})
    db.data_fields[f["id"]] = f
    return ok(ser_data_field(f), code=201)


@bp.get("/hris/data-fields")
def list_data_fields():
    auth(ALL_ROLES)
    items = list(db.data_fields.values())
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    sensitivity = request.args.get("sensitivity")
    if sensitivity is not None:
        items = [f for f in items if f["sensitivity"] == sensitivity]
    return list_page(items, ser_data_field)


@bp.get("/hris/data-fields/<dataFieldId>")
def get_data_field(dataFieldId):
    auth(ALL_ROLES)
    f = get_or_404(db.data_fields, dataFieldId, "ERR_DATA_FIELD_NOT_FOUND")
    return ok(ser_data_field(f))


@bp.post("/hris/data-fields/<dataFieldId>/activate")
def activate_data_field(dataFieldId):
    auth(["DataSteward"])
    f = get_or_404(db.data_fields, dataFieldId, "ERR_DATA_FIELD_NOT_FOUND")
    if f["status"] != "DRAFT":
        raise ApiError("ERR_FIELD_NOT_ACTIVE", 409, "Activate requires DRAFT")
    f["status"] = "ACTIVE"
    bump(f)
    return ok(ser_data_field(f))


@bp.post("/hris/data-fields/<dataFieldId>/deprecate")
def deprecate_data_field(dataFieldId):
    auth(["DataSteward"])
    f = get_or_404(db.data_fields, dataFieldId, "ERR_DATA_FIELD_NOT_FOUND")
    if f["status"] != "ACTIVE":
        raise ApiError("ERR_FIELD_NOT_ACTIVE", 409, "Deprecate requires ACTIVE")
    f["status"] = "DEPRECATED"
    bump(f)
    return ok(ser_data_field(f))


@bp.get("/hris/data-fields/<dataFieldId>/data-quality-rules")
def list_field_rules(dataFieldId):
    auth(ALL_ROLES)
    get_or_404(db.data_fields, dataFieldId, "ERR_DATA_FIELD_NOT_FOUND")
    items = [r for r in db.dq_rules.values() if r["target_field_id"] == dataFieldId]
    return list_page(items, ser_dq_rule)


@bp.post("/hris/data-quality-rules")
def create_dq_rule():
    auth(["DataSteward"])
    b = body()
    target_field_id = req_field(b, "target_field_id")
    rule_type = req_field(b, "rule_type")
    severity = req_field(b, "severity")
    if not isinstance(target_field_id, str):
        raise inv("Invalid target_field_id")
    field = get_or_404(db.data_fields, target_field_id, "ERR_DATA_FIELD_NOT_FOUND")
    if rule_type not in RULE_TYPES:
        raise inv("Invalid rule_type")
    if severity not in SEVERITIES:
        raise inv("Invalid severity")
    param_min = b.get("param_min")
    param_max = b.get("param_max")
    param_pattern = b.get("param_pattern")
    from util import parse_int_val
    if param_min is not None:
        param_min = parse_int_val(param_min, "param_min")
    if param_max is not None:
        param_max = parse_int_val(param_max, "param_max")
    if rule_type == "REGEX" and not param_pattern:
        raise inv("REGEX rule requires param_pattern")
    if rule_type == "RANGE" and param_min is None and param_max is None:
        raise inv("RANGE rule requires param_min and/or param_max")
    if param_pattern is not None and not isinstance(param_pattern, str):
        raise inv("param_pattern must be a string")
    if field["status"] != "ACTIVE":
        raise ApiError("ERR_FIELD_NOT_ACTIVE", 409,
                       "DQ rules are authored against an ACTIVE field")
    r = new_entity(db.dq_rules)
    r.update({"target_field_id": target_field_id, "rule_type": rule_type,
              "severity": severity, "param_min": param_min, "param_max": param_max,
              "param_pattern": param_pattern, "status": "ACTIVE"})
    db.dq_rules[r["id"]] = r
    return ok(ser_dq_rule(r), code=201)


@bp.patch("/hris/data-quality-rules/<ruleId>")
def patch_dq_rule(ruleId):
    auth(["DataSteward"])
    r = get_or_404(db.dq_rules, ruleId, "ERR_DQ_RULE_NOT_FOUND")
    b = body()
    if "status" in b and b["status"] is not None:
        if b["status"] not in ("ACTIVE", "DISABLED"):
            raise inv("status must be ACTIVE or DISABLED")
        r["status"] = b["status"]
    from util import parse_int_val
    if "param_min" in b:
        r["param_min"] = None if b["param_min"] is None else parse_int_val(b["param_min"], "param_min")
    if "param_max" in b:
        r["param_max"] = None if b["param_max"] is None else parse_int_val(b["param_max"], "param_max")
    if "param_pattern" in b:
        if b["param_pattern"] is not None and not isinstance(b["param_pattern"], str):
            raise inv("param_pattern must be a string")
        r["param_pattern"] = b["param_pattern"]
    bump(r)
    return ok(ser_dq_rule(r))
