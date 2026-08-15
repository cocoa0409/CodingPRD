"""SecurityRoleAssignment, AuditEntry, and the logical clock."""
from flask import Blueprint, request

from engine import sweep
from errors import ApiError
from serialize import ser_audit, ser_grant
from services import SOD_PAIRS, audit, bump, get_or_404
from store import db
from util import (
    ALL_ROLES, auth, body, clock_date, fmt_clock, inv, list_page, new_entity,
    ok, parse_date_val, parse_instant, req_field,
)

bp = Blueprint("admin", __name__)

ROLE_CODES = {"HRIS_ANALYST", "DATA_STEWARD", "CHANGE_APPROVER",
              "INTEGRATION_OPERATOR", "SECURITY_ADMIN"}


@bp.post("/hris/security-role-assignments")
def create_grant():
    auth(["SecurityAdmin"])
    b = body()
    user_id = req_field(b, "user_id")
    role_code = req_field(b, "role_code")
    if not isinstance(user_id, str) or not user_id:
        raise inv("Invalid user_id")
    if role_code not in ROLE_CODES:
        raise inv("Invalid role_code")
    scope = b.get("scope_department", "GLOBAL")
    if scope is None:
        scope = "GLOBAL"
    if not isinstance(scope, str):
        raise inv("Invalid scope_department")
    valid_from = parse_date_val(req_field(b, "valid_from"), "valid_from")
    valid_until = parse_date_val(req_field(b, "valid_until"), "valid_until")
    if valid_until < valid_from:
        raise inv("valid_until earlier than valid_from")
    g = new_entity(db.grants)
    g.update({"user_id": user_id, "role_code": role_code, "scope_department": scope,
              "valid_from": valid_from, "valid_until": valid_until,
              "status": "REQUESTED", "approved_by": None})
    db.grants[g["id"]] = g
    return ok(ser_grant(g), code=201)


@bp.get("/hris/security-role-assignments")
def list_grants():
    auth(ALL_ROLES)
    items = list(db.grants.values())
    for key in ("user_id", "role_code", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [g for g in items if g[key] == v]
    return list_page(items, ser_grant)


@bp.post("/hris/security-role-assignments/<grantId>/approve")
def approve_grant(grantId):
    caller = auth(["SecurityAdmin"])
    g = get_or_404(db.grants, grantId, "ERR_GRANT_NOT_FOUND")
    if g["status"] != "REQUESTED":
        raise ApiError("ERR_GRANT_INVALID_STATE", 409, "Approve requires REQUESTED")
    # authority tier: self-approval -> segregation of duties
    if caller == g["user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 403,
                       "Approver may not be the grant's user_id")
    for other in db.grants.values():
        if other["id"] == g["id"] or other["user_id"] != g["user_id"]:
            continue
        if other["status"] not in ("APPROVED", "PROVISIONED"):
            continue
        pair = (g["role_code"], other["role_code"])
        if pair in SOD_PAIRS or (pair[1], pair[0]) in SOD_PAIRS:
            raise ApiError("ERR_SOD_CONFLICT", 409,
                           "Grant would give one user both roles of a conflicting pair")
    for other in db.grants.values():
        if other["id"] == g["id"] or other["user_id"] != g["user_id"]:
            continue
        if other["role_code"] != g["role_code"]:
            continue
        if other["status"] not in ("APPROVED", "PROVISIONED"):
            continue
        # closed-interval overlap; touching endpoints count
        if other["valid_from"] <= g["valid_until"] and g["valid_from"] <= other["valid_until"]:
            raise ApiError("ERR_GRANT_WINDOW_OVERLAP", 409,
                           "Overlapping grant window for the same user and role")
    if g["valid_until"] < g["valid_from"]:
        raise inv("valid_until earlier than valid_from")
    g["approved_by"] = caller
    g["status"] = "APPROVED"
    cdate = clock_date()
    if cdate > g["valid_until"]:
        g["status"] = "EXPIRED"
    elif cdate >= g["valid_from"]:
        g["status"] = "PROVISIONED"
    bump(g)
    audit(caller, "GRANT_APPROVE")
    return ok(ser_grant(g))


@bp.post("/hris/security-role-assignments/<grantId>/revoke")
def revoke_grant(grantId):
    caller = auth(["SecurityAdmin"])
    g = get_or_404(db.grants, grantId, "ERR_GRANT_NOT_FOUND")
    if g["status"] not in ("APPROVED", "PROVISIONED"):
        raise ApiError("ERR_GRANT_INVALID_STATE", 409,
                       "Revoke requires APPROVED or PROVISIONED")
    g["status"] = "REVOKED"
    bump(g)
    audit(caller, "GRANT_REVOKE")
    return ok(ser_grant(g))


# ---------------------------------------------------------------- audit log
@bp.get("/hris/audit-entries")
def list_audit():
    auth(ALL_ROLES)
    items = list(db.audit_entries.values())
    for key in ("worker_id", "field_id", "change_request_id", "batch_id"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a[key] == v]
    return list_page(items, ser_audit)


@bp.get("/hris/audit-entries/<auditEntryId>")
def get_audit(auditEntryId):
    auth(ALL_ROLES)
    a = get_or_404(db.audit_entries, auditEntryId, "ERR_AUDIT_ENTRY_NOT_FOUND")
    return ok(ser_audit(a))


# --------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(["SecurityAdmin"])
    b = body()
    to = parse_instant(req_field(b, "to_iso8601"))
    db.clock = to
    sweep()
    return ok({"current_utc": fmt_clock(db.clock)})
