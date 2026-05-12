"""Deposit routes."""
from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth
from response import success
from services.lookups import get_deposit, get_lease, get_move_out_for_lease
from services.validation import require_body, get_body, require_int
from services.occ import check_version
from services.tenant_ledger import recompute_for_tenant
from services.audit import record as audit_record


bp = Blueprint("deposits", __name__)


def _check_tenant_ownership_deposit(d: dict) -> None:
    if g.user_role == "Tenant":
        le = db.leases.get(d["lease_id"])
        if le is None or le.get("tenant_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Tenants can only access their own deposit")


@bp.get("/deposits/<deposit_id>")
@require_auth(roles={"PropertyManager", "LeasingAgent", "FinanceOfficer", "Tenant"})
def get_deposit_route(deposit_id):
    d = get_deposit(deposit_id)
    _check_tenant_ownership_deposit(d)
    return success(db.public(d))


@bp.post("/deposits/<deposit_id>/top-up")
@require_auth(roles={"Tenant"})
def top_up(deposit_id):
    d = get_deposit(deposit_id)
    _check_tenant_ownership_deposit(d)
    body = require_body(request)
    check_version(body, d)
    amount = require_int(body, "amount_cents", min_value=1)
    if d["collected_cents"] + amount > d["required_cents"]:
        raise err("ERR_DEPOSIT_OVERPAY",
                  "Top-up would push collected_cents above required_cents")
    d["collected_cents"] = d["collected_cents"] + amount
    # adjustment_status update: only if previously ADJUSTMENT_PENDING
    if d["adjustment_status"] == "ADJUSTMENT_PENDING" and d["collected_cents"] == d["required_cents"]:
        d["adjustment_status"] = "AT_REST"
    db.stamp_update(d)
    # Recompute tenant ledger
    le = db.leases.get(d["lease_id"])
    if le is not None:
        recompute_for_tenant(le["tenant_id"])
    return success(db.public(d))


@bp.post("/deposits/<deposit_id>/propose-deductions")
@require_auth(roles={"PropertyManager"})
def propose_deductions(deposit_id):
    d = get_deposit(deposit_id)
    body = require_body(request)
    check_version(body, d)
    items = body.get("deduction_items")
    # PRD §3.8 describes deduction_items as an array of elements; an
    # empty array is a valid boundary case (empty sum is 0, which
    # neither exceeds collected_cents nor violates any other PRD-stated
    # constraint). We accept an empty list.
    if not isinstance(items, list):
        raise err("ERR_VALIDATION", "deduction_items must be a list")
    le = get_lease(d["lease_id"])
    if le["status"] != "TERMINATING":
        raise err("ERR_INVALID_STATE",
                  f"Owning lease must be TERMINATING (current: {le['status']})")
    # Validate items
    total = 0
    parsed = []
    for it in items:
        if not isinstance(it, dict):
            raise err("ERR_VALIDATION", "deduction_items entries must be objects")
        kind = it.get("kind")
        if kind not in {"OVERDUE_RENT", "DAMAGE", "CLEANING"}:
            raise err("ERR_VALIDATION", "deduction_items[].kind invalid")
        amt = it.get("amount_cents")
        if isinstance(amt, bool) or not isinstance(amt, int) or amt < 0:
            raise err("ERR_VALIDATION", "deduction_items[].amount_cents must be a non-negative int")
        note = it.get("note")
        parsed.append({"kind": kind, "amount_cents": amt, "note": note})
        total += amt
    if total > d["collected_cents"]:
        raise err("ERR_DEDUCTION_EXCEEDS_DEPOSIT",
                  "Sum of deduction items exceeds Deposit.collected_cents")

    d["adjustment_status"] = "DEDUCTION_PENDING_APPROVAL"
    d["pending_deduction_items"] = parsed
    db.stamp_update(d)

    # Cascade move-out request to DEDUCTION_PROPOSED
    mor = get_move_out_for_lease(le["id"])
    if mor is not None:
        mor["status"] = "DEDUCTION_PROPOSED"
        db.stamp_update(mor)
    return success(db.public(d))


@bp.post("/deposits/<deposit_id>/approve-deductions")
@require_auth(roles={"FinanceOfficer"})
def approve_deductions(deposit_id):
    d = get_deposit(deposit_id)
    body = get_body(request)
    check_version(body, d)
    if d["adjustment_status"] != "DEDUCTION_PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE",
                  f"Deposit must be DEDUCTION_PENDING_APPROVAL (current: {d['adjustment_status']})")
    le = get_lease(d["lease_id"])
    mor = get_move_out_for_lease(le["id"])
    if mor is None or mor["status"] not in {"RESTORATION_CONFIRMED", "DEDUCTION_PROPOSED"}:
        cur = mor["status"] if mor else "None"
        raise err("ERR_INVALID_STATE",
                  f"MoveOutRequest must be RESTORATION_CONFIRMED or DEDUCTION_PROPOSED (current: {cur})")
    items = d.get("pending_deduction_items") or []
    retained_sum = sum(int(it["amount_cents"]) for it in items)
    d["retained_cents"] = retained_sum
    d["refunded_cents"] = d["collected_cents"] - retained_sum
    d["adjustment_status"] = "SETTLED"
    db.stamp_update(d)

    if mor is not None:
        mor["status"] = "DEDUCTION_APPROVED"
        db.stamp_update(mor)

    recompute_for_tenant(le["tenant_id"])

    audit_record(
        subject_kind="DEPOSIT", subject_id=d["id"], action="DEPOSIT_DEDUCTED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"deposit_id": d["id"], "retained_cents": retained_sum,
                 "items": items},
    )
    audit_record(
        subject_kind="DEPOSIT", subject_id=d["id"], action="DEPOSIT_REFUNDED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"deposit_id": d["id"], "refunded_cents": d["refunded_cents"]},
    )
    return success(db.public(d))


@bp.post("/deposits/<deposit_id>/reject-deductions")
@require_auth(roles={"FinanceOfficer"})
def reject_deductions(deposit_id):
    d = get_deposit(deposit_id)
    body = get_body(request)
    check_version(body, d)
    if d["adjustment_status"] != "DEDUCTION_PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE",
                  f"Deposit must be DEDUCTION_PENDING_APPROVAL (current: {d['adjustment_status']})")
    d["adjustment_status"] = "AT_REST"
    d["pending_deduction_items"] = []
    db.stamp_update(d)
    return success(db.public(d))
