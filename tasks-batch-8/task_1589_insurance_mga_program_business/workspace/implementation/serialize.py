"""Entity serializers. Datetimes are ISO 8601 UTC with three fractional
digits; internal fields (underscore-prefixed) never leak."""
from db import format_dt


def _dt(v):
    if v is None:
        return None
    return format_dt(v)


def _ratio(v):
    """Loss ratios are stored as Decimal (2dp) or None; emitted as JSON numbers."""
    if v is None:
        return None
    return float(v)


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def carrier(c):
    d = _common(c)
    d.update({
        "name": c["name"],
        "naic_code": c["naic_code"],
        "contact_email": c["contact_email"],
        "status": c["status"],
    })
    return d


def tpa(t):
    d = _common(t)
    d.update({
        "name": t["name"],
        "license_number": t["license_number"],
        "contact_email": t["contact_email"],
        "status": t["status"],
    })
    return d


def program(p):
    d = _common(p)
    d.update({
        "carrier_id": p["carrier_id"],
        "name": p["name"],
        "line_of_business": p["line_of_business"],
        "states_covered": list(p["states_covered"]),
        "inception_date": _dt(p["inception_date"]),
        "aggregate_limit_cents": p["aggregate_limit_cents"],
        "commission_rate_pct": p["commission_rate_pct"],
        "corrective_threshold_pct": p["corrective_threshold_pct"],
        "termination_threshold_pct": p["termination_threshold_pct"],
        "min_trust_balance_cents": p["min_trust_balance_cents"],
        "min_earned_premium_for_ratio_cents": p["min_earned_premium_for_ratio_cents"],
        "status": p["status"],
        "consumed_aggregate_cents": p["consumed_aggregate_cents"],
        "trust_balance_cents": p["trust_balance_cents"],
        "latest_incurred_loss_ratio_pct": _ratio(p["latest_incurred_loss_ratio_pct"]),
        "termination_reason": p["termination_reason"],
    })
    return d


def guideline(g):
    d = _common(g)
    d.update({
        "program_id": g["program_id"],
        "state_code": g["state_code"],
        "class_code": g["class_code"],
        "max_policy_premium_cents": g["max_policy_premium_cents"],
        "max_policy_limit_cents": g["max_policy_limit_cents"],
        "min_policy_premium_cents": g["min_policy_premium_cents"],
        "status": g["status"],
    })
    return d


def allocation(a):
    d = _common(a)
    d.update({
        "program_id": a["program_id"],
        "period_label": a["period_label"],
        "allocated_cents": a["allocated_cents"],
        "consumed_cents": a["consumed_cents"],
        "status": a["status"],
    })
    return d


def filing(f):
    d = _common(f)
    d.update({
        "program_id": f["program_id"],
        "state_code": f["state_code"],
        "filing_type": f["filing_type"],
        "base_rates": dict(f["base_rates"]),
        "policy_fee_cents": f["policy_fee_cents"],
        "effective_from": _dt(f["effective_from"]),
        "effective_to": _dt(f["effective_to"]),
        "status": f["status"],
        "version_seq": f["version_seq"],
        "submitted_at": _dt(f["submitted_at"]),
        "approved_at": _dt(f["approved_at"]),
    })
    return d


