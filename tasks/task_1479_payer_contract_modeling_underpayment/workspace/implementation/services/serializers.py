"""Resource -> wire format serializers (computed fields resolved here)."""

import db as _db
from services.cases import compute_case_ledger


def _base(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_payer(p):
    out = _base(p)
    out.update({
        "name": p["name"],
        "payer_type": p["payer_type"],
        "appeal_deadline_days": p["appeal_deadline_days"],
        "status": p["status"],
    })
    return out


def serialize_contract(c):
    # open_underpayment_cents: read-time rollup, never stored
    open_cents = 0
    for case in _db.store.cases.values():
        if case.get("contract_id") == c["id"] and case["status"] not in {
            "RECOVERED", "DENIED_FINAL", "WRITTEN_OFF", "WITHDRAWN",
        }:
            ledger = compute_case_ledger(case)
            open_cents += ledger["current_outstanding_cents"]
    out = _base(c)
    out.update({
        "payer_id": c["payer_id"],
        "contract_code": c["contract_code"],
        "effective_date": c["effective_date"],
        "expiration_date": c["expiration_date"],
        "prior_contract_id": c.get("prior_contract_id"),
        "payment_terms_days": c["payment_terms_days"],
        "underpayment_threshold_cents": c["underpayment_threshold_cents"],
        "underpayment_threshold_bp": c["underpayment_threshold_bp"],
        "volume_tiers": c.get("volume_tiers", []),
        "status": c["status"],
        "open_underpayment_cents": open_cents,
    })
    return out


def serialize_term(t):
    out = _base(t)
    out.update({
        "contract_id": t["contract_id"],
        "service_category": t["service_category"],
        "rate_model": t["rate_model"],
        "base_rate_cents": t.get("base_rate_cents"),
        "percent_of_charge_bp": t.get("percent_of_charge_bp"),
    })
    return out


def serialize_carve_out(p):
    out = _base(p)
    out.update({
        "contract_id": p["contract_id"],
        "carve_type": p["carve_type"],
        "revenue_codes": p["revenue_codes"],
        "rate_model": p["rate_model"],
        "percent_bp": p.get("percent_bp"),
        "invoice_markup_bp": p.get("invoice_markup_bp"),
        "max_cap_cents": p.get("max_cap_cents"),
    })
    return out


def serialize_stop_loss(p):
    out = _base(p)
    out.update({
        "contract_id": p["contract_id"],
        "provision_type": p["provision_type"],
        "service_category": p.get("service_category"),
        "threshold_cents": p["threshold_cents"],
        "rate_bp": p["rate_bp"],
    })
    return out


def serialize_escalator(e):
    out = _base(e)
    out.update({
        "contract_id": e["contract_id"],
        "effective_date": e["effective_date"],
        "escalator_bp": e["escalator_bp"],
        "applies_to_category": e.get("applies_to_category"),
        "compounding": e.get("compounding", True),
        "status": e["status"],
        "applied_date": e.get("applied_date"),
    })
    return out


def serialize_amendment(a):
    out = _base(a)
    out.update({
        "contract_id": a["contract_id"],
        "supersedes_amendment_id": a.get("supersedes_amendment_id"),
        "effective_date": a["effective_date"],
        "retroactive_to_date": a.get("retroactive_to_date"),
        "term_overrides": a["term_overrides"],
        "status": a["status"],
        "created_by_user_id": a["created_by_user_id"],
        "approved_by_user_id": a.get("approved_by_user_id"),
    })
    return out


def serialize_network_agreement(n):
    out = _base(n)
    out.update({
        "payer_id": n["payer_id"],
        "network_name": n["network_name"],
        "wrap_rate_bp": n["wrap_rate_bp"],
        "precedence_rank": n["precedence_rank"],
        "effective_date": n["effective_date"],
        "expiration_date": n["expiration_date"],
        "status": n["status"],
    })
    return out


def serialize_claim(c):
    from services.pricing import compute_paid_amount, compute_variance
    paid = compute_paid_amount(c["id"])
    variance = compute_variance(c)
    out = _base(c)
    out.update({
        "payer_id": c["payer_id"],
        "claim_number": c["claim_number"],
        "patient_account_number": c["patient_account_number"],
        "service_category": c["service_category"],
        "admission_date": c["admission_date"],
        "discharge_date": c["discharge_date"],
        "total_billed_charges_cents": c["total_billed_charges_cents"],
        "drg_weight": c.get("drg_weight"),
        "pricing_status": c["pricing_status"],
        "remittance_status": c["remittance_status"],
        "priced_contract_id": c.get("priced_contract_id"),
        "network_agreement_id": c.get("network_agreement_id"),
        "network_flag": c["network_flag"],
        "pricing_variant": c.get("pricing_variant"),
        "expected_reimbursement_cents": c.get("expected_reimbursement_cents"),
        "original_expected_cents": c.get("original_expected_cents"),
        "paid_amount_cents": paid,
        "variance_cents": variance,
        "pricing_trace": c.get("pricing_trace"),
    })
    return out


def serialize_claim_line(l):
    out = _base(l)
    out.update({
        "claim_id": l["claim_id"],
        "revenue_code": l["revenue_code"],
        "service_date": l["service_date"],
        "charge_cents": l["charge_cents"],
        "units": l["units"],
        "invoice_cost_cents": l.get("invoice_cost_cents"),
        "is_carve_out": l.get("is_carve_out", False),
        "priced_amount_cents": l.get("priced_amount_cents"),
    })
    return out


def serialize_remittance(r):
    out = _base(r)
    out.update({
        "claim_id": r["claim_id"],
        "appeal_id": r.get("appeal_id"),
        "paid_amount_cents": r["paid_amount_cents"],
        "remittance_date": r["remittance_date"],
        "adjustment_reason_code": r.get("adjustment_reason_code", "OTHER"),
        "source": r["source"],
        "status": r["status"],
    })
    return out


def serialize_case(c):
    ledger = compute_case_ledger(c)
    payer = _db.store.payers.get(c["payer_id"])
    days = payer["appeal_deadline_days"] if payer else 45
    from datetime import timedelta
    qd = db_parse_date(c["queued_date"])
    deadline = (qd + timedelta(days=days)).isoformat()
    out = _base(c)
    out.update({
        "claim_id": c["claim_id"],
        "payer_id": c["payer_id"],
        "contract_id": c.get("contract_id"),
        "original_variance_cents": c["original_variance_cents"],
        "current_outstanding_cents": ledger["current_outstanding_cents"],
        "recovered_to_date_cents": ledger["recovered_to_date_cents"],
        "write_off_amount_cents": c.get("write_off_amount_cents", 0),
        "escalation_level": c["escalation_level"],
        "status": c["status"],
        "claimed_by_user_id": c.get("claimed_by_user_id"),
        "queued_date": c["queued_date"],
        "appeal_filing_deadline": deadline,
    })
    return out


def db_parse_date(s):
    from db import parse_date
    return parse_date(s)


def serialize_appeal(a):
    out = _base(a)
    out.update({
        "case_id": a["case_id"],
        "level": a["level"],
        "channel": a["channel"],
        "status": a["status"],
        "outcome": a["outcome"],
        "filed_date": a.get("filed_date"),
        "response_due_date": a.get("response_due_date"),
        "outcome_recorded_date": a.get("outcome_recorded_date"),
        "recovered_amount_cents": a.get("recovered_amount_cents", 0),
    })
    return out


def serialize_proposal(p):
    contract = _db.store.contracts.get(p["contract_id"])
    is_stale = False
    if p["status"] in {"MODELED", "SUBMITTED", "COUNTERED"} and contract is not None:
        mv = p.get("modeled_contract_version")
        is_stale = mv is not None and mv != contract["version"]
    out = _base(p)
    out.update({
        "contract_id": p["contract_id"],
        "round_number": p["round_number"],
        "proposed_terms": p["proposed_terms"],
        "projected_volume_mix": p["projected_volume_mix"],
        "modeled_contract_version": p.get("modeled_contract_version"),
        "baseline_same_store_cents": p.get("baseline_same_store_cents"),
        "delta_same_store_cents": p.get("delta_same_store_cents"),
        "baseline_mix_shifted_cents": p.get("baseline_mix_shifted_cents"),
        "delta_mix_shifted_cents": p.get("delta_mix_shifted_cents"),
        "is_stale": is_stale,
        "status": p["status"],
    })
    return out


def serialize_alert(a):
    out = _base(a)
    out.update({
        "contract_id": a["contract_id"],
        "escalator_id": a.get("escalator_id"),
        "amendment_id": a.get("amendment_id"),
        "alert_type": a["alert_type"],
        "trigger_date": a["trigger_date"],
        "status": a["status"],
    })
    return out
