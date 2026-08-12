"""CertAudit endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_str, as_enum,
                  parse_date, clock_date, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_AUDIT_TOO_CLOSE, ERR_AUDIT_NOT_DUE)
from services import core
from datetime import timedelta

bp = Blueprint("cert_audits", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
SCHEDULERS = {"SugarhouseManager", "CertInspector"}
INSPECTOR = {"CertInspector"}


@bp.post("/sugarhouse/sugarbushes/<bid>/cert-audits")
def create_audit(bid):
    caller = authenticate()
    require_role(caller, SCHEDULERS)
    bush = db.sugarbushes.get(bid)
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {bid} not found")
    data = body_json()
    check_unknown_fields(data, {"audit_type", "scheduled_for"})
    require_fields(data, ["audit_type", "scheduled_for"])
    audit_type = as_enum(data["audit_type"], "audit_type", {"ORGANIC", "WOODS"})
    scheduled_for = as_str(data["scheduled_for"], "scheduled_for")
    try:
        sf = parse_date(scheduled_for)
    except Exception:
        raise_err(ERR_VALIDATION, "scheduled_for must be a YYYY-MM-DD date")

    # 14-day minimum spacing against ANY other audit on this bush
    for other in db.cert_audits.values():
        if other["sugarbush_id"] != bush["id"]:
            continue
        other_date = parse_date(other["scheduled_for"])
        if abs((sf - other_date).days) < core.AUDIT_SPACING_DAYS:
            raise_err(ERR_AUDIT_TOO_CLOSE,
                      "another audit on this bush is scheduled less than 14 days away")

    a = core.new_cert_audit(bush["id"], audit_type, scheduled_for)
    db.cert_audits[a["id"]] = a
    return success_object(core.ser_cert_audit(a), status=201)


@bp.get("/sugarhouse/sugarbushes/<bid>/cert-audits")
def list_audits(bid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    bush = db.sugarbushes.get(bid)
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {bid} not found")
    limit, offset = parse_pagination(request.args)
    audit_type = request.args.get("audit_type")
    rows = [a for a in db.cert_audits.values() if a["sugarbush_id"] == bush["id"]]
    if audit_type is not None:
        rows = [r for r in rows if r["audit_type"] == audit_type]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_cert_audit(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/cert-audits/<aid>/record-result")
def record_result(aid):
    caller = authenticate()
    require_role(caller, INSPECTOR)
    a = db.cert_audits.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, f"cert audit {aid} not found")
    data = body_json()
    check_unknown_fields(data, {"result"})
    require_fields(data, ["result"])
    result = as_enum(data["result"], "result", {"PASS", "FAIL"})
    if a["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, f"audit is {a['status']}, expected SCHEDULED")
    if clock_date() < parse_date(a["scheduled_for"]):
        raise_err(ERR_AUDIT_NOT_DUE, "audit is not due yet (clock < scheduled_for)")
    a["result"] = result
    a["status"] = "RECORDED"
    core.bump(a)
    if a["audit_type"] == "ORGANIC":
        bush = db.sugarbushes.get(a["sugarbush_id"])
        if bush:
            core.recompute_organic_certified(bush)
    return success_object(core.ser_cert_audit(a))
