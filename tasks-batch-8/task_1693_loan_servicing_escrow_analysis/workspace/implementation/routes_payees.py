"""Payees."""

from datetime import timedelta

from flask import Blueprint, request

from auth import any_role, require_roles
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_SOD,
    not_found,
)
from serializers import disbursement_out, line_item_out, payee_out
from store import store
from util import bump, fmt_date, new_record, now_ts, ok, ok_list, today
from validate import body, req_enum, req_str

bp = Blueprint("payees", __name__)

PAYEE_TYPES = ("TAX_AUTHORITY", "INSURANCE_CARRIER", "PMI_PROVIDER")


def get_payee_or_404(pid):
    p = store.payees.get(pid)
    if p is None:
        raise not_found("Payee not found")
    return p


def _cascade_block(payee_id):
    for d in sorted(store.disbursements.values(), key=lambda r: r["_seq"]):
        if d["payee_id"] == payee_id and d["status"] == "SCHEDULED":
            d["status"] = "BLOCKED"
            bump(d)


def _cascade_unblock(payee_id):
    for d in sorted(store.disbursements.values(), key=lambda r: r["_seq"]):
        if d["payee_id"] == payee_id and d["status"] == "BLOCKED":
            d["status"] = "SCHEDULED"
            bump(d)


@bp.post("/servicing/payees")
def create_payee():
    uid, _ = require_roles("DisbursementProcessor")
    data = body()
    payee_type = req_enum(data, "payee_type", PAYEE_TYPES)
    legal_name = req_str(data, "legal_name")
    remit = req_str(data, "remit_to_address")
    mask = req_str(data, "ach_routing_mask")
    p = new_record({
        "payee_type": payee_type,
        "legal_name": legal_name,
        "remit_to_address": remit,
        "ach_routing_mask": mask,
        "created_by_user_id": uid,
        "verification_status": "PENDING_VERIFICATION",
        "verified_by_user_id": None,
        "verified_at": None,
        "verification_expires_at": None,
    })
    store.payees[p["id"]] = p
    return ok(payee_out(p), 201)


@bp.get("/servicing/payees")
def list_payees():
    any_role()
    rows = sorted(store.payees.values(), key=lambda r: r["_seq"])
    vs = request.args.get("verification_status")
    if vs is not None:
        rows = [r for r in rows if r["verification_status"] == vs]
    pt = request.args.get("payee_type")
    if pt is not None:
        rows = [r for r in rows if r["payee_type"] == pt]
    return ok_list([payee_out(r) for r in rows])


@bp.get("/servicing/payees/<pid>")
def get_payee(pid):
    any_role()
    return ok(payee_out(get_payee_or_404(pid)))


@bp.post("/servicing/payees/<pid>/verify")
def verify_payee(pid):
    uid, _ = require_roles("PayeeVerifier")
    p = get_payee_or_404(pid)
    if p["verification_status"] == "REJECTED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Payee is REJECTED")
    if p["verification_status"] not in ("PENDING_VERIFICATION", "SUSPENDED", "EXPIRED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Payee cannot be verified from this state")
    if uid == p["created_by_user_id"]:
        raise ApiError(ERR_SOD, 409, "Verifier must differ from creator")
    was_blocked_source = p["verification_status"] in ("SUSPENDED", "EXPIRED")
    p["verification_status"] = "VERIFIED"
    p["verified_by_user_id"] = uid
    p["verified_at"] = now_ts()
    p["verification_expires_at"] = fmt_date(today() + timedelta(days=365))
    bump(p)
    if was_blocked_source:
        _cascade_unblock(p["id"])
    return ok(payee_out(p))


@bp.post("/servicing/payees/<pid>/reject")
def reject_payee(pid):
    require_roles("PayeeVerifier")
    p = get_payee_or_404(pid)
    if p["verification_status"] == "REJECTED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Payee is REJECTED")
    if p["verification_status"] != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Payee is not PENDING_VERIFICATION")
    p["verification_status"] = "REJECTED"
    bump(p)
    return ok(payee_out(p))


@bp.post("/servicing/payees/<pid>/suspend")
def suspend_payee(pid):
    require_roles("PayeeVerifier", "ComplianceOfficer")
    p = get_payee_or_404(pid)
    if p["verification_status"] == "REJECTED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Payee is REJECTED")
    if p["verification_status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Payee is not VERIFIED")
    p["verification_status"] = "SUSPENDED"
    bump(p)
    _cascade_block(p["id"])
    return ok(payee_out(p))


@bp.get("/servicing/payees/<pid>/disbursements")
def payee_disbursements(pid):
    any_role()
    p = get_payee_or_404(pid)
    rows = [d for d in sorted(store.disbursements.values(), key=lambda r: r["_seq"])
            if d["payee_id"] == p["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([disbursement_out(r) for r in rows])


@bp.get("/servicing/payees/<pid>/line-items")
def payee_line_items(pid):
    any_role()
    p = get_payee_or_404(pid)
    rows = [li for li in sorted(store.line_items.values(), key=lambda r: r["_seq"])
            if li["payee_id"] == p["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([line_item_out(r) for r in rows])
