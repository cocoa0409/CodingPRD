"""Entity serializers — convert stored dicts to API output shape."""

from services.derived import account_balance


def _iso_date(d):
    """Accept either a date object or string, return YYYY-MM-DD."""
    if d is None:
        return None
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return str(d)


def serialize_client(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "date_of_birth": _iso_date(c["date_of_birth"]),
        "ssn_last4": c["ssn_last4"],
        "county_of_residence": c["county_of_residence"],
        "medicaid_enrolled": c["medicaid_enrolled"],
        "medicaid_resource_limit_cents": c["medicaid_resource_limit_cents"],
        "status": c["status"],
        "total_funds_cents": c.get("total_funds_cents", 0),
        "countable_resources_cents": c.get("countable_resources_cents", 0),
        "medicaid_at_risk": c.get("medicaid_at_risk", False),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_entitlement(e):
    return {
        "id": e["id"],
        "client_id": e["client_id"],
        "claim_type": e["claim_type"],
        "monthly_benefit_cents": e["monthly_benefit_cents"],
        "effective_start_date": _iso_date(e["effective_start_date"]),
        "effective_end_date": _iso_date(e["effective_end_date"]) if e["effective_end_date"] else None,
        "status": e["status"],
        "verified_at": e.get("verified_at"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_account(a):
    return {
        "id": a["id"],
        "client_id": a["client_id"],
        "account_type": a["account_type"],
        "bank_account_ref": a["bank_account_ref"],
        "balance_cents": a.get("balance_cents", 0),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "account_id": e["account_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "reference_id": e["reference_id"],
        "balance_after_cents": e["balance_after_cents"],
        "created_at": e["created_at"],
    }


def serialize_budget_plan(p):
    return {
        "id": p["id"],
        "client_id": p["client_id"],
        "period_month": p["period_month"],
        "source_benefit_cents": p["source_benefit_cents"],
        "lines": p["lines"],
        "allocated_lines": p["allocated_lines"],
        "total_planned_cents": p["total_planned_cents"],
        "status": p["status"],
        "superseded_by_plan_id": p.get("superseded_by_plan_id"),
        "created_by_user_id": p.get("created_by_user_id"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_disbursement(d):
    return {
        "id": d["id"],
        "client_id": d["client_id"],
        "account_id": d["account_id"],
        "budget_plan_id": d["budget_plan_id"],
        "court_order_id": d.get("court_order_id"),
        "spend_down_plan_id": d.get("spend_down_plan_id"),
        "payee_name": d["payee_name"],
        "category": d["category"],
        "amount_cents": d["amount_cents"],
        "scheduled_release_date": _iso_date(d["scheduled_release_date"]),
        "requested_by_user_id": d.get("requested_by_user_id"),
        "approved_by_user_id": d.get("approved_by_user_id"),
        "co_approved_by_conservator_id": d.get("co_approved_by_conservator_id"),
        "fee_cents": d.get("fee_cents", 0),
        "released_at": d.get("released_at"),
        "returned_at": d.get("returned_at"),
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_deposit(d):
    return {
        "id": d["id"],
        "account_id": d["account_id"],
        "entitlement_id": d.get("entitlement_id"),
        "source": d["source"],
        "amount_cents": d["amount_cents"],
        "received_date": _iso_date(d["received_date"]),
        "posted_at": d.get("posted_at"),
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_court_order(o):
    return {
        "id": o["id"],
        "client_id": o["client_id"],
        "order_type": o["order_type"],
        "amount_limit_cents": o.get("amount_limit_cents"),
        "petitioned_date": _iso_date(o["petitioned_date"]),
        "granted_date": _iso_date(o.get("granted_date")),
        "expiry_date": _iso_date(o["expiry_date"]),
        "executed_disbursement_id": o.get("executed_disbursement_id"),
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_bond(b):
    return {
        "id": b["id"],
        "coverage_amount_cents": b["coverage_amount_cents"],
        "coverage_start_date": _iso_date(b["coverage_start_date"]),
        "coverage_end_date": _iso_date(b["coverage_end_date"]),
        "premium_paid_through_date": _iso_date(b["premium_paid_through_date"]),
        "status": b["status"],
        "funds_under_management_cents": b.get("funds_under_management_cents", 0),
        "utilization_bps": b.get("utilization_bps", 0),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_report(r):
    return {
        "id": r["id"],
        "client_id": r["client_id"],
        "report_type": r["report_type"],
        "period_start_date": _iso_date(r["period_start_date"]),
        "period_end_date": _iso_date(r["period_end_date"]),
        "basis": r["basis"],
        "due_date": _iso_date(r["due_date"]),
        "receipts_total_cents": r.get("receipts_total_cents"),
        "disbursements_total_cents": r.get("disbursements_total_cents"),
        "opening_balance_cents": r.get("opening_balance_cents"),
        "ending_balance_cents": r.get("ending_balance_cents"),
        "submitted_at": r.get("submitted_at"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_spend_down(sp):
    return {
        "id": sp["id"],
        "client_id": sp["client_id"],
        "target_month": sp["target_month"],
        "entries": sp["entries"],
        "provisional_excess_cents": sp.get("provisional_excess_cents", 0),
        "final_excess_cents": sp.get("final_excess_cents"),
        "auto_created": sp.get("auto_created", False),
        "status": sp["status"],
        "created_at": sp["created_at"],
        "updated_at": sp["updated_at"],
        "version": sp["version"],
    }


def serialize_audit_case(a):
    return {
        "id": a["id"],
        "client_id": a["client_id"],
        "authority": a["authority"],
        "scope": a["scope"],
        "period_start_date": _iso_date(a["period_start_date"]),
        "period_end_date": _iso_date(a["period_end_date"]),
        "misuse_amount_cents": a.get("misuse_amount_cents"),
        "findings_count": a.get("findings_count"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_conservator(c):
    return {
        "id": c["id"],
        "client_id": c["client_id"],
        "full_name": c["full_name"],
        "court_case_number": c["court_case_number"],
        "authority_scope": c["authority_scope"],
        "appointed_date": _iso_date(c["appointed_date"]),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
