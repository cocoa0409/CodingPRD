"""Public serializers — convert internal records into the JSON shape returned
in `data`. Computed fields (allocated_total_kw, active_session_count,
receivable_balance_cents, line_item_count, total_amount_cents,
energy_delivered_kwh, etc.) are recomputed/refreshed at read time where the
PRD says they are exposed.

Numeric kW values are surfaced as floats with 1-decimal precision; kWh with
3-decimal precision; all monetary amounts are integer cents.
"""
from decimal import Decimal

import db
import services.site as site_svc
import services.session as session_svc


def _num(d):
    """Render a Decimal as a JSON number, dropping trailing zeros but keeping value."""
    if isinstance(d, Decimal):
        f = float(d)
        # normalize -0.0 to 0.0
        return 0.0 if f == 0 else f
    return d


def site(s):
    site_svc.recompute_site_aggregates(s)
    return {
        "id": s["id"],
        "name": s["name"],
        "circuit_limit_kw": _num(s["circuit_limit_kw"]),
        "allocation_policy": s["allocation_policy"],
        "demand_charge_threshold_kw": _num(s["demand_charge_threshold_kw"]),
        "demand_avoidance_armed": s["demand_avoidance_armed"],
        "allocated_total_kw": _num(s["allocated_total_kw"]),
        "active_session_count": s["active_session_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def stall(s):
    return {
        "id": s["id"],
        "site_id": s["site_id"],
        "connector_type": s["connector_type"],
        "max_power_kw": _num(s["max_power_kw"]),
        "ocpp_status": s["ocpp_status"],
        "reservation_priority": s["reservation_priority"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def driver(d):
    return {
        "id": d["id"],
        "email": d["email"],
        "full_name": d["full_name"],
        "home_emsp_id": d["home_emsp_id"],
        "wallet_balance_cents": d["wallet_balance_cents"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def emsp(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "commission_pct": _num(e["commission_pct"]),
        "receivable_balance_cents": e["receivable_balance_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def tariff(t):
    return {
        "id": t["id"],
        "site_id": t["site_id"],
        "connector_type": t["connector_type"],
        "pricing_mode": t["pricing_mode"],
        "session_fee_cents": t["session_fee_cents"],
        "energy_tier_1_max_kwh": _num(t["energy_tier_1_max_kwh"]),
        "energy_tier_2_max_kwh": _num(t["energy_tier_2_max_kwh"]),
        "energy_rate_t1_cents": t["energy_rate_t1_cents"],
        "energy_rate_t2_cents": t["energy_rate_t2_cents"],
        "energy_rate_t3_cents": t["energy_rate_t3_cents"],
        "time_rate_cents_per_min": t["time_rate_cents_per_min"],
        "idle_grace_minutes": t["idle_grace_minutes"],
        "idle_fee_cents_per_min": t["idle_fee_cents_per_min"],
        "effective_from": t["effective_from"],
        "effective_to": t["effective_to"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def reservation(r):
    return {
        "id": r["id"],
        "stall_id": r["stall_id"],
        "driver_id": r["driver_id"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
        "hold_fee_cents": r["hold_fee_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def session(s):
    return {
        "id": s["id"],
        "stall_id": s["stall_id"],
        "driver_id": s["driver_id"],
        "tariff_id": s["tariff_id"],
        "reservation_id": s["reservation_id"],
        "emsp_id": s["emsp_id"],
        "is_roaming": s["is_roaming"],
        "charging_status": s["charging_status"],
        "billing_status": s["billing_status"],
        "energy_delivered_kwh": _num(s["energy_delivered_kwh"]),
        "charging_minutes": s["charging_minutes"],
        "idle_minutes": s["idle_minutes"],
        "allocated_power_kw": _num(s["allocated_power_kw"]),
        "total_cost_cents": s["total_cost_cents"],
        "idle_fee_cents": s["idle_fee_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def meter_event(m):
    # MeterEvent is immutable: only id + created_at common fields (PRD §2.4).
    return {
        "id": m["id"],
        "session_id": m["session_id"],
        "meter_kwh": _num(m["meter_kwh"]),
        "sampled_at": m["sampled_at"],
        "reading_context": m["reading_context"],
        "created_at": m["created_at"],
    }


def batch(b):
    return {
        "id": b["id"],
        "emsp_id": b["emsp_id"],
        "status": b["status"],
        "line_item_count": b["line_item_count"],
        "total_amount_cents": b["total_amount_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def line_item(li):
    return {
        "id": li["id"],
        "batch_id": li["batch_id"],
        "session_id": li["session_id"],
        "gross_amount_cents": li["gross_amount_cents"],
        "commission_cents": li["commission_cents"],
        "net_amount_cents": li["net_amount_cents"],
        "status": li["status"],
        "created_at": li["created_at"],
        "updated_at": li["updated_at"],
        "version": li["version"],
    }


def load_allocation(la):
    return {
        "id": la["id"],
        "site_id": la["site_id"],
        "trigger_reason": la["trigger_reason"],
        "policy_used": la["policy_used"],
        "cap_kw": _num(la["cap_kw"]),
        "allocated_total_kw": _num(la["allocated_total_kw"]),
        "session_count": la["session_count"],
        "created_at": la["created_at"],
        "updated_at": la["updated_at"],
        "version": la["version"],
    }
