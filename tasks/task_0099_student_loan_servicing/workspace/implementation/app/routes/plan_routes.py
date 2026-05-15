"""Repayment plan routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..clock import add_days, days_between, now_dt, now_iso_ms, parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..services import calculations as calc
from ..services.borrowers import recompute_aggregates
from ..store import bump_version, common_fields_create, get_store
from ._helpers import created, get_borrower_or_404, get_json_body, list_ok, ok


VALID_PLAN_TYPES = {"STANDARD_10", "IBR", "PAYE", "SAVE"}


def _validate_loan_ids(borrower_id: str, ids: list[str]) -> list[dict]:
    if not isinstance(ids, list) or not ids:
        raise ApiError("ERR_PLAN_LOAN_INELIGIBLE", "included_loan_ids must be a non-empty list.")
    store = get_store()
    out = []
    for lid in ids:
        loan = store.loans.get(lid)
        if not loan or loan.get("borrower_id") != borrower_id:
            raise ApiError("ERR_LOAN_NOT_FOUND", f"Loan {lid} not found.")
        out.append(loan)
    return out


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/plans", methods=["POST"])
    @require_auth("Borrower", "ServicerAdmin")
    def create_plan(borrower_id):
        b = get_borrower_or_404(borrower_id)
        body = get_json_body(allow_empty=False)
        plan_type = body.get("plan_type")
        if plan_type not in VALID_PLAN_TYPES:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid plan_type: {plan_type}")
        ids = body.get("included_loan_ids") or []
        # PRD §3.7: plan create only validates ownership of loans; loan-status
        # eligibility (REPAYMENT/GRACE) is enforced at activation time.
        _validate_loan_ids(borrower_id, ids)
        plan = {
            **common_fields_create(),
            "borrower_id": borrower_id,
            "plan_type": plan_type,
            "status": "PENDING",
            "effective_from": None,
            "certified_agi_cents": 0,
            "certified_family_size": 0,
            "monthly_payment_cents": 0,
            "recertification_due_at": None,
            "included_loan_ids": list(ids),
        }
        get_store().plans[plan["id"]] = plan
        return created(plan)

    @app.route("/borrowers/<borrower_id>/plans", methods=["GET"])
    @require_auth("Borrower", "ServicerAdmin", "ServicerCertifier")
    def list_plans(borrower_id):
        get_borrower_or_404(borrower_id)
        limit, offset = parse_limit_offset()
        status = parse_optional_str("status")
        items = [p for p in get_store().plans.values() if p["borrower_id"] == borrower_id]
        if status:
            items = [p for p in items if p["status"] == status]
        items.sort(key=lambda p: p["created_at"])
        page = {
            "limit": limit,
            "offset": offset,
            "total_count": len(items),
            "has_more": offset + limit < len(items),
        }
        return list_ok(items[offset : offset + limit], page)

    @app.route("/borrowers/<borrower_id>/plans/<plan_id>", methods=["GET"])
    @require_auth("Borrower", "ServicerAdmin", "ServicerCertifier")
    def get_plan(borrower_id, plan_id):
        get_borrower_or_404(borrower_id)
        p = get_store().plans.get(plan_id)
        if not p or p["borrower_id"] != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Plan {plan_id} not found.")
        return ok(p)

    @app.route("/borrowers/<borrower_id>/plans/<plan_id>/activate", methods=["POST"])
    @require_auth("Borrower", "ServicerAdmin")
    def activate_plan(borrower_id, plan_id):
        b = get_borrower_or_404(borrower_id)
        plan = get_store().plans.get(plan_id)
        if not plan or plan["borrower_id"] != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Plan {plan_id} not found.")
        if plan["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Plan must be PENDING to activate.")
        # Re-validate loan ids
        loans = _validate_loan_ids(borrower_id, plan.get("included_loan_ids", []))
        # included loans must be REPAYMENT or GRACE; DEFAULT explicitly blocks
        for l in loans:
            if l["status"] in ("DEFAULT",):
                raise ApiError(
                    "ERR_PLAN_LOAN_INELIGIBLE",
                    f"Loan {l['id']} is in DEFAULT.",
                )
            if l["status"] not in ("REPAYMENT", "GRACE"):
                raise ApiError(
                    "ERR_PLAN_LOAN_INELIGIBLE",
                    f"Loan {l['id']} is not in REPAYMENT or GRACE.",
                )
        # IDR plans require fresh AGI cert
        if plan["plan_type"] in ("IBR", "PAYE", "SAVE"):
            agi_at = b.get("agi_certified_at")
            if not agi_at:
                raise ApiError("ERR_AGI_NOT_CERTIFIED", "AGI not certified.")
            try:
                ac = parse_iso(agi_at)
            except Exception:
                raise ApiError("ERR_AGI_NOT_CERTIFIED", "AGI cert timestamp invalid.")
            if days_between(now_dt(), ac) > 365:
                raise ApiError("ERR_AGI_NOT_CERTIFIED", "AGI cert outside 365 days.")
        # Plan conflict: another ACTIVE plan covering any included loan.
        # Per PRD §3.7: sequential supersede is allowed — older plan cascades
        # to SUPERSEDED and the new plan proceeds. The concurrency rule §2.10
        # for ERR_PLAN_CONFLICT applies only to simultaneous activations on
        # different overlapping plans (a race condition), which in a serial
        # in-memory model never fires.
        overlapping = []
        for other in get_store().plans.values():
            if other["id"] == plan["id"]:
                continue
            if other["borrower_id"] != borrower_id:
                continue
            if other["status"] != "ACTIVE":
                continue
            if set(other.get("included_loan_ids", [])) & set(plan.get("included_loan_ids", [])):
                overlapping.append(other)
        for other in overlapping:
            other["status"] = "SUPERSEDED"
            bump_version(other)
        # Activation
        plan["status"] = "ACTIVE"
        plan["effective_from"] = now_iso_ms()
        if plan["plan_type"] in ("IBR", "PAYE", "SAVE"):
            plan["certified_agi_cents"] = int(b.get("adjusted_gross_income_cents", 0))
            plan["certified_family_size"] = int(b.get("family_size", 1))
            plan["recertification_due_at"] = _format_iso_dt_add(now_dt(), 365)
        else:
            plan["certified_agi_cents"] = 0
            plan["certified_family_size"] = 0
            plan["recertification_due_at"] = None
        plan["monthly_payment_cents"] = calc.compute_monthly_payment(plan, b, loans)
        bump_version(plan)
        return ok(plan)

    @app.route("/borrowers/<borrower_id>/plans/<plan_id>", methods=["DELETE"])
    @require_auth("Borrower", "ServicerAdmin")
    def delete_plan(borrower_id, plan_id):
        get_borrower_or_404(borrower_id)
        plan = get_store().plans.get(plan_id)
        if not plan or plan["borrower_id"] != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Plan {plan_id} not found.")
        if plan["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Only PENDING plans can be cancelled.")
        plan["status"] = "TERMINATED"
        bump_version(plan)
        return ok(plan)


def _format_iso_dt_add(dt, days: int) -> str:
    from ..clock import add_days, format_iso
    return format_iso(add_days(dt, days))
