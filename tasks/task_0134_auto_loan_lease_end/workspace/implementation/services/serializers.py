"""Entity serializers — emit the JSON shape returned by the API.

Each serializer returns a plain dict; the response layer wraps it with the
standard envelope (see response.py).
"""
from __future__ import annotations

from utils import iso_now


def _iso(dt):
    return iso_now(dt) if dt is not None else None


def serialize_customer(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "fico_score": c["fico_score"],
        "fico_tier": c["fico_tier"],
        "default_count": c["default_count"],
        "default_rate": c["default_rate"],
        "lifetime_payment_count": c["lifetime_payment_count"],
        "status": c["status"],
        "clock_day_index": c["clock_day_index"],
        "created_at": _iso(c["created_at"]),
        "updated_at": _iso(c["updated_at"]),
        "version": c["version"],
    }


def serialize_vehicle(v: dict) -> dict:
    return {
        "id": v["id"],
        "vin": v["vin"],
        "model": v["model"],
        "msrp_cents": v["msrp_cents"],
        "residual_factor_bps": v["residual_factor_bps"],
        "status": v["status"],
        "created_at": _iso(v["created_at"]),
        "updated_at": _iso(v["updated_at"]),
        "version": v["version"],
    }


def serialize_loan_contract(lc: dict) -> dict:
    return {
        "id": lc["id"],
        "customer_id": lc["customer_id"],
        "vehicle_id": lc["vehicle_id"],
        "principal_cents": lc["principal_cents"],
        "down_payment_cents": lc["down_payment_cents"],
        "term_months": lc["term_months"],
        "apr_bps": lc.get("apr_bps"),
        "base_apr_bps": lc.get("base_apr_bps"),
        "monthly_payment_cents": lc.get("monthly_payment_cents"),
        "remaining_principal_cents": lc.get("remaining_principal_cents"),
        "total_principal_paid_cents": lc.get("total_principal_paid_cents", 0),
        "total_interest_paid_cents": lc.get("total_interest_paid_cents", 0),
        "payments_made_count": lc.get("payments_made_count", 0),
        "payments_scheduled_count": lc.get("payments_scheduled_count"),
        "status": lc["status"],
        "origination_day_index": lc.get("origination_day_index"),
        "created_at": _iso(lc["created_at"]),
        "updated_at": _iso(lc["updated_at"]),
        "version": lc["version"],
    }


def serialize_lease_contract(lc: dict) -> dict:
    return {
        "id": lc["id"],
        "customer_id": lc["customer_id"],
        "vehicle_id": lc["vehicle_id"],
        "capitalized_cost_cents": lc["capitalized_cost_cents"],
        "down_payment_cents": lc["down_payment_cents"],
        "term_months": lc["term_months"],
        "mileage_allowance": lc["mileage_allowance"],
        "money_factor_micro": lc.get("money_factor_micro"),
        "residual_value_cents": lc.get("residual_value_cents"),
        "monthly_payment_cents": lc.get("monthly_payment_cents"),
        "payments_made_count": lc.get("payments_made_count", 0),
        "payments_scheduled_count": lc.get("payments_scheduled_count"),
        "status": lc["status"],
        "lease_end_election": lc.get("lease_end_election"),
        "origination_day_index": lc.get("origination_day_index"),
        "maturity_day_index": lc.get("maturity_day_index"),
        "created_at": _iso(lc["created_at"]),
        "updated_at": _iso(lc["updated_at"]),
        "version": lc["version"],
    }


def serialize_payment(p: dict) -> dict:
    return {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "contract_id": p["contract_id"],
        "contract_type": p["contract_type"],
        "period_index": p["period_index"],
        "due_day_index": p["due_day_index"],
        "amount_due_cents": p["amount_due_cents"],
        "principal_portion_cents": p.get("principal_portion_cents"),
        "interest_portion_cents": p.get("interest_portion_cents"),
        "status": p["status"],
        "paid_day_index": p.get("paid_day_index"),
        "created_at": _iso(p["created_at"]),
    }


def serialize_gap_rider(g: dict) -> dict:
    return {
        "id": g["id"],
        "customer_id": g["customer_id"],
        "contract_id": g["contract_id"],
        "contract_type": g["contract_type"],
        "monthly_premium_cents": g["monthly_premium_cents"],
        "status": g["status"],
        "claim_payout_cents": g.get("claim_payout_cents", 0),
        "attached_day_index": g["attached_day_index"],
        "created_at": _iso(g["created_at"]),
        "updated_at": _iso(g["updated_at"]),
        "version": g["version"],
    }


def serialize_assessment(a: dict) -> dict:
    return {
        "id": a["id"],
        "lease_contract_id": a["lease_contract_id"],
        "customer_id": a["customer_id"],
        "odometer_reading": a.get("odometer_reading"),
        "mileage_overage": a.get("mileage_overage", 0),
        "mileage_penalty_cents": a.get("mileage_penalty_cents", 0),
        "disposition_fee_cents": a.get("disposition_fee_cents", 0),
        "purchase_option_cents": a.get("purchase_option_cents", 0),
        "total_due_cents": a.get("total_due_cents", 0),
        "status": a["status"],
        "settled_day_index": a.get("settled_day_index"),
        "created_at": _iso(a["created_at"]),
        "updated_at": _iso(a["updated_at"]),
        "version": a["version"],
    }


def serialize_delinquency_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "customer_id": e["customer_id"],
        "payment_id": e["payment_id"],
        "default_count_after": e["default_count_after"],
        "apr_uplift_bps_applied": e["apr_uplift_bps_applied"],
        "affected_contract_ids": list(e["affected_contract_ids"]),
        "created_at": _iso(e["created_at"]),
    }


def serialize_clock_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "customer_id": e["customer_id"],
        "days_advanced": e["days_advanced"],
        "new_clock_day_index": e["new_clock_day_index"],
        "payments_due_now": e["payments_due_now"],
        "payments_defaulted_now": e["payments_defaulted_now"],
        "created_at": _iso(e["created_at"]),
    }
