"""Entity -> wire-dict serializers.

Common fields (PRD §2.4): id, created_at, updated_at, version for normal
resources; immutable resources (CalibrationRecord, MonthlySettlement) carry
only id and created_at.
"""
from __future__ import annotations

from db import isoformat


def _ts(dt):
    return isoformat(dt) if dt is not None else None


def _common(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": _ts(e["created_at"]),
        "updated_at": _ts(e["updated_at"]),
        "version": e["version"],
    }


def _immutable(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": _ts(e["created_at"]),
    }


def station_out(s: dict) -> dict:
    d = _common(s)
    d.update({
        "station_name": s["station_name"],
        "station_code": s["station_code"],
        "access_mode": s["access_mode"],
        "backup_capacity_gge": s["backup_capacity_gge"],
        "uptime_posture": s["uptime_posture"],
        "status": s["status"],
    })
    return d


def compressor_out(c: dict) -> dict:
    d = _common(c)
    d.update({
        "station_id": c["station_id"],
        "compressor_code": c["compressor_code"],
        "capacity_scf_per_minute": c["capacity_scf_per_minute"],
        "condition": c["condition"],
    })
    return d


def dispenser_out(dsp: dict) -> dict:
    d = _common(dsp)
    d.update({
        "station_id": dsp["station_id"],
        "dispenser_code": dsp["dispenser_code"],
        "fuel_type": dsp["fuel_type"],
        "status": dsp["status"],
        "correction_factor": float(dsp["correction_factor"]),
        "last_calibration_at": _ts(dsp["last_calibration_at"]),
        "calibration_due_at": _ts(dsp["calibration_due_at"]),
    })
    return d


def calibration_record_out(r: dict) -> dict:
    d = _immutable(r)
    acf = r["applied_correction_factor"]
    d.update({
        "dispenser_id": r["dispenser_id"],
        "measured_error_pct": float(r["measured_error_pct"]),
        "result": r["result"],
        "applied_correction_factor": float(acf) if acf is not None else None,
        "performed_at": _ts(r["performed_at"]),
    })
    return d


def pricing_policy_out(p: dict) -> dict:
    d = _common(p)
    d.update({
        "station_id": p["station_id"],
        "access_scope": p["access_scope"],
        "fuel_type": p["fuel_type"],
        "price_per_gge_cents": p["price_per_gge_cents"],
        "tier_threshold_gge": float(p["tier_threshold_gge"]) if p["tier_threshold_gge"] is not None else None,
        "tier_price_cents": p["tier_price_cents"],
        "effective_from": _ts(p["effective_from"]),
        "effective_to": _ts(p["effective_to"]),
        "status": p["status"],
    })
    return d


def fleet_account_out(a: dict) -> dict:
    d = _common(a)
    d.update({
        "account_name": a["account_name"],
        "billing_email": a["billing_email"],
        "credit_limit_cents": a["credit_limit_cents"],
        "outstanding_balance_cents": a["outstanding_balance_cents"],
        "status": a["status"],
    })
    return d


def fleet_card_out(c: dict) -> dict:
    d = _common(c)
    d.update({
        "fleet_account_id": c["fleet_account_id"],
        "card_number": c["card_number"],
        "vehicle_plate": c["vehicle_plate"],
        "daily_gge_limit": float(c["daily_gge_limit"]),
        "status": c["status"],
        "current_day_gge": float(c["current_day_gge"]),
        "current_day_date": c["current_day_date"],
    })
    return d


def supply_contract_out(c: dict) -> dict:
    d = _common(c)
    d.update({
        "fleet_account_id": c["fleet_account_id"],
        "station_id": c["station_id"],
        "committed_monthly_gge": float(c["committed_monthly_gge"]),
        "contract_price_per_gge_cents": c["contract_price_per_gge_cents"],
        "shortfall_tier1_rate_cents": c["shortfall_tier1_rate_cents"],
        "shortfall_tier2_rate_cents": c["shortfall_tier2_rate_cents"],
        "start_month": c["start_month"],
        "end_month": c["end_month"],
        "status": c["status"],
    })
    return d


