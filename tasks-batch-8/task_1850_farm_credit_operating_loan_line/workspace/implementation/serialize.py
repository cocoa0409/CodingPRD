"""Entity serializers (common fields: id, created_at, updated_at, version)
and list-pagination helpers (PRD 2.3, 2.6)."""
from flask import request

from db import get_clock
from errors import raise_err
from services.core import (available_credit_cents, coverage_cents,
                           pending_draw_cents, perfection_state)
from util import fmt_date, fmt_iso, fmt_ts3


def _common(e):
    return {"id": e["id"], "created_at": fmt_ts3(e["created_at"]),
            "updated_at": fmt_ts3(e["updated_at"]), "version": e["version"]}


def _dt(v):
    return None if v is None else fmt_iso(v)


def _date(v):
    return None if v is None else fmt_date(v)


def ser_association(a):
    out = _common(a)
    out.update({
        "name": a["name"],
        "charter_number": a["charter_number"],
        "review_index": a["review_index"],
        "active_disaster_declarations": [
            {"disaster_ref": d["disaster_ref"], "counties": list(d["counties"]),
             "start_date": fmt_iso(d["start_date"]), "end_date": fmt_iso(d["end_date"])}
            for d in a["active_disaster_declarations"]
        ],
        "current_fiscal_year": get_clock().year,
    })
    return out


def ser_borrower(b):
    out = _common(b)
    out.update({
        "association_id": b["association_id"],
        "legal_name": b["legal_name"],
        "tax_id": b["tax_id"],
        "county": b["county"],
        "status": b["status"],
        "patronage_eligible": b["patronage_eligible"],
        "active_covenant_breach_count": b["active_covenant_breach_count"],
    })
    return out


def ser_loan(l):
    out = _common(l)
    out.update({
        "borrower_id": l["borrower_id"],
        "association_id": l["association_id"],
        "requested_commitment_cents": l["requested_commitment_cents"],
        "approved_commitment_cents": l["approved_commitment_cents"],
        "rate_bps": l["rate_bps"],
        "season_year": l["season_year"],
        "maturity_date": _dt(l["maturity_date"]),
        "status": l["status"],
        "payment_posture": l["payment_posture"],
        "consecutive_delinquent_reviews": l["consecutive_delinquent_reviews"],
        "outstanding_principal_cents": l["outstanding_principal_cents"],
        "accrued_interest_cents": l["accrued_interest_cents"],
        "last_accrual_date": _date(l["last_accrual_date"]),
        "borrowing_base_cents": l["borrowing_base_cents"],
        "pending_draw_cents": pending_draw_cents(l),
    })
    return out


def ser_budget(b):
    out = _common(b)
    out.update({
        "loan_account_id": b["loan_account_id"],
        "season_year": b["season_year"],
        "crop_type": b["crop_type"],
        "acres": b["acres"],
        "projected_revenue_cents": b["projected_revenue_cents"],
        "projected_expenses_cents": b["projected_expenses_cents"],
        "actual_revenue_cents": b["actual_revenue_cents"],
        "status": b["status"],
    })
    return out


def ser_collateral(c):
    out = _common(c)
    out.update({
        "loan_account_id": c["loan_account_id"],
        "collateral_type": c["collateral_type"],
        "description": c["description"],
        "appraised_value_cents": c["appraised_value_cents"],
        "prior_lien_cents": c["prior_lien_cents"],
        "status": c["status"],
        "perfection_state": perfection_state(c),
    })
    return out


def ser_filing(f):
    out = _common(f)
    out.update({
        "collateral_id": f["collateral_id"],
        "filing_number": f["filing_number"],
        "jurisdiction": f["jurisdiction"],
        "filed_date": _dt(f["filed_date"]),
        "lapse_date": _dt(f["lapse_date"]),
        "status": f["status"],
    })
    return out


def ser_policy(p):
    out = _common(p)
    out.update({
        "borrower_id": p["borrower_id"],
        "assigned_loan_id": p["assigned_loan_id"],
        "policy_number": p["policy_number"],
        "crop_type": p["crop_type"],
        "county": p["county"],
        "coverage_start": _dt(p["coverage_start"]),
        "coverage_end": _dt(p["coverage_end"]),
        "coverage_amount_cents": p["coverage_amount_cents"],
        "status": p["status"],
        "assignment_status": p["assignment_status"],
    })
    return out


