"""Wire-format serialisers — convert internal entity dicts to API JSON shapes.

Common-fields entities (Borrower, Property, SeniorLien, Heloc) carry
id, created_at, updated_at, version (PRD §2.4).  Immutable ledger and
audit entities (Draw, Payment, RateReset, Fee, DefaultEvent,
InsuranceEvent, SeniorLienDefaultEvent, BankruptcyEvent) carry only
id + created_at — no updated_at, no version (PRD §2.4, second paragraph).
"""
from __future__ import annotations

from datetime import datetime

from utils import iso_now


def _ts(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return iso_now(v)
    return v


# ── Top-level entities (carry version + updated_at) ────────────────────────


def borrower_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "full_name": b["full_name"],
        "email": b["email"],
        "bankruptcy_flag": b["bankruptcy_flag"],
        "bankruptcy_filed_at": _ts(b.get("bankruptcy_filed_at")),
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def property_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "borrower_id": p["borrower_id"],
        "address": p["address"],
        "appraised_value_cents": p["appraised_value_cents"],
        "occupancy": p["occupancy"],
        "insurance_status": p["insurance_status"],
        "insurance_lapsed_at": _ts(p.get("insurance_lapsed_at")),
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def senior_lien_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "property_id": s["property_id"],
        "holder_name": s["holder_name"],
        "principal_balance_cents": s["principal_balance_cents"],
        "status": s["status"],
        "defaulted_at": _ts(s.get("defaulted_at")),
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }


def heloc_view(h: dict, *, include_computed: bool = False) -> dict:
    out = {
        "id": h["id"],
        "borrower_id": h["borrower_id"],
        "property_id": h["property_id"],
        "credit_limit_cents": h["credit_limit_cents"],
        "margin_bps": h["margin_bps"],
        "periodic_cap_bps": h["periodic_cap_bps"],
        "lifetime_cap_bps": h["lifetime_cap_bps"],
        "lifetime_floor_bps": h["lifetime_floor_bps"],
        "initial_rate_bps": h.get("initial_rate_bps"),
        "current_rate_bps": h.get("current_rate_bps"),
        "origination_date": _ts(h.get("origination_date")),
        "draw_period_end_date": _ts(h.get("draw_period_end_date")),
        "repayment_period_end_date": _ts(h.get("repayment_period_end_date")),
        "repayment_term_years": h["repayment_term_years"],
        "principal_balance_cents": h["principal_balance_cents"],
        "available_credit_cents": h.get("available_credit_cents"),
        "accrued_interest_cents": h["accrued_interest_cents"],
        "status": h["status"],
        "delinquency_days": h["delinquency_days"],
        "annual_fee_cents": h["annual_fee_cents"],
        "annual_fee_waived_first_year": h["annual_fee_waived_first_year"],
        "early_closure_fee_cents": h["early_closure_fee_cents"],
        "defaulted_at": _ts(h.get("defaulted_at")),
        "default_trigger": h.get("default_trigger"),
        "closed_at": _ts(h.get("closed_at")),
        "created_at": _ts(h["created_at"]),
        "updated_at": _ts(h["updated_at"]),
        "version": h["version"],
    }
    if include_computed:
        # The PRD §3.10 says the single-HELOC read includes
        # minimum_payment_due_cents, available_credit_cents (already
        # included above), and current_rate_bps (also included).
        # Import locally to avoid a circular import at module load.
        from services.engine import minimum_payment_due_cents
        out["minimum_payment_due_cents"] = minimum_payment_due_cents(h)
    return out


# ── Ledger / immutable entities ────────────────────────────────────────────


def draw_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "heloc_id": d["heloc_id"],
        "amount_cents": d["amount_cents"],
        "drawn_at": _ts(d["drawn_at"]),
        "created_at": _ts(d["created_at"]),
    }


def payment_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "heloc_id": p["heloc_id"],
        "amount_cents": p["amount_cents"],
        "interest_component_cents": p["interest_component_cents"],
        "principal_component_cents": p["principal_component_cents"],
        "posted_at": _ts(p["posted_at"]),
        "created_at": _ts(p["created_at"]),
    }


def rate_reset_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "heloc_id": r["heloc_id"],
        "prime_rate_bps": r["prime_rate_bps"],
        "requested_rate_bps": r["requested_rate_bps"],
        "applied_rate_bps": r["applied_rate_bps"],
        "reset_at": _ts(r["reset_at"]),
        "created_at": _ts(r["created_at"]),
    }


def fee_view(f: dict) -> dict:
    return {
        "id": f["id"],
        "heloc_id": f["heloc_id"],
        "fee_type": f["fee_type"],
        "amount_cents": f["amount_cents"],
        "status": f["status"],
        "assessed_at": _ts(f["assessed_at"]),
        "created_at": _ts(f["created_at"]),
    }


def default_event_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "heloc_id": e["heloc_id"],
        "trigger": e["trigger"],
        "source_event_id": e.get("source_event_id"),
        "recorded_at": _ts(e["recorded_at"]),
        "created_at": _ts(e["created_at"]),
    }


def insurance_event_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "event_type": e["event_type"],
        "recorded_at": _ts(e["recorded_at"]),
        "created_at": _ts(e["created_at"]),
    }


def senior_lien_default_event_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "senior_lien_id": e["senior_lien_id"],
        "recorded_at": _ts(e["recorded_at"]),
        "created_at": _ts(e["created_at"]),
    }


def bankruptcy_event_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "borrower_id": e["borrower_id"],
        "recorded_at": _ts(e["recorded_at"]),
        "created_at": _ts(e["created_at"]),
    }