def policy(p):
    d = _common(p)
    d.update({
        "program_id": p["program_id"],
        "filing_id": p["filing_id"],
        "insured_name": p["insured_name"],
        "state_code": p["state_code"],
        "class_code": p["class_code"],
        "exposure_units": p["exposure_units"],
        "coverage_limit_cents": p["coverage_limit_cents"],
        "experience_mod": p["experience_mod"],
        "effective_from": _dt(p["effective_from"]),
        "effective_to": _dt(p["effective_to"]),
        "status": p["status"],
        "audit_status": p["audit_status"],
        "gross_premium_cents": p["gross_premium_cents"],
        "final_premium_cents": p["final_premium_cents"],
        "mga_commission_cents": p["mga_commission_cents"],
        "collected_cents": p["collected_cents"],
        "earned_premium_cents": p["earned_premium_cents"],
        "quote_valid_until": _dt(p["quote_valid_until"]),
        "bound_at": _dt(p["bound_at"]),
        "issued_at": _dt(p["issued_at"]),
        "cancelled_at": _dt(p["cancelled_at"]),
        "cancellation_date": _dt(p["cancellation_date"]),
        "cancellation_reason": p["cancellation_reason"],
        "pre_cancel_status": p["pre_cancel_status"],
        "capacity_released_cents": p["capacity_released_cents"],
        "reported_premium_bordereau_id": p["reported_premium_bordereau_id"],
    })
    return d


def claim(c):
    d = _common(c)
    d.update({
        "policy_id": c["policy_id"],
        "program_id": c["program_id"],
        "assigned_tpa_id": c["assigned_tpa_id"],
        "claim_type": c["claim_type"],
        "occurrence_date": _dt(c["occurrence_date"]),
        "amount_claimed_cents": c["amount_claimed_cents"],
        "case_reserve_cents": c["case_reserve_cents"],
        "approved_amount_cents": c["approved_amount_cents"],
        "paid_cents": c["paid_cents"],
        "status": c["status"],
        "denial_reason": c["denial_reason"],
        "denied_at": _dt(c["denied_at"]),
        "reopened_count": c["reopened_count"],
        "paid_at": _dt(c["paid_at"]),
        "referral_reason": c["referral_reason"],
        "reported_claim_bordereau_id": c["reported_claim_bordereau_id"],
    })
    return d


def appointment(a):
    d = _common(a)
    d.update({
        "program_id": a["program_id"],
        "tpa_id": a["tpa_id"],
        "claim_type": a["claim_type"],
        "authority_limit_cents": a["authority_limit_cents"],
        "effective_from": _dt(a["effective_from"]),
        "effective_to": _dt(a["effective_to"]),
        "status": a["status"],
    })
    return d


def ledger_entry(e):
    """TrustLedgerEntry carries id + created_at only (no updated_at/version)."""
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "program_id": e["program_id"],
        "policy_id": e["policy_id"],
        "claim_id": e["claim_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "basis_cents": e["basis_cents"],
        "running_balance_cents": e["running_balance_cents"],
        "memo": e["memo"],
    }


def bordereau(b):
    d = _common(b)
    d.update({
        "program_id": b["program_id"],
        "bordereau_type": b["bordereau_type"],
        "period_label": b["period_label"],
        "rows": b["rows"],
        "declared_totals": b["declared_totals"],
        "computed_totals": b["computed_totals"],
        "row_count": b["row_count"],
        "due_date": _dt(b["due_date"]),
        "overdue": b["overdue"],
        "status": b["status"],
        "rejection_reason": b["rejection_reason"],
        "submitted_at": _dt(b["submitted_at"]),
    })
    return d


def audit(a):
    d = _common(a)
    d.update({
        "program_id": a["program_id"],
        "scope": a["scope"],
        "scheduled_start": _dt(a["scheduled_start"]),
        "scheduled_end": _dt(a["scheduled_end"]),
        "findings": a["findings"],
        "status": a["status"],
        "outcome": a["outcome"],
    })
    return d


def loss_evaluation(e):
    d = _common(e)
    d.update({
        "program_id": e["program_id"],
        "period_label": e["period_label"],
        "earned_premium_cents": e["earned_premium_cents"],
        "paid_losses_cents": e["paid_losses_cents"],
        "case_reserves_cents": e["case_reserves_cents"],
        "paid_loss_ratio_pct": _ratio(e["paid_loss_ratio_pct"]),
        "incurred_loss_ratio_pct": _ratio(e["incurred_loss_ratio_pct"]),
        "outcome": e["outcome"],
    })
    return d