def ser_claim(c):
    out = _common(c)
    out.update({
        "policy_id": c["policy_id"],
        "loan_account_id": c["loan_account_id"],
        "claimed_loss_cents": c["claimed_loss_cents"],
        "adjuster_approved_cents": c["adjuster_approved_cents"],
        "indemnity_to_lender_cents": c["indemnity_to_lender_cents"],
        "applied_interest_cents": c["applied_interest_cents"],
        "applied_principal_cents": c["applied_principal_cents"],
        "remitted_to_borrower_cents": c["remitted_to_borrower_cents"],
        "status": c["status"],
    })
    return out


def ser_draw(d):
    out = _common(d)
    out.update({
        "loan_account_id": d["loan_account_id"],
        "amount_cents": d["amount_cents"],
        "purpose": d["purpose"],
        "disbursement_date": _dt(d["disbursement_date"]),
        "status": d["status"],
    })
    return out


def ser_repayment(r):
    out = _common(r)
    out.update({
        "loan_account_id": r["loan_account_id"],
        "amount_cents": r["amount_cents"],
        "source": r["source"],
        "applied_interest_cents": r["applied_interest_cents"],
        "applied_principal_cents": r["applied_principal_cents"],
        "status": r["status"],
    })
    return out


def ser_covenant(c):
    out = _common(c)
    out.update({
        "loan_account_id": c["loan_account_id"],
        "borrower_id": c["borrower_id"],
        "as_of_date": _dt(c["as_of_date"]),
        "current_assets_cents": c["current_assets_cents"],
        "current_liabilities_cents": c["current_liabilities_cents"],
        "working_capital_cents": c["working_capital_cents"],
        "current_ratio_milli": c["current_ratio_milli"],
        "required_ratio_milli": c["required_ratio_milli"],
        "outcome": c["outcome"],
        "recorded_by_user_id": c["recorded_by_user_id"],
        "status": c["status"],
    })
    return out


def ser_plan(p):
    out = _common(p)
    out.update({
        "loan_account_id": p["loan_account_id"],
        "plan_type": p["plan_type"],
        "amortization_style": p["amortization_style"],
        "extension_months": p["extension_months"],
        "new_rate_bps": p["new_rate_bps"],
        "capitalize_interest": p["capitalize_interest"],
        "base_balance_cents": p["base_balance_cents"],
        "new_installment_cents": p["new_installment_cents"],
        "created_by_user_id": p["created_by_user_id"],
        "status": p["status"],
    })
    return out


def ser_deferral(d):
    out = _common(d)
    out.update({
        "loan_account_id": d["loan_account_id"],
        "disaster_ref": d["disaster_ref"],
        "requested_start": _dt(d["requested_start"]),
        "requested_end": _dt(d["requested_end"]),
        "status": d["status"],
    })
    return out


def ser_distribution(d):
    out = _common(d)
    out.update({
        "association_id": d["association_id"],
        "fiscal_year": d["fiscal_year"],
        "pool_cents": d["pool_cents"],
        "allocated_cents": d["allocated_cents"],
        "undistributed_cents": d["undistributed_cents"],
        "allocation_lines": [dict(line) for line in d["allocation_lines"]],
        "status": d["status"],
    })
    return out


def ser_notice(n):
    out = _common(n)
    out.update({
        "loan_account_id": n["loan_account_id"],
        "deficiency_cents": n["deficiency_cents"],
        "status": n["status"],
    })
    return out


# ---------------------------------------------------------------------------
# List helpers: pagination (limit default 10, min 1, max 100; offset default 0)
# and equality filters; results sorted by created_at ascending (oldest first).
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "limit and offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(items, serializer, filters):
    """filters: list of (query_param, value_getter) pairs."""
    result = list(items)
    for param, getter in filters:
        raw = request.args.get(param)
        if raw is not None:
            result = [e for e in result if str(getter(e)) == raw]
    result.sort(key=lambda e: e["_seq"])  # created_at ascending == creation order
    total = len(result)
    limit, offset = parse_pagination()
    page = result[offset:offset + limit]
    return page, total, limit, offset, serializer
