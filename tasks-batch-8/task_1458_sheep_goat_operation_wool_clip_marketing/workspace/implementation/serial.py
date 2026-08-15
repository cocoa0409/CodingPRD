"""Entity serializers: internal rows -> public JSON dicts with computed fields."""
import calc
import util


def _common(row):
    return {
        "id": row["id"],
        "created_at": util.ts_audit(row["created_at"]),
        "updated_at": util.ts_audit(row["updated_at"]),
        "version": row["version"],
    }


def flock_public(row):
    out = _common(row)
    out.update({
        "flock_name": row["flock_name"],
        "species": row["species"],
        "flock_status": row["flock_status"],
        "baseline_headcount": row["baseline_headcount"],
        "guardian_dog_count": row["guardian_dog_count"],
        "current_headcount": calc.flock_headcount(row["id"]),
        "withdrawal_until": util.ts_domain(calc.flock_withdrawal_until(row["id"])),
    })
    return out


def season_public(row):
    out = _common(row)
    total_born, total_alive, rate = calc.season_totals(row)
    out.update({
        "flock_id": row["flock_id"],
        "season_label": row["season_label"],
        "ewes_bred": row["ewes_bred"],
        "breeding_start_date": util.ts_domain(row["breeding_start_date"]),
        "breeding_end_date": util.ts_domain(row["breeding_end_date"]),
        "expected_lambing_start": util.ts_domain(row["expected_lambing_start"]),
        "season_status": row["season_status"],
        "total_born": total_born,
        "total_born_alive": total_alive,
        "lambing_rate_pct": util.num_out(rate),
    })
    return out


