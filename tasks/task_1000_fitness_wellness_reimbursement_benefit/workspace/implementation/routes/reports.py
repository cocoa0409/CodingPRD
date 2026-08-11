"""Utilization report endpoint (calc_utilization_report)."""
from flask import request

from db import STORE
from errors import err, ERR_EMPLOYER_NOT_FOUND
from middleware import require_roles
from response import success
from util import month_range, rhu2
from flask import Blueprint

bp = Blueprint("reports", __name__)


@bp.get("/api/reports/utilization")
def utilization_report():
    require_roles("BenefitsAdmin", "Auditor")
    employer_id = request.args.get("employer_id")
    period = request.args.get("period_yyyymm")
    from errors import ERR_INVALID_REQUEST
    if not employer_id or not period:
        raise err(ERR_INVALID_REQUEST, 400, "employer_id and period_yyyymm are required")
    if employer_id not in STORE.employers:
        raise err(ERR_EMPLOYER_NOT_FOUND, 404, "employer id does not resolve")
    start, nxt = month_range(period)
    employer_plan_ids = {p["id"] for p in STORE.plans.values()
                         if p["employer_id"] == employer_id}
    enrs = [e for e in STORE.enrollments.values()
            if e["plan_id"] in employer_plan_ids
            and e["status"] in ("ACTIVE", "EXHAUSTED", "CLOSED")]
    total_allowance = sum(e["annual_allowance_cents"] for e in enrs)
    total_used = sum(e["used_cents"] for e in enrs)
    utilization = 0 if total_allowance == 0 else rhu2(
        __import__("decimal").Decimal(100 * total_used) / total_allowance)
    member_ids = {m["id"] for m in STORE.members.values()
                  if m["employer_id"] == employer_id}
    paid_claim_count = sum(
        1 for c in STORE.claims.values()
        if c["member_id"] in member_ids and c["payment_status"] == "PAID"
        and c["_paid_at"] is not None and start <= c["_paid_at"] < nxt)
    open_flags = 0
    for f in STORE.fraud_flags.values():
        if f["status"] != "OPEN":
            continue
        mid = None
        if f.get("visit_id") and f["visit_id"] in STORE.visits:
            mid = STORE.visits[f["visit_id"]]["member_id"]
        elif f.get("claim_id") and f["claim_id"] in STORE.claims:
            mid = STORE.claims[f["claim_id"]]["member_id"]
        if mid in member_ids:
            open_flags += 1
    return success({
        "employer_id": employer_id,
        "period_yyyymm": period,
        "enrolled_members": len(enrs),
        "total_allowance_cents": total_allowance,
        "total_used_cents": total_used,
        "utilization_pct": utilization,
        "paid_claim_count": paid_claim_count,
        "open_fraud_flags": open_flags,
    })
