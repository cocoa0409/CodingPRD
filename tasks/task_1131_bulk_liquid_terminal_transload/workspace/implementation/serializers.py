"""Entity serializers. Output field values are rendered as JSON-safe values;
datetimes are ISO 8601 UTC with three fractional digits, decimals as floats."""
from decimal import Decimal

from clock import iso_z


def _ts(dt):
    return iso_z(dt) if dt is not None else None


def _num(value):
    """Render numeric stored values (int / Decimal / float) as JSON numbers.
    Whole-barrel Decimals become ints; fractional Decimals become floats."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def customer_view(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "contact_email": c["contact_email"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def tank_view(t):
    return {
        "id": t["id"],
        "tank_code": t["tank_code"],
        "product_grade": t["product_grade"],
        "capacity_bbl": _num(t["capacity_bbl"]),
        "safe_fill_pct": _num(t["safe_fill_pct"]),
        "heel_bbl": _num(t["heel_bbl"]),
        "vapor_control_class": t["vapor_control_class"],
        "working_capacity_bbl": _num(t["working_capacity_bbl"]),
        "current_inventory_bbl": _num(t["current_inventory_bbl"]),
        "provisional_inventory_bbl": _num(t["provisional_inventory_bbl"]),
        "status": t["status"],
        "created_at": _ts(t["created_at"]),
        "updated_at": _ts(t["updated_at"]),
        "version": t["version"],
    }


def resource_view(r):
    return {
        "id": r["id"],
        "resource_code": r["resource_code"],
        "resource_type": r["resource_type"],
        "concurrent_capacity": r["concurrent_capacity"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def lease_view(l):
    return {
        "id": l["id"],
        "customer_id": l["customer_id"],
        "product_grade": l["product_grade"],
        "committed_capacity_bbl": _num(l["committed_capacity_bbl"]),
        "min_monthly_throughput_bbl": _num(l["min_monthly_throughput_bbl"]),
        "throughput_fee_per_bbl": _num(l["throughput_fee_per_bbl"]),
        "shortfall_fee_per_bbl": _num(l["shortfall_fee_per_bbl"]),
        "loss_allowance_pct": _num(l["loss_allowance_pct"]),
        "excess_loss_rate_per_bbl": _num(l["excess_loss_rate_per_bbl"]),
        "start_date": l["start_date"],
        "end_date": l["end_date"],
        "reserved_capacity_bbl": _num(l["reserved_capacity_bbl"]),
        "suspension_reason": l["suspension_reason"],
        "status": l["status"],
        "created_at": _ts(l["created_at"]),
        "updated_at": _ts(l["updated_at"]),
        "version": l["version"],
    }


def amendment_view(a):
    return {
        "id": a["id"],
        "lease_id": a["lease_id"],
        "proposed_committed_capacity_bbl": _num(a.get("proposed_committed_capacity_bbl")),
        "proposed_throughput_fee_per_bbl": _num(a.get("proposed_throughput_fee_per_bbl")),
        "proposed_min_monthly_throughput_bbl": _num(a.get("proposed_min_monthly_throughput_bbl")),
        "base_lease_version": a["base_lease_version"],
        "status": a["status"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def allocation_view(a):
    return {
        "id": a["id"],
        "lease_id": a["lease_id"],
        "tank_id": a["tank_id"],
        "allocated_bbl": _num(a["allocated_bbl"]),
        "period_start": a["period_start"],
        "period_end": a["period_end"],
        "status": a["status"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def permit_view(p):
    return {
        "id": p["id"],
        "permit_type": p["permit_type"],
        "tank_id": p["tank_id"],
        "valid_from": _ts(p["valid_from"]),
        "valid_until": _ts(p["valid_until"]),
        "status": p["status"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def movement_view(m):
    return {
        "id": m["id"],
        "sequence_no": m["sequence_no"],
        "lease_id": m["lease_id"],
        "tank_id": m["tank_id"],
        "resource_id": m["resource_id"],
        "direction": m["direction"],
        "mode": m["mode"],
        "product_grade": m["product_grade"],
        "declared_volume_bbl": _num(m["declared_volume_bbl"]),
        "window_start": _ts(m["window_start"]),
        "window_end": _ts(m["window_end"]),
        "actual_arrival_at": _ts(m["actual_arrival_at"]),
        "actual_start_at": _ts(m["actual_start_at"]),
        "actual_complete_at": _ts(m["actual_complete_at"]),
        "demurrage_estimated_amount": _num(m["demurrage_estimated_amount"]),
        "demurrage_actual_amount": _num(m["demurrage_actual_amount"]),
        "status": m["status"],
        "billing_status": m["billing_status"],
        "created_at": _ts(m["created_at"]),
        "updated_at": _ts(m["updated_at"]),
        "version": m["version"],
    }


def gauge_ticket_view(g):
    return {
        "id": g["id"],
        "movement_id": g["movement_id"],
        "ticket_type": g["ticket_type"],
        "observed_volume_bbl": _num(g["observed_volume_bbl"]),
        "observed_temp_f": _num(g["observed_temp_f"]),
        "observed_at": _ts(g["observed_at"]),
        "recorded_by_user_id": g["recorded_by_user_id"],
        "created_at": _ts(g["created_at"]),
    }


def sample_view(s):
    return {
        "id": s["id"],
        "movement_id": s["movement_id"],
        "sample_type": s["sample_type"],
        "collected_by_user_id": s["collected_by_user_id"],
        "lab_result": s["lab_result"],
        "specific_gravity": _num(s["specific_gravity"]),
        "result_recorded_by_user_id": s["result_recorded_by_user_id"],
        "retain_until": _ts(s["retain_until"]),
        "retain_status": s["retain_status"],
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }


def custody_transfer_view(ct):
    return {
        "id": ct["id"],
        "movement_id": ct["movement_id"],
        "provisional_volume_bbl": _num(ct["provisional_volume_bbl"]),
        "certified_volume_bbl": _num(ct["certified_volume_bbl"]),
        "shrinkage_bbl": _num(ct["shrinkage_bbl"]),
        "allowed_loss_bbl": _num(ct["allowed_loss_bbl"]),
        "excess_loss_bbl": _num(ct["excess_loss_bbl"]),
        "excess_loss_charge": _num(ct["excess_loss_charge"]),
        "certified_by_user_id": ct["certified_by_user_id"],
        "status": ct["status"],
        "created_at": _ts(ct["created_at"]),
        "updated_at": _ts(ct["updated_at"]),
        "version": ct["version"],
    }


def statement_view(s):
    return {
        "id": s["id"],
        "lease_id": s["lease_id"],
        "period": s["period"],
        "period_start": _ts(s["period_start"]),
        "period_end_exclusive": _ts(s["period_end_exclusive"]),
        "total_throughput_bbl": _num(s["total_throughput_bbl"]),
        "throughput_fee_amount": _num(s["throughput_fee_amount"]),
        "shortfall_bbl": _num(s["shortfall_bbl"]),
        "shortfall_fee_amount": _num(s["shortfall_fee_amount"]),
        "total_excess_loss_bbl": _num(s["total_excess_loss_bbl"]),
        "excess_loss_amount": _num(s["excess_loss_amount"]),
        "total_demurrage_amount": _num(s["total_demurrage_amount"]),
        "total_dwell_amount": _num(s["total_dwell_amount"]),
        "statement_total_amount": _num(s["statement_total_amount"]),
        "status": s["status"],
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }
