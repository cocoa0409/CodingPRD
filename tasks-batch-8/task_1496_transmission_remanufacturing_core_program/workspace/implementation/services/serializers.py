"""Entity -> wire-format serializers. Datetimes rendered with 3 fractional
digits per PRD §2.4. Computed fields resolved here."""

from validators import format_ts


def model_view(m):
    return {
        "id": m["id"],
        "model_code": m["model_code"],
        "year_start": m["year_start"],
        "year_end": m["year_end"],
        "make": m["make"],
        "model": m["model"],
        "core_deposit_cents": m["core_deposit_cents"],
        "flat_rate_hours": m["flat_rate_hours"],
        "labor_cap_cents": m["labor_cap_cents"],
        "warranty_days": m["warranty_days"],
        "dyno_targets": m["dyno_targets"],
        "required_parts": m["required_parts"],
        "spec_version": m["spec_version"],
        "created_at": format_ts(m["created_at"]),
        "updated_at": format_ts(m["updated_at"]),
        "version": m["version"],
    }


def part_view(p):
    return {
        "id": p["id"],
        "part_number": p["part_number"],
        "part_family": p["part_family"],
        "unit_cost_cents": p["unit_cost_cents"],
        "qty_on_hand": p["qty_on_hand"],
        "qty_reserved": p["qty_reserved"],
        "availability": p["qty_on_hand"] - p["qty_reserved"],
        "created_at": format_ts(p["created_at"]),
        "updated_at": format_ts(p["updated_at"]),
        "version": p["version"],
    }


def mapping_view(x):
    return {
        "id": x["id"],
        "hard_part_id": x["hard_part_id"],
        "transmission_model_id": x["transmission_model_id"],
        "tier": x["tier"],
        "created_at": format_ts(x["created_at"]),
    }


def order_view(o):
    return {
        "id": o["id"],
        "transmission_model_id": o["transmission_model_id"],
        "buyer_ref": o["buyer_ref"],
        "pinned_spec": o["pinned_spec"],
        "model_spec_version_pin": o["model_spec_version_pin"],
        "status": o["status"],
        "shortage_parts": o["shortage_parts"],
        "reserved_parts": o["reserved_parts"],
        "surcharge_labor_minutes": o["surcharge_labor_minutes"],
        "cal_status": o["cal_status"],
        "cal_generation": o["cal_generation"],
        "solenoid_trims": o["solenoid_trims"],
        "tcm_flash_version": o["tcm_flash_version"],
        "tcm_flash_version_applied": o["tcm_flash_version_applied"],
        "cal_created_by_id": o["cal_created_by_id"],
        "cal_created_at": format_ts(o["cal_created_at"]),
        "dyno_attempts_used": o["dyno_attempts_used"],
        "last_shift_quality_score": o["last_shift_quality_score"],
        "core_settlement_status": o["core_settlement_status"],
        "shipped_at": format_ts(o["shipped_at"]),
        "created_at": format_ts(o["created_at"]),
        "updated_at": format_ts(o["updated_at"]),
        "version": o["version"],
    }


def booking_view(b):
    return {
        "id": b["id"],
        "reman_order_id": b["reman_order_id"],
        "dyno_cell_code": b["dyno_cell_code"],
        "start_utc": format_ts(b["start_utc"]),
        "end_utc": format_ts(b["end_utc"]),
        "status": b["status"],
        "created_at": format_ts(b["created_at"]),
    }


def run_view(r):
    return {
        "id": r["id"],
        "reman_order_id": r["reman_order_id"],
        "dyno_booking_id": r["dyno_booking_id"],
        "attempt_number": r["attempt_number"],
        "gear_pressures_kpa": r["gear_pressures_kpa"],
        "shift_quality_score": r["shift_quality_score"],
        "verdict": r["verdict"],
        "created_at": format_ts(r["created_at"]),
    }


def core_view(c):
    return {
        "id": c["id"],
        "core_deposit_invoice_id": c["core_deposit_invoice_id"],
        "dock_code": c["dock_code"],
        "dock_start_utc": format_ts(c["dock_start_utc"]),
        "dock_end_utc": format_ts(c["dock_end_utc"]),
        "received_at": format_ts(c["received_at"]),
        "days_late": c["days_late"],
        "case_cracked": c["case_cracked"],
        "findings": c["findings"],
        "deduction_score": c["deduction_score"],
        "grade": c["grade"],
        "status": c["status"],
        "created_at": format_ts(c["created_at"]),
        "updated_at": format_ts(c["updated_at"]),
        "version": c["version"],
    }


def invoice_view(i):
    return {
        "id": i["id"],
        "reman_order_id": i["reman_order_id"],
        "buyer_ref": i["buyer_ref"],
        "deposit_cents": i["deposit_cents"],
        "issued_at": format_ts(i["issued_at"]),
        "provisional_credit_cents": i["provisional_credit_cents"],
        "final_credit_cents": i["final_credit_cents"],
        "forfeited_cents": i["forfeited_cents"],
        "status": i["status"],
        "created_at": format_ts(i["created_at"]),
        "updated_at": format_ts(i["updated_at"]),
        "version": i["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "reman_order_id": c["reman_order_id"],
        "installer_id": c["installer_id"],
        "failure_code": c["failure_code"],
        "claimed_labor_hours": c["claimed_labor_hours"],
        "installer_labor_rate_cents": c["installer_labor_rate_cents"],
        "allowance_policy": c["allowance_policy"],
        "labor_allowance_cents": c["labor_allowance_cents"],
        "routing_type": c["routing_type"],
        "return_required": c["return_required"],
        "claim_status": c["claim_status"],
        "return_status": c["return_status"],
        "deny_reason": c["deny_reason"],
        "salvaged_parts": c["salvaged_parts"],
        "created_at": format_ts(c["created_at"]),
        "updated_at": format_ts(c["updated_at"]),
        "version": c["version"],
    }