def monthly_settlement_out(s: dict) -> dict:
    d = _immutable(s)
    d.update({
        "supply_contract_id": s["supply_contract_id"],
        "month": s["month"],
        "delivered_gge": float(s["delivered_gge"]),
        "shortfall_gge": float(s["shortfall_gge"]),
        "penalty_cents": s["penalty_cents"],
        "settled_at": _ts(s["settled_at"]),
    })
    return d


def fueling_session_out(s: dict) -> dict:
    d = _common(s)
    d.update({
        "access_type": s["access_type"],
        "station_id": s["station_id"],
        "dispenser_id": s["dispenser_id"],
        "fleet_card_id": s["fleet_card_id"],
        "fleet_account_id": s["fleet_account_id"],
        "client_ref": s["client_ref"],
        "estimated_gge": float(s["estimated_gge"]),
        "unit_price_cents": s["unit_price_cents"],
        "hold_amount_cents": s["hold_amount_cents"],
        "metered_mass_kg": float(s["metered_mass_kg"]) if s["metered_mass_kg"] is not None else None,
        "correction_factor_applied": float(s["correction_factor_applied"]) if s["correction_factor_applied"] is not None else None,
        "provisional_gge": float(s["provisional_gge"]) if s["provisional_gge"] is not None else None,
        "settled_gge": float(s["settled_gge"]) if s["settled_gge"] is not None else None,
        "total_amount_cents": s["total_amount_cents"],
        "status": s["status"],
        "void_reason": s["void_reason"],
        "authorized_at": _ts(s["authorized_at"]),
        "completed_at": _ts(s["completed_at"]),
        "voided_at": _ts(s["voided_at"]),
        "settled_at": _ts(s["settled_at"]),
    })
    return d


def maintenance_window_out(w: dict) -> dict:
    d = _common(w)
    d.update({
        "station_id": w["station_id"],
        "compressor_id": w["compressor_id"],
        "starts_at": _ts(w["starts_at"]),
        "ends_at": _ts(w["ends_at"]),
        "window_type": w["window_type"],
        "status": w["status"],
    })
    return d


def backup_arrangement_out(b: dict) -> dict:
    d = _common(b)
    d.update({
        "station_id": b["station_id"],
        "partner_station_code": b["partner_station_code"],
        "available_from": _ts(b["available_from"]),
        "available_until": _ts(b["available_until"]),
        "committed_gge": b["committed_gge"],
        "used_gge": float(b["used_gge"]),
        "status": b["status"],
    })
    return d


def safety_inspection_out(i: dict) -> dict:
    d = _common(i)
    d.update({
        "station_id": i["station_id"],
        "inspection_type": i["inspection_type"],
        "scheduled_for": _ts(i["scheduled_for"]),
        "status": i["status"],
        "result": i["result"],
        "findings": i["findings"],
        "performed_by": i["performed_by"],
        "approved_by": i["approved_by"],
        "completed_at": _ts(i["completed_at"]),
    })
    return d


def tax_credit_claim_out(c: dict) -> dict:
    d = _common(c)
    d.update({
        "station_id": c["station_id"],
        "period_start": _ts(c["period_start"]),
        "period_end": _ts(c["period_end"]),
        "status": c["status"],
        "eligible_gge_provisional": float(c["eligible_gge_provisional"]) if c["eligible_gge_provisional"] is not None else None,
        "claim_amount_provisional_cents": c["claim_amount_provisional_cents"],
        "eligible_gge_final": float(c["eligible_gge_final"]) if c["eligible_gge_final"] is not None else None,
        "claim_amount_final_cents": c["claim_amount_final_cents"],
        "decision_reason": c["decision_reason"],
    })
    return d