def birth_public(row):
    return {
        "id": row["id"],
        "season_id": row["season_id"],
        "birth_date": util.ts_domain(row["birth_date"]),
        "births_reported": row["births_reported"],
        "born_alive": row["born_alive"],
        "born_dead": row["born_dead"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "created_at": util.ts_audit(row["created_at"]),
    }


def pasture_public(row):
    out = _common(row)
    status, occupied = calc.pasture_status(row)
    out.update({
        "pasture_name": row["pasture_name"],
        "acres": util.num_out(row["acres"]),
        "carrying_capacity_head": row["carrying_capacity_head"],
        "rest_days": row["rest_days"],
        "occupied_head_count": occupied,
        "pasture_status": status,
    })
    return out


def move_public(row):
    out = _common(row)
    out.update({
        "flock_id": row["flock_id"],
        "pasture_id": row["pasture_id"],
        "contract_id": row["contract_id"],
        "move_start": util.ts_domain(row["move_start"]),
        "move_end": util.ts_domain(row["move_end"]),
        "head_count": row["head_count"],
        "move_status": row["move_status"],
    })
    return out


def treatment_public(row):
    out = _common(row)
    efficacy, resistance = calc.treatment_efficacy(row)
    out.update({
        "flock_id": row["flock_id"],
        "product_name": row["product_name"],
        "treatment_date": util.ts_domain(row["treatment_date"]),
        "withdrawal_days": row["withdrawal_days"],
        "withdrawal_until": util.ts_domain(row["withdrawal_until"]),
        "fecal_egg_count_before": row["fecal_egg_count_before"],
        "fecal_egg_count_after": row["fecal_egg_count_after"],
        "efficacy_pct": util.num_out(efficacy),
        "resistance_flag": resistance,
    })
    return out


def crew_public(row):
    out = _common(row)
    out.update({
        "crew_name": row["crew_name"],
        "crew_status": row["crew_status"],
        "head_per_day_capacity": row["head_per_day_capacity"],
        "daily_rate_cents": row["daily_rate_cents"],
    })
    return out


def shearing_public(row):
    out = _common(row)
    out.update({
        "flock_id": row["flock_id"],
        "crew_id": row["crew_id"],
        "scheduled_start": util.ts_domain(row["scheduled_start"]),
        "scheduled_end": util.ts_domain(row["scheduled_end"]),
        "expected_head": row["expected_head"],
        "shearing_status": row["shearing_status"],
        "shorn_head_count": row["shorn_head_count"],
    })
    return out


def clip_public(row):
    out = _common(row)
    allocated, unallocated, value, posture = calc.clip_aggregates(row)
    out.update({
        "shearing_event_id": row["shearing_event_id"],
        "flock_id": row["flock_id"],
        "greasy_weight_lbs": util.num_out(row["greasy_weight_lbs"]),
        "skirtings_weight_lbs": util.num_out(row["skirtings_weight_lbs"]),
        "allocated_weight_lbs": util.num_out(allocated),
        "unallocated_weight_lbs": util.num_out(unallocated),
        "clip_value_cents": value,
        "marketing_posture": posture,
    })
    return out


def lot_public(row):
    out = _common(row)
    out.update({
        "clip_id": row["clip_id"],
        "lot_code": row["lot_code"],
        "weight_lbs": util.num_out(row["weight_lbs"]),
        "estimated_micron": util.num_out(row["estimated_micron"]),
        "certified_micron": util.num_out(row["certified_micron"]),
        "certified_yield_pct": util.num_out(row["certified_yield_pct"]),
        "effective_micron": util.num_out(calc.lot_effective_micron(row)),
        "grade_code": calc.lot_grade_code(row),
        "lot_status": row["lot_status"],
        "provisional_value_cents": row["provisional_value_cents"],
        "certified_value_cents": row["certified_value_cents"],
        "effective_value_cents": calc.lot_effective_value(row),
    })
    return out


def core_test_public(row):
    out = _common(row)
    out.update({
        "lot_id": row["lot_id"],
        "lab_ref": row["lab_ref"],
        "test_status": row["test_status"],
        "measured_micron": util.num_out(row["measured_micron"]),
        "clean_yield_pct": util.num_out(row["clean_yield_pct"]),
        "vegetable_matter_pct": util.num_out(row["vegetable_matter_pct"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "locked_by_user_id": row["locked_by_user_id"],
    })
    return out


def consignment_public(row):
    out = _common(row)
    out.update({
        "lot_id": row["lot_id"],
        "pool_ref": row["pool_ref"],
        "consignment_status": row["consignment_status"],
        "advance_cents": row["advance_cents"],
        "sale_gross_cents": row["sale_gross_cents"],
        "pool_fee_cents": row["pool_fee_cents"],
        "settlement_cents": row["settlement_cents"],
        "pending_clawback_cents": row["pending_clawback_cents"],
        "clawback_cents": row["clawback_cents"],
    })
    return out


def holiday_public(row):
    out = _common(row)
    out.update({
        "holiday_name": row["holiday_name"],
        "window_start": util.ts_domain(row["window_start"]),
        "window_end": util.ts_domain(row["window_end"]),
        "premium_pct": util.num_out(row["premium_pct"]),
        "min_head": row["min_head"],
    })
    return out


def sale_public(row):
    out = _common(row)
    out.update({
        "flock_id": row["flock_id"],
        "sale_type": row["sale_type"],
        "channel": row["channel"],
        "head_count": row["head_count"],
        "avg_weight_lbs": util.num_out(row["avg_weight_lbs"]),
        "base_price_per_cwt_cents": row["base_price_per_cwt_cents"],
        "per_head_price_cents": row["per_head_price_cents"],
        "shrink_pct": util.num_out(row["shrink_pct"]),
        "scheduled_date": util.ts_domain(row["scheduled_date"]),
        "payment_status": row["payment_status"],
        "delivery_status": row["delivery_status"],
        "booked_price_cents": row["booked_price_cents"],
        "applied_holiday_name": row["applied_holiday_name"],
        "premium_pct_applied": util.num_out(row["premium_pct_applied"]),
        "actual_total_weight_lbs": util.num_out(row["actual_total_weight_lbs"]),
        "actual_head_delivered": row["actual_head_delivered"],
        "settled_price_cents": row["settled_price_cents"],
    })
    return out


def loss_public(row):
    out = _common(row)
    out.update({
        "flock_id": row["flock_id"],
        "loss_date": util.ts_domain(row["loss_date"]),
        "head_lost": row["head_lost"],
        "predator_type": row["predator_type"],
        "guardian_on_duty": row["guardian_on_duty"],
        "report_status": row["report_status"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
    })
    return out


def contract_public(row):
    out = _common(row)
    out.update({
        "flock_id": row["flock_id"],
        "client_org_name": row["client_org_name"],
        "parcel_name": row["parcel_name"],
        "service_window_start": util.ts_domain(row["service_window_start"]),
        "service_window_end": util.ts_domain(row["service_window_end"]),
        "rate_per_head_day_cents": row["rate_per_head_day_cents"],
        "min_head": row["min_head"],
        "max_head": row["max_head"],
        "target_cover_reduction_pct": util.num_out(row["target_cover_reduction_pct"]),
        "terms_version": row["terms_version"],
        "contract_status": row["contract_status"],
        "breach_flag": row["breach_flag"],
        "achieved_cover_reduction_pct": util.num_out(row["achieved_cover_reduction_pct"]),
        "head_days": row["head_days"],
        "invoice_cents": row["invoice_cents"],
    })
    return out
