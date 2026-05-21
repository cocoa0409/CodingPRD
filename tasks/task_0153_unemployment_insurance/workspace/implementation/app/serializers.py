"""Serialise stored entity dicts into API-shaped responses.

Each serializer returns a plain JSON-friendly dict that becomes the
`data` payload in a response envelope.
"""
from __future__ import annotations

from typing import Any, Dict


def _common(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Common fields: id, created_at, updated_at, version."""
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }


def serialize_claimant(c: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(c)
    out.update({
        "ssn_last4": c["ssn_last4"],
        "full_name": c["full_name"],
        "state_residence": c["state_residence"],
        "date_of_birth": c["date_of_birth"],
        "lifetime_overpayment_balance_cents": c.get("lifetime_overpayment_balance_cents", 0),
    })
    return out


def serialize_employer(e: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(e)
    out.update({
        "ein": e["ein"],
        "legal_name": e["legal_name"],
        "reserve_ratio_basis_cents": e["reserve_ratio_basis_cents"],
        "taxable_payroll_cents": e["taxable_payroll_cents"],
        "experience_rate_bps": e["experience_rate_bps"],
    })
    return out


def serialize_wage_record(w: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "claimant_id": w["claimant_id"],
        "employer_id": w["employer_id"],
        "quarter_year": w["quarter_year"],
        "quarter_index": w["quarter_index"],
        "wages_cents": w["wages_cents"],
    }


def serialize_claim(c: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(c)
    out.update({
        "claimant_id": c["claimant_id"],
        "filing_date": c.get("filing_date"),
        "benefit_year_start": c.get("benefit_year_start"),
        "benefit_year_end": c.get("benefit_year_end"),
        "base_period_variant": c.get("base_period_variant"),
        "base_period_total_wages_cents": c.get("base_period_total_wages_cents", 0),
        "high_quarter_wages_cents": c.get("high_quarter_wages_cents", 0),
        "weekly_benefit_amount_cents": c.get("weekly_benefit_amount_cents", 0),
        "max_weeks_of_eligibility": c.get("max_weeks_of_eligibility", 0),
        "status": c["status"],
        "weeks_paid": c.get("weeks_paid", 0),
        "weeks_remaining": c.get("weeks_remaining", 0),
        "pandemic_extension_weeks_granted": c.get("pandemic_extension_weeks_granted", 0),
        "extension_id": c.get("extension_id"),
        "assigned_adjudicator_id": c.get("assigned_adjudicator_id"),
        "decision_at": c.get("decision_at"),
    })
    return out


def serialize_certification(c: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(c)
    out.update({
        "claim_id": c["claim_id"],
        "week_ending_date": c["week_ending_date"],
        "status": c["status"],
        "earnings_reported_cents": c["earnings_reported_cents"],
        "able_and_available": c["able_and_available"],
        "work_search_count": c.get("work_search_count", 0),
        "payable_amount_cents": c.get("payable_amount_cents", 0),
        "payment_id": c.get("payment_id"),
    })
    return out


def serialize_work_search_entry(w: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "certification_id": w["certification_id"],
        "contact_date": w["contact_date"],
        "employer_name": w["employer_name"],
        "contact_method": w["contact_method"],
    }


def serialize_benefit_payment(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "claim_id": p["claim_id"],
        "certification_id": p["certification_id"],
        "amount_cents": p["amount_cents"],
        "issued_at": p["issued_at"],
        "status": p["status"],
        "reversed_reason": p.get("reversed_reason"),
    }


def serialize_overpayment(o: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(o)
    out.update({
        "claim_id": o["claim_id"],
        "certification_id": o.get("certification_id"),
        "principal_cents": o["principal_cents"],
        "balance_cents": o["balance_cents"],
        "classification": o["classification"],
        "status": o["status"],
    })
    return out


def serialize_appeal(a: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(a)
    out.update({
        "claim_id": a["claim_id"],
        "subject_type": a["subject_type"],
        "subject_id": a["subject_id"],
        "subject_locked_version": a["subject_locked_version"],
        "assigned_adjudicator_id": a.get("assigned_adjudicator_id"),
        "assigned_appeal_officer_id": a["assigned_appeal_officer_id"],
        "filed_at": a["filed_at"],
        "deadline_at": a["deadline_at"],
        "status": a["status"],
        "decision_at": a.get("decision_at"),
    })
    return out


def serialize_employer_charge(c: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(c)
    out.update({
        "employer_id": c["employer_id"],
        "claim_id": c["claim_id"],
        "payment_id": c["payment_id"],
        "charge_cents": c["charge_cents"],
        "status": c["status"],
    })
    return out


def serialize_pandemic_extension(p: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(p)
    out.update({
        "program_name": p["program_name"],
        "effective_start": p["effective_start"],
        "effective_end": p["effective_end"],
        "extra_weeks": p["extra_weeks"],
        "status": p["status"],
    })
    return out


def serialize_system_clock(now_iso: str) -> Dict[str, Any]:
    return {"now": now_iso}
