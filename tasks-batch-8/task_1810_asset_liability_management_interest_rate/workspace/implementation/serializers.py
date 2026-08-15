"""Public resource projections (scaffold 1.1 entity fields, PRD 2.5 common
properties). Internal keys (``_seq``, ``_created_dt``) never leak."""

from services import run_assumption_stale


def book_json(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "base_curve_rate_bps": b["base_curve_rate_bps"],
        "min_hedged_notional_cents": b["min_hedged_notional_cents"],
        "status": b["status"],
        "total_assets_cents": b["total_assets_cents"],
        "total_liabilities_cents": b["total_liabilities_cents"],
        "hedged_notional_cents": b["hedged_notional_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def position_json(p):
    return {
        "id": p["id"],
        "book_id": p["book_id"],
        "category": p["category"],
        "deposit_segment": p["deposit_segment"],
        "balance_cents": p["balance_cents"],
        "rate_bps": p["rate_bps"],
        "scheduled_runoff_pct": p["scheduled_runoff_pct"],
        "is_prepayment_eligible": p["is_prepayment_eligible"],
        "duration_years": p["duration_years"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def assumption_set_json(a):
    return {
        "id": a["id"],
        "book_id": a["book_id"],
        "domain": a["domain"],
        "params": a["params"],
        "status": a["status"],
        "created_by_user_id": a["created_by_user_id"],
        "approved_by_user_id": a["approved_by_user_id"],
        "approved_at": a["approved_at"],
        "governance_flag": a["governance_flag"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def scenario_json(s):
    return {
        "id": s["id"],
        "book_id": s["book_id"],
        "name": s["name"],
        "kind": s["kind"],
        "shock_bps": s["shock_bps"],
        "ramp_total_bps": s["ramp_total_bps"],
        "ramp_months": s["ramp_months"],
        "preset_code": s["preset_code"],
        "horizon_months": s["horizon_months"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def run_json(r):
    return {
        "id": r["id"],
        "book_id": r["book_id"],
        "scenario_id": r["scenario_id"],
        "prepayment_set_id": r["prepayment_set_id"],
        "decay_set_id": r["decay_set_id"],
        "beta_set_id": r["beta_set_id"],
        "balance_sheet_convention": r["balance_sheet_convention"],
        "annual_growth_pct": r["annual_growth_pct"],
        "book_version_pinned": r["book_version_pinned"],
        "status": r["status"],
        "period_month": r["period_month"],
        "nii_base_cents": r["nii_base_cents"],
        "nii_scenario_cents": r["nii_scenario_cents"],
        "nii_delta_pct": r["nii_delta_pct"],
        "eve_base_cents": r["eve_base_cents"],
        "eve_scenario_cents": r["eve_scenario_cents"],
        "eve_delta_pct": r["eve_delta_pct"],
        "breach_summary": r["breach_summary"],
        "assumption_stale": run_assumption_stale(r),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def policy_limit_json(lim):
    return {
        "id": lim["id"],
        "book_id": lim["book_id"],
        "metric": lim["metric"],
        "applies_to_kinds": lim["applies_to_kinds"],
        "threshold_pct": lim["threshold_pct"],
        "status": lim["status"],
        "created_at": lim["created_at"],
        "updated_at": lim["updated_at"],
        "version": lim["version"],
    }


def breach_json(b):
    return {
        "id": b["id"],
        "book_id": b["book_id"],
        "run_id": b["run_id"],
        "limit_id": b["limit_id"],
        "metric": b["metric"],
        "observed_delta_pct": b["observed_delta_pct"],
        "threshold_pct": b["threshold_pct"],
        "period_month": b["period_month"],
        "status": b["status"],
        "remediation_note": b["remediation_note"],
        "due_date": b["due_date"],
        "resolution_note": b["resolution_note"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def hedge_json(h):
    return {
        "id": h["id"],
        "book_id": h["book_id"],
        "position_id": h["position_id"],
        "instrument": h["instrument"],
        "designation_type": h["designation_type"],
        "notional_cents": h["notional_cents"],
        "fixed_rate_bps": h["fixed_rate_bps"],
        "start_month": h["start_month"],
        "end_month": h["end_month"],
        "effectiveness_method": h["effectiveness_method"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def eff_test_json(t):
    # Append-only event record: id + created_at only, no updated_at/version.
    return {
        "id": t["id"],
        "hedge_id": t["hedge_id"],
        "test_month": t["test_month"],
        "method": t["method"],
        "hedge_value_change_cents": t["hedge_value_change_cents"],
        "hedged_item_value_change_cents": t["hedged_item_value_change_cents"],
        "slope": t["slope"],
        "r_squared": t["r_squared"],
        "sample_count": t["sample_count"],
        "offset_ratio": t["offset_ratio"],
        "result": t["result"],
        "created_at": t["created_at"],
    }


def backtest_json(r):
    return {
        "id": r["id"],
        "book_id": r["book_id"],
        "assumption_set_id": r["assumption_set_id"],
        "domain": r["domain"],
        "start_month": r["start_month"],
        "observation_months": r["observation_months"],
        "observed_value_pct": r["observed_value_pct"],
        "predicted_value_pct": r["predicted_value_pct"],
        "deviation_pct": r["deviation_pct"],
        "outcome": r["outcome"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def report_json(r):
    return {
        "id": r["id"],
        "book_id": r["book_id"],
        "period_month": r["period_month"],
        "status": r["status"],
        "run_count": r["run_count"],
        "worst_nii_delta_pct": r["worst_nii_delta_pct"],
        "worst_eve_delta_pct": r["worst_eve_delta_pct"],
        "open_breach_count": r["open_breach_count"],
        "regulatory_coverage_complete": r["regulatory_coverage_complete"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "acknowledged_by_user_id": r["acknowledged_by_user_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
