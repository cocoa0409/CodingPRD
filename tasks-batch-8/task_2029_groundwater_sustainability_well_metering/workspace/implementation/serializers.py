"""Entity serializers: Decimals -> JSON numbers, datetimes -> ISO strings."""
from util import iso_ts, num_out


def _common(e):
    return {
        "created_at": iso_ts(e["created_at"]),
        "updated_at": iso_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_account(a):
    out = {
        "id": a["id"],
        "holder_name": a["holder_name"],
        "account_type": a["account_type"],
        "base_allocation_af": num_out(a["base_allocation_af"]),
        "status": a["status"],
        "current_water_year": a["current_water_year"],
        "extracted_af_ytd": num_out(a["extracted_af_ytd"]),
        "pending_extraction_af": num_out(a["pending_extraction_af"]),
        "credit_balance_af": num_out(a["credit_balance_af"]),
        "transfer_out_af_ytd": num_out(a["transfer_out_af_ytd"]),
        "transfer_reserved_af": num_out(a["transfer_reserved_af"]),
        "penalty_balance_cents": a["penalty_balance_cents"],
    }
    out.update(_common(a))
    return out


def ser_well(w):
    out = {
        "id": w["id"],
        "account_id": w["account_id"],
        "well_type": w["well_type"],
        "location_description": w["location_description"],
        "minimum_threshold_ft": num_out(w["minimum_threshold_ft"]) if w["minimum_threshold_ft"] is not None else None,
        "meter_serial": w["meter_serial"],
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def ser_report(r):
    out = {
        "id": r["id"],
        "well_id": r["well_id"],
        "water_year": r["water_year"],
        "month": r["month"],
        "reported_af": num_out(r["reported_af"]),
        "late_flag": r["late_flag"],
        "fee_cents": r["fee_cents"],
        "amendment_count": r["amendment_count"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_transfer(t):
    out = {
        "id": t["id"],
        "seller_account_id": t["seller_account_id"],
        "buyer_account_id": t["buyer_account_id"],
        "quantity_af": num_out(t["quantity_af"]),
        "unit_price_cents": t["unit_price_cents"],
        "effective_start_date": t["start"].isoformat(),
        "effective_end_date": t["end"].isoformat(),
        "expires_at": iso_ts(t["expires_at"]),
        "settled_at": iso_ts(t["settled_at"]) if t["settled_at"] is not None else None,
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def ser_reading(r):
    # MonitoringReading is append-only: id + created_at, no updated_at/version.
    return {
        "id": r["id"],
        "well_id": r["well_id"],
        "measured_at": iso_ts(r["measured_at"]),
        "depth_to_water_ft": num_out(r["depth_to_water_ft"]),
        "collector_name": r["collector_name"],
        "created_at": iso_ts(r["created_at"]),
    }


def ser_snapshot(s):
    out = {
        "id": s["id"],
        "computed_at": iso_ts(s["computed_at"]),
        "eligible_well_count": s["eligible_well_count"],
        "breached_well_count": s["breached_well_count"],
        "breach_pct": num_out(s["breach_pct"]) if s["breach_pct"] is not None else None,
        "rolling_mean_depth_ft": num_out(s["rolling_mean_depth_ft"]) if s["rolling_mean_depth_ft"] is not None else None,
        "condition": s["condition"],
        "mean_condition": s["mean_condition"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_assessment(a):
    out = {
        "id": a["id"],
        "account_id": a["account_id"],
        "reason": a["reason"],
        "water_year": a["water_year"],
        "overdraft_af": num_out(a["overdraft_af"]) if a["overdraft_af"] is not None else None,
        "amount_cents": a["amount_cents"],
        "reduced_amount_cents": a["reduced_amount_cents"],
        "paid_amount_cents": a["paid_amount_cents"],
        "assessed_by": a["assessed_by"],
        "decided_by": a["decided_by"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def ser_annual(r):
    out = {
        "id": r["id"],
        "water_year": r["water_year"],
        "total_extracted_af": num_out(r["total_extracted_af"]),
        "verified_report_count": r["verified_report_count"],
        "overdraft_assessment_count": r["overdraft_assessment_count"],
        "penalties_assessed_cents": r["penalties_assessed_cents"],
        "penalties_collected_cents": r["penalties_collected_cents"],
        "total_pumping_fees_cents": r["total_pumping_fees_cents"],
        "final_basin_condition": r["final_basin_condition"],
        "avg_depth_ft": num_out(r["avg_depth_ft"]) if r["avg_depth_ft"] is not None else None,
        "status": r["status"],
    }
    out.update(_common(r))
    return out
