"""Resource serialisation.  Every resource exposes id/created_at/updated_at/version."""

from core import as_number, db, fmt_dt, now_clock


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_show(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "federation_show_id": row["federation_show_id"],
            "venue": row["venue"],
            "competition_level": row["competition_level"],
            "start_utc": fmt_dt(row["start_utc"]),
            "end_utc": fmt_dt(row["end_utc"]),
            "entry_close_utc": fmt_dt(row["entry_close_utc"]),
            "license_status": row["license_status"],
            "revision_count": row["revision_count"],
            "correction_note": row["correction_note"],
            "prize_money_pool_cents": row["prize_money_pool_cents"],
            "allocated_prize_cents": row["allocated_prize_cents"],
            "unallocated_prize_cents": row["prize_money_pool_cents"] - row["allocated_prize_cents"],
            "stall_capacity": row["stall_capacity"],
            "stall_fee_cents": row["stall_fee_cents"],
            "reserved_stall_count": row["reserved_stall_count"],
            "available_stall_count": row["stall_capacity"] - row["reserved_stall_count"],
            "division_share_bp_total": row["division_share_bp_total"],
            "welfare_strike_count": row["welfare_strike_count"],
        }
    )
    return out


def ser_ring(row):
    out = _common(row)
    out.update(
        {
            "show_id": row["show_id"],
            "name": row["name"],
            "surface_type": row["surface_type"],
            "footing_condition_score": row["footing_condition_score"],
            "turnover_buffer_minutes": row["turnover_buffer_minutes"],
            "warmup_capacity_horses": row["warmup_capacity_horses"],
            "status": row["status"],
            "scheduled_minutes_total": row["scheduled_minutes_total"],
            "slot_count": row["slot_count"],
        }
    )
    return out


def ser_division(row):
    out = _common(row)
    out.update(
        {
            "show_id": row["show_id"],
            "name": row["name"],
            "discipline": row["discipline"],
            "age_group": row["age_group"],
            "min_jump_height_cm": row["min_jump_height_cm"],
            "max_jump_height_cm": row["max_jump_height_cm"],
            "division_share_bp": row["division_share_bp"],
            "jumpoff_enabled": row["jumpoff_enabled"],
            "status": row["status"],
            "division_allotment_cents": row["division_allotment_cents"],
        }
    )
    return out


def ser_class(row):
    out = _common(row)
    out.update(
        {
            "division_id": row["division_id"],
            "class_number": row["class_number"],
            "name": row["name"],
            "jump_height_cm": row["jump_height_cm"],
            "entry_fee_cents": row["entry_fee_cents"],
            "class_share_bp": row["class_share_bp"],
            "max_entries": row["max_entries"],
            "qualifier_for_class_id": row["qualifier_for_class_id"],
            "status": row["status"],
            "entry_count": row["entry_count"],
            "confirmed_entry_count": row["confirmed_entry_count"],
            "estimated_minutes": row["estimated_minutes"],
            "actual_minutes": row["actual_minutes"],
            "class_purse_cents": row["class_purse_cents"],
            "awarded_prize_cents": row["awarded_prize_cents"],
            "placed_count": row["placed_count"],
            "point_eligible": row["point_eligible"],
        }
    )
    return out


def ser_slot(row):
    out = _common(row)
    out.update(
        {
            "ring_id": row["ring_id"],
            "class_id": row["class_id"],
            "slot_type": row["slot_type"],
            "start_utc": fmt_dt(row["start_utc"]),
            "duration_minutes": row["duration_minutes"],
            "end_utc": fmt_dt(row["end_utc"]),
            "warmup_start_utc": fmt_dt(row["warmup_start_utc"]),
            "order_index": row["order_index"],
            "status": row["status"],
        }
    )
    return out


