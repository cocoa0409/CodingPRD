"""Financial-obligation endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.common import (
    apply_page,
    check_enum,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    recompute_balances,
    require_bool,
    require_fields,
    require_int_min,
    sorted_by_created,
)

bp = Blueprint("obligations", __name__)

OBLIGATION_TYPES = {"RESTITUTION", "FEE"}


@bp.post("/supervisees/<sid>/obligations")
@require_roles("Officer", "SupervisingJudge")
def create(sid):
    s = get_supervisee_or_404(sid)
    body = get_body()
    require_fields(body, ["obligation_type", "principal_cents"])
    check_enum(body["obligation_type"], OBLIGATION_TYPES, "obligation_type")
    require_int_min(body["principal_cents"], 1, "principal_cents")

    parent_obligation_id = body.get("parent_obligation_id")
    monthly_accrual = body.get("monthly_accrual_cents", 0)
    if monthly_accrual is None:
        monthly_accrual = 0
    require_int_min(monthly_accrual, 0, "monthly_accrual_cents")
    recurring = body.get("recurring", False)
    if recurring is None:
        recurring = False
    require_bool(recurring, "recurring")

    # Body FK existence for parent_obligation_id (ERR_REFERENCE_NOT_FOUND, 422).
    if parent_obligation_id is not None and parent_obligation_id not in db.obligations:
        raise ApiError(*ERR_REFERENCE_NOT_FOUND, "parent_obligation_id not found.")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "parent_obligation_id": parent_obligation_id,
            "obligation_type": body["obligation_type"],
            "principal_cents": body["principal_cents"],
            "monthly_accrual_cents": monthly_accrual,
            "recurring": recurring,
            "paid_cents": 0,
            "status": "OPEN",
        }
    )
    db.obligations[rec["id"]] = rec
    # Recompute balances to include the new obligation.
    if recompute_balances(s):
        db.touch(s)
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/obligations")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_obligations(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [o for o in db.obligations.values() if o.get("supervisee_id") == sid]
    ob_type = request.args.get("obligation_type")
    if ob_type is not None:
        records = [r for r in records if r["obligation_type"] == ob_type]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    parent = request.args.get("parent_obligation_id")
    if parent is not None:
        records = [r for r in records if r.get("parent_obligation_id") == parent]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/obligations/<oid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_obligation(sid, oid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.obligations, oid, sid, label="Obligation")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/obligations/<oid>/discharge")
@require_roles("SupervisingJudge")
def discharge(sid, oid):
    s = get_supervisee_or_404(sid)
    o = get_child_or_404(db.obligations, oid, sid, label="Obligation")
    if o["status"] not in ("OPEN", "PARTIALLY_PAID"):
        raise ApiError(*ERR_INVALID_STATE, "Obligation is not OPEN or PARTIALLY_PAID.")
    o["status"] = "DISCHARGED"
    db.touch(o)
    # Recompute balances so the discharged obligation no longer counts.
    if recompute_balances(s):
        db.touch(s)
    return object_response(public(o), 200)
