"""Entity serialization. TrustAccount derived fields are computed live."""

import db


def income_balance(trust_id):
    return sum(e["amount_cents"] for e in db.ledger_entries.values()
               if e["trust_id"] == trust_id and e["bucket"] == "INCOME")


def principal_balance(trust_id):
    return sum(e["amount_cents"] for e in db.ledger_entries.values()
               if e["trust_id"] == trust_id and e["bucket"] == "PRINCIPAL")


RESERVING_STATES = ("VOTING", "APPROVED")
PENDING_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFORMATION_REQUESTED",
                  "VOTING", "APPROVED")


def reserved_income(trust_id):
    return sum(r["income_portion_cents"] for r in db.distribution_requests.values()
               if r["trust_id"] == trust_id and r["status"] in RESERVING_STATES)


def reserved_principal(trust_id):
    return sum(r["principal_portion_cents"] for r in db.distribution_requests.values()
               if r["trust_id"] == trust_id and r["status"] in RESERVING_STATES)


def holdings_market_value(trust_id):
    return sum(h["units"] * h["unit_price_cents"] for h in db.holdings.values()
               if h["trust_id"] == trust_id)


def total_market_value(trust_id):
    return (holdings_market_value(trust_id)
            + income_balance(trust_id) + principal_balance(trust_id))


def pending_distribution_count(trust_id):
    return sum(1 for r in db.distribution_requests.values()
               if r["trust_id"] == trust_id and r["status"] in PENDING_STATES)


