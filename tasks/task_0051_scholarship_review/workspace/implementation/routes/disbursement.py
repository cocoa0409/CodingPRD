"""Disbursement plan create / approve / revert / execute / records."""
from flask import Blueprint, g

import db
from clock import now_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import calculations
from services.audit import emit_audit
from services.lookup import (
    get_scholarship_or_404, get_plan_or_404, check_version,
)
from services.validation import get_body


bp = Blueprint("disbursement", __name__)


VALID_CHANNELS = {"BANK", "CAMPUS_CARD"}


@bp.route("/scholarships/<scholarship_id>/disbursement-plans", methods=["POST"])
@require_auth(roles={"FinanceOfficer"})
def create_plan(scholarship_id):
    s = get_scholarship_or_404(scholarship_id)
    body = get_body()
    channel = body.get("payment_channel")
    if channel not in VALID_CHANNELS:
        raise err("ERR_BAD_REQUEST", "payment_channel must be BANK or CAMPUS_CARD")

    # Aggregate AWARDED applications
    awarded = [a for a in db.applications.values()
               if a["scholarship_id"] == s["id"] and a["status"] == "AWARDED"]
    total_gross = len(awarded) * s["per_award_amount_cents"]
    per_tax = calculations.compute_tax_withheld(s["per_award_amount_cents"])
    total_tax = len(awarded) * per_tax
    total_net = total_gross - total_tax

    entity = {
        "scholarship_id": s["id"],
        "payment_channel": channel,
        "status": "DRAFT",
        "total_gross_cents": total_gross,
        "total_tax_cents": total_tax,
        "total_net_cents": total_net,
        "dept_approver_id": None,
        "finance_approver_id": None,
    }
    db.stamp_create(entity, common_fields=True)
    db.disbursement_plans[entity["id"]] = entity
    return success(db.public(entity), 201)


@bp.route("/scholarships/<scholarship_id>/disbursement-plans/<plan_id>", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "DeptOfficer", "FinanceOfficer"})
def get_plan(scholarship_id, plan_id):
    get_scholarship_or_404(scholarship_id)
    p = get_plan_or_404(scholarship_id, plan_id)
    return success(db.public(p), 200)


@bp.route("/scholarships/<scholarship_id>/disbursement-plans/<plan_id>/approve", methods=["POST"])
@require_auth(roles={"DeptOfficer", "FinanceOfficer"})
def approve_plan(scholarship_id, plan_id):
    s = get_scholarship_or_404(scholarship_id)
    p = get_plan_or_404(scholarship_id, plan_id)
    body = get_body()
    check_version(p, body)
    level = body.get("level")
    if level not in ("DEPT", "FINANCE"):
        raise err("ERR_BAD_REQUEST", "level must be DEPT or FINANCE")

    if s["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "Scholarship must be FINALIZED to approve disbursement")

    role = g.user_role
    if level == "DEPT":
        if role != "DeptOfficer":
            raise err("ERR_FORBIDDEN", "DEPT approval requires DeptOfficer role")
        if p["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "DEPT approval requires plan in DRAFT")
        if p["total_gross_cents"] <= 0:
            raise err("ERR_PLAN_EMPTY", "total_gross_cents must be > 0")
        p["dept_approver_id"] = g.user_id
        p["status"] = "DEPT_APPROVED"
        db.stamp_update(p)
        emit_audit("DISBURSEMENT_APPROVED", "DisbursementPlan", p["id"],
                   {"level": "DEPT", "from": "DRAFT", "to": "DEPT_APPROVED"})
    else:
        if role != "FinanceOfficer":
            raise err("ERR_FORBIDDEN", "FINANCE approval requires FinanceOfficer role")
        if p["status"] != "DEPT_APPROVED":
            raise err("ERR_INVALID_STATE", "FINANCE approval requires plan in DEPT_APPROVED")
        if p.get("dept_approver_id") == g.user_id:
            raise err("ERR_SOD_VIOLATION", "Finance approver must differ from Dept approver")
        p["finance_approver_id"] = g.user_id
        p["status"] = "FINANCE_APPROVED"
        db.stamp_update(p)
        emit_audit("DISBURSEMENT_APPROVED", "DisbursementPlan", p["id"],
                   {"level": "FINANCE", "from": "DEPT_APPROVED", "to": "FINANCE_APPROVED"})

    return success(db.public(p), 200)


@bp.route("/scholarships/<scholarship_id>/disbursement-plans/<plan_id>/revert", methods=["POST"])
@require_auth(roles={"DeptOfficer"})
def revert_plan(scholarship_id, plan_id):
    s = get_scholarship_or_404(scholarship_id)
    p = get_plan_or_404(scholarship_id, plan_id)
    body = get_body()
    check_version(p, body)
    if s["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "Scholarship must be FINALIZED to revert plan")
    if p["status"] != "DEPT_APPROVED":
        raise err("ERR_INVALID_STATE", "Plan must be DEPT_APPROVED to revert")
    if p.get("dept_approver_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Only the original dept approver may revert")

    p["dept_approver_id"] = None
    p["status"] = "DRAFT"
    db.stamp_update(p)
    emit_audit("DISBURSEMENT_APPROVED", "DisbursementPlan", p["id"],
               {"level": "DEPT", "action": "REVERT",
                 "from": "DEPT_APPROVED", "to": "DRAFT"})
    return success(db.public(p), 200)


@bp.route("/scholarships/<scholarship_id>/disbursement-plans/<plan_id>/execute", methods=["POST"])
@require_auth(roles={"FinanceOfficer"})
def execute_plan(scholarship_id, plan_id):
    s = get_scholarship_or_404(scholarship_id)
    p = get_plan_or_404(scholarship_id, plan_id)
    body = get_body()
    check_version(p, body)
    if s["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "Scholarship must be FINALIZED to execute plan")
    if p["status"] != "FINANCE_APPROVED":
        raise err("ERR_INVALID_STATE", "Plan must be FINANCE_APPROVED to execute")
    if p.get("finance_approver_id") != g.user_id:
        raise err("ERR_EXECUTOR_MISMATCH", "Executor must equal finance_approver_id")

    awarded = [a for a in db.applications.values()
               if a["scholarship_id"] == s["id"] and a["status"] == "AWARDED"]
    executed_at = now_iso()
    for a in awarded:
        gross = s["per_award_amount_cents"]
        tax = calculations.compute_tax_withheld(gross)
        net = gross - tax
        channel = calculations.route_channel(net, p["payment_channel"])
        rec = {
            "plan_id": p["id"],
            "application_id": a["id"],
            "student_id": a["student_id"],
            "gross_cents": gross,
            "tax_withheld_cents": tax,
            "net_cents": net,
            "payment_channel": channel,
            "executed_at": executed_at,
        }
        db.stamp_create(rec, common_fields=False)
        db.disbursement_records[rec["id"]] = rec

    p["status"] = "EXECUTED"
    db.stamp_update(p)
    emit_audit("DISBURSEMENT_EXECUTED", "DisbursementPlan", p["id"],
               {"from": "FINANCE_APPROVED", "to": "EXECUTED",
                 "record_count": len(awarded)})
    return success(db.public(p), 200)


@bp.route("/scholarships/<scholarship_id>/disbursement-plans/<plan_id>/records", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "FinanceOfficer"})
def list_records(scholarship_id, plan_id):
    get_scholarship_or_404(scholarship_id)
    get_plan_or_404(scholarship_id, plan_id)
    limit, offset = get_pagination()
    rows = [r for r in db.disbursement_records.values() if r["plan_id"] == plan_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total)
