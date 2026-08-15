"""Restriction rules and effectiveness windows (PRD §3.3)."""
from flask import Blueprint, request

import audit
import db
import services as svc
from errors import raise_err
from middleware import ALL_ROLES, body, paged, pagination, require_enum, require_roles
from response import ok_list, ok_object
from util import is_int, parse_dt, public

bp = Blueprint("restrictions", __name__)

RULE_TYPES = ("PROHIBITED", "MAX_POSITION_UNITS")
SIDES = ("BUY", "SELL", "BOTH")


def _same_key(a, b):
    return (a["account_id"] == b["account_id"] and a["security_id"] == b["security_id"]
            and a["rule_type"] == b["rule_type"] and a["side"] == b["side"])


@bp.post("/trading/restrictions")
@require_roles("ComplianceOfficer")
def create_restriction():
    b = body()
    rule_type = require_enum(b, "rule_type", RULE_TYPES)
    side = require_enum(b, "side", SIDES)
    ef_raw = b.get("effective_from")
    et_raw = b.get("effective_to")
    ef = parse_dt(ef_raw)
    et = parse_dt(et_raw)
    if ef is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'effective_from' must be an ISO 8601 datetime")
    if et is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'effective_to' must be an ISO 8601 datetime")
    if et < ef:
        raise_err("ERR_INVALID_REQUEST", "effective_to must be no earlier than effective_from")
    threshold = b.get("threshold_units")
    if rule_type == "MAX_POSITION_UNITS":
        if not is_int(threshold) or threshold <= 0:
            raise_err("ERR_INVALID_REQUEST",
                      "threshold_units is required and must be a positive integer for MAX_POSITION_UNITS")
    elif threshold is not None:
        raise_err("ERR_INVALID_REQUEST", "threshold_units is forbidden for PROHIBITED")
    account_id = b.get("account_id")
    security_id = b.get("security_id")
    if account_id is not None:
        if not isinstance(account_id, str):
            raise_err("ERR_INVALID_REQUEST", "Field 'account_id' must be a string")
        svc.fetch("accounts", account_id, "ERR_ACCOUNT_NOT_FOUND")
    if security_id is not None:
        if not isinstance(security_id, str):
            raise_err("ERR_INVALID_REQUEST", "Field 'security_id' must be a string")
        svc.fetch("securities", security_id, "ERR_SECURITY_NOT_FOUND")
    rec = svc.new_record()
    rec.update({"account_id": account_id, "security_id": security_id,
                "rule_type": rule_type, "side": side, "threshold_units": threshold,
                "effective_from": ef_raw, "effective_to": et_raw, "status": "DRAFT",
                "_ef": ef, "_et": et})
    db.store["restrictions"][rec["id"]] = rec
    audit.record_request("Restriction", rec["id"], "RESTRICTION_CREATED",
                         f"rule_type: {rule_type}; side: {side}; window: [{ef_raw}, {et_raw}]")
    return ok_object(public(rec), 201)


@bp.get("/trading/restrictions/<restrictionId>")
@require_roles(*ALL_ROLES)
def get_restriction(restrictionId):
    return ok_object(public(svc.fetch("restrictions", restrictionId, "ERR_RESTRICTION_NOT_FOUND")))


@bp.get("/trading/restrictions")
@require_roles(*ALL_ROLES)
def list_restrictions():
    limit, offset = pagination()
    items = sorted(db.store["restrictions"].values(), key=lambda r: r["_seq"])
    account_id = request.args.get("account_id")
    security_id = request.args.get("security_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    if security_id is not None:
        items = [r for r in items if r["security_id"] == security_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paged(items, limit, offset)
    return ok_list([public(r) for r in page], total, limit, offset)


@bp.post("/trading/restrictions/<restrictionId>/activate")
@require_roles("ComplianceOfficer")
def activate_restriction(restrictionId):
    rec = svc.fetch("restrictions", restrictionId, "ERR_RESTRICTION_NOT_FOUND")
    if rec["status"] not in ("DRAFT", "SUSPENDED"):
        raise_err("ERR_INVALID_STATE", f"Cannot activate a restriction in {rec['status']}")
    for other in db.store["restrictions"].values():
        if other["id"] == rec["id"] or other["status"] != "ACTIVE":
            continue
        if not _same_key(rec, other):
            continue
        # closed-window intersection: shared endpoints DO intersect
        if rec["_ef"] <= other["_et"] and other["_ef"] <= rec["_et"]:
            raise_err("ERR_RESTRICTION_WINDOW_OVERLAP",
                      "Window overlaps an ACTIVE restriction with the same key")
    frm = rec["status"]
    rec["status"] = "ACTIVE"
    svc.touch(rec)
    audit.record_request("Restriction", rec["id"], "RESTRICTION_ACTIVATED",
                         f"status: {frm} -> ACTIVE")
    return ok_object(public(rec))


@bp.post("/trading/restrictions/<restrictionId>/suspend")
@require_roles("ComplianceOfficer")
def suspend_restriction(restrictionId):
    rec = svc.fetch("restrictions", restrictionId, "ERR_RESTRICTION_NOT_FOUND")
    if rec["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", f"Cannot suspend a restriction in {rec['status']}")
    rec["status"] = "SUSPENDED"
    svc.touch(rec)
    audit.record_request("Restriction", rec["id"], "RESTRICTION_SUSPENDED",
                         "status: ACTIVE -> SUSPENDED")
    return ok_object(public(rec))


@bp.post("/trading/restrictions/<restrictionId>/retire")
@require_roles("ComplianceOfficer")
def retire_restriction(restrictionId):
    rec = svc.fetch("restrictions", restrictionId, "ERR_RESTRICTION_NOT_FOUND")
    if rec["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise_err("ERR_INVALID_STATE", f"Cannot retire a restriction in {rec['status']}")
    frm = rec["status"]
    rec["status"] = "RETIRED"
    svc.touch(rec)
    audit.record_request("Restriction", rec["id"], "RESTRICTION_RETIRED",
                         f"status: {frm} -> RETIRED")
    return ok_object(public(rec))