def ser_official(row):
    out = _common(row)
    out.update(
        {
            "federation_official_id": row["federation_official_id"],
            "full_name": row["full_name"],
            "license_roles": list(row["license_roles"]),
            "license_level": row["license_level"],
            "licensed_disciplines": list(row["licensed_disciplines"]),
            "license_expires_on": fmt_dt(row["license_expires_on"]),
            "affiliated_trainer_name": row["affiliated_trainer_name"],
            "assigned_minutes": row["assigned_minutes"],
        }
    )
    return out


def ser_assignment(row):
    out = _common(row)
    out.update(
        {
            "official_id": row["official_id"],
            "slot_id": row["slot_id"],
            "official_role": row["official_role"],
            "status": row["status"],
        }
    )
    return out


def ser_rider(row):
    out = _common(row)
    expires = row["membership_expires_on"]
    status = "ACTIVE" if now_clock() < expires else "LAPSED"
    out.update(
        {
            "federation_member_number": row["federation_member_number"],
            "full_name": row["full_name"],
            "membership_expires_on": fmt_dt(expires),
            "trainer_name": row["trainer_name"],
            "membership_status": status,
            "national_points_total": as_number(row["national_points_total"]),
            "regional_points_total": int(row["regional_points_total"]),
        }
    )
    return out


def ser_horse(row):
    out = _common(row)
    out.update(
        {
            "federation_registration_number": row["federation_registration_number"],
            "name": row["name"],
            "owner_name": row["owner_name"],
            "coggins_drawn_on": fmt_dt(row["coggins_drawn_on"]),
            "coggins_expires_on": fmt_dt(row["coggins_expires_on"]),
            "eligibility_status": row["eligibility_status"],
        }
    )
    return out


def ser_entry(row):
    out = _common(row)
    out.update(
        {
            "show_id": row["show_id"],
            "rider_id": row["rider_id"],
            "horse_id": row["horse_id"],
            "verification_status": row["verification_status"],
            "settlement_status": row["settlement_status"],
            "requested_stall_count": row["requested_stall_count"],
            "assigned_stall_count": row["assigned_stall_count"],
            "class_fee_cents_total": row["class_fee_cents_total"],
            "stall_fee_cents": row["stall_fee_cents"],
            "preliminary_subtotal_cents": row["preliminary_subtotal_cents"],
            "office_fee_cents": row["office_fee_cents"],
            "total_due_cents": row["total_due_cents"],
            "refunded_cents": row["refunded_cents"],
        }
    )
    return out


def ser_class_entry(row):
    out = _common(row)
    out.update(
        {
            "entry_id": row["entry_id"],
            "class_id": row["class_id"],
            "status": row["status"],
            "placing": row["placing"],
            "round_seconds": row["round_seconds"],
            "prize_cents": row["prize_cents"],
            "points_national": as_number(row["points_national"]),
            "points_regional": int(row["points_regional"]),
        }
    )
    return out


def ser_submission(row):
    out = _common(row)
    out.update(
        {
            "class_id": row["class_id"],
            "submitted_by_user_id": row["submitted_by_user_id"],
            "national_body_reference": row["national_body_reference"],
            "regional_body_reference": row["regional_body_reference"],
            "national_points_total": as_number(row["national_points_total"]),
            "regional_points_total": int(row["regional_points_total"]),
            "status": row["status"],
        }
    )
    return out


def ser_case(row):
    out = _common(row)
    out.update(
        {
            "entry_id": row["entry_id"],
            "opened_by_official_id": row["opened_by_official_id"],
            "case_type": row["case_type"],
            "sample_code": row["sample_code"],
            "welfare_rule_code": row["welfare_rule_code"],
            "finding": row["finding"],
            "status": row["status"],
        }
    )
    return out


def ser_coverage(row):
    out = _common(row)
    out.update(
        {
            "show_id": row["show_id"],
            "coverage_type": row["coverage_type"],
            "provider_name": row["provider_name"],
            "start_utc": fmt_dt(row["start_utc"]),
            "end_utc": fmt_dt(row["end_utc"]),
            "status": row["status"],
        }
    )
    return out