def trust_json(t):
    tid = t["id"]
    inc = income_balance(tid)
    pri = principal_balance(tid)
    res_i = reserved_income(tid)
    res_p = reserved_principal(tid)
    return {
        "id": tid,
        "trust_name": t["trust_name"],
        "trust_type": t["trust_type"],
        "grantor_name": t["grantor_name"],
        "governing_state": t["governing_state"],
        "ein": t["ein"],
        "fiscal_year_end_month": t["fiscal_year_end_month"],
        "distribution_standard": t["distribution_standard"],
        "status": t["status"],
        "accepted_at": t["accepted_at"],
        "income_balance_cents": inc,
        "principal_balance_cents": pri,
        "reserved_income_cents": res_i,
        "reserved_principal_cents": res_p,
        "available_income_cents": inc - res_i,
        "available_principal_cents": pri - res_p,
        "total_market_value_cents": inc + pri + holdings_market_value(tid),
        "pending_distribution_count": pending_distribution_count(tid),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def document_json(d):
    return {
        "id": d["id"],
        "trust_id": d["trust_id"],
        "version_number": d["version_number"],
        "prior_document_id": d["prior_document_id"],
        "summary": d["summary"],
        "per_stirpes": d["per_stirpes"],
        "interpretation_notes": d["interpretation_notes"],
        "status": d["status"],
        "submitted_at": d["submitted_at"],
        "approved_at": d["approved_at"],
        "rejected_reason": d["rejected_reason"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def beneficiary_json(b):
    return {
        "id": b["id"],
        "trust_id": b["trust_id"],
        "full_name": b["full_name"],
        "beneficiary_class": b["beneficiary_class"],
        "share_bps": b["share_bps"],
        "date_of_birth": b["date_of_birth"],
        "status": b["status"],
        "deceased_at": b["deceased_at"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def committee_member_json(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "term_start": m["term_start"],
        "term_end": m["term_end"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def distribution_request_json(r):
    return {
        "id": r["id"],
        "trust_id": r["trust_id"],
        "beneficiary_id": r["beneficiary_id"],
        "amount_cents": r["amount_cents"],
        "allocation_source": r["allocation_source"],
        "purpose_category": r["purpose_category"],
        "purpose_note": r["purpose_note"],
        "status": r["status"],
        "income_portion_cents": r["income_portion_cents"],
        "principal_portion_cents": r["principal_portion_cents"],
        "approve_count": r["approve_count"],
        "decline_count": r["decline_count"],
        "abstain_count": r["abstain_count"],
        "committee_size_snapshot": r["committee_size_snapshot"],
        "opened_by_user_id": r["opened_by_user_id"],
        "decision_at": r["decision_at"],
        "disbursed_at": r["disbursed_at"],
        "cancelled_reason": r["cancelled_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def vote_json(v):
    return {
        "id": v["id"],
        "distribution_request_id": v["distribution_request_id"],
        "committee_member_id": v["committee_member_id"],
        "vote": v["vote"],
        "created_at": v["created_at"],
    }


def policy_json(p):
    return {
        "id": p["id"],
        "trust_id": p["trust_id"],
        "effective_from": p["effective_from"],
        "effective_to": p["effective_to"],
        "equity_target_pct": p["equity_target_pct"],
        "equity_band_pct": p["equity_band_pct"],
        "fixed_income_target_pct": p["fixed_income_target_pct"],
        "fixed_income_band_pct": p["fixed_income_band_pct"],
        "alternatives_allowed": p["alternatives_allowed"],
        "status": p["status"],
        "activated_at": p["activated_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def holding_json(h):
    return {
        "id": h["id"],
        "trust_id": h["trust_id"],
        "asset_class": h["asset_class"],
        "ticker": h["ticker"],
        "units": h["units"],
        "unit_price_cents": h["unit_price_cents"],
        "market_value_cents": h["units"] * h["unit_price_cents"],
        "cost_basis_cents": h["cost_basis_cents"],
        "priced_at": h["priced_at"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def review_json(r):
    return {
        "id": r["id"],
        "trust_id": r["trust_id"],
        "investment_policy_statement_id": r["investment_policy_statement_id"],
        "asset_class": r["asset_class"],
        "direction": r["direction"],
        "measured_weight_pct": r["measured_weight_pct"],
        "band_limit_pct": r["band_limit_pct"],
        "severity": r["severity"],
        "status": r["status"],
        "remediation_note": r["remediation_note"],
        "resolved_at": r["resolved_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ledger_entry_json(e):
    return {
        "id": e["id"],
        "trust_id": e["trust_id"],
        "entry_kind": e["entry_kind"],
        "bucket": e["bucket"],
        "amount_cents": e["amount_cents"],
        "receipt_type": e["receipt_type"],
        "value_date": e["value_date"],
        "description": e["description"],
        "source_entity_type": e["source_entity_type"],
        "source_entity_id": e["source_entity_id"],
        "created_at": e["created_at"],
    }


def fee_assessment_json(f):
    return {
        "id": f["id"],
        "trust_id": f["trust_id"],
        "period_start": f["period_start"],
        "period_end": f["period_end"],
        "variant": f["variant"],
        "base_market_value_cents": f["base_market_value_cents"],
        "annual_fee_cents": f["annual_fee_cents"],
        "assessed_fee_cents": f["assessed_fee_cents"],
        "income_portion_cents": f["income_portion_cents"],
        "principal_portion_cents": f["principal_portion_cents"],
        "status": f["status"],
        "calculated_by_user_id": f["calculated_by_user_id"],
        "disclosed_by_user_id": f["disclosed_by_user_id"],
        "posted_by_user_id": f["posted_by_user_id"],
        "disclosed_at": f["disclosed_at"],
        "dispute_reason": f["dispute_reason"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def statement_json(s):
    return {
        "id": s["id"],
        "trust_id": s["trust_id"],
        "fiscal_year": s["fiscal_year"],
        "opening_income_cents": s["opening_income_cents"],
        "opening_principal_cents": s["opening_principal_cents"],
        "receipts_income_cents": s["receipts_income_cents"],
        "receipts_principal_cents": s["receipts_principal_cents"],
        "disbursements_cents": s["disbursements_cents"],
        "fees_cents": s["fees_cents"],
        "distributions_cents": s["distributions_cents"],
        "closing_income_cents": s["closing_income_cents"],
        "closing_principal_cents": s["closing_principal_cents"],
        "status": s["status"],
        "delivered_at": s["delivered_at"],
        "acknowledged_at": s["acknowledged_at"],
        "dispute_reason": s["dispute_reason"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def filing_json(f):
    return {
        "id": f["id"],
        "trust_id": f["trust_id"],
        "tax_year": f["tax_year"],
        "tentative_dni_cents": f["tentative_dni_cents"],
        "dni_cents": f["dni_cents"],
        "elected_65day_amount_cents": f["elected_65day_amount_cents"],
        "distribution_deduction_cents": f["distribution_deduction_cents"],
        "exemption_cents": f["exemption_cents"],
        "trust_taxable_income_cents": f["trust_taxable_income_cents"],
        "status": f["status"],
        "prepared_by_user_id": f["prepared_by_user_id"],
        "reviewed_by_user_id": f["reviewed_by_user_id"],
        "amendment_number": f["amendment_number"],
        "filed_at": f["filed_at"],
        "accepted_at": f["accepted_at"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def termination_case_json(c):
    return {
        "id": c["id"],
        "trust_id": c["trust_id"],
        "status": c["status"],
        "reason": c["reason"],
        "initiated_by_user_id": c["initiated_by_user_id"],
        "reserve_taxes_cents": c["reserve_taxes_cents"],
        "reserve_fees_cents": c["reserve_fees_cents"],
        "distributable_income_cents": c["distributable_income_cents"],
        "distributable_principal_cents": c["distributable_principal_cents"],
        "distribution_lines": c["distribution_lines"],
        "approved_by_user_id": c["approved_by_user_id"],
        "distributed_at": c["distributed_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
