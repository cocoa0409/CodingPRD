"""Per-entity serialization.  Internal fields (``_``-prefixed) never leave the
process; caller-supplied instants are echoed byte for byte; server-written
instants carry three fractional digits."""

from services import derive


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def organization(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "org_type": row["org_type"],
            "contact_email": row["contact_email"],
            "insurance_certificate_expiry": row.get("insurance_certificate_expiry"),
            "insurance_coverage_cents": row.get("insurance_coverage_cents"),
            "no_show_count": row.get("no_show_count", 0),
            "standing": derive.derive_standing(row),
            "deposit_held_cents": derive.org_deposit_held_cents(row),
            "outstanding_balance_cents": derive.org_outstanding_balance_cents(row),
        }
    )
    return out


def room(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "building_code": row["building_code"],
            "capacity": row["capacity"],
            "features": list(row.get("features", [])),
            "turnaround_buffer_minutes": row.get("turnaround_buffer_minutes", 30),
            "internal_hourly_rate_cents": row["internal_hourly_rate_cents"],
            "student_hourly_rate_cents": row["student_hourly_rate_cents"],
            "external_hourly_rate_cents": row["external_hourly_rate_cents"],
            "peak_multiplier_bps": row.get("peak_multiplier_bps", 12500),
            "status": row["status"],
            "outage_start_at": row.get("outage_start_at"),
            "outage_end_at": row.get("outage_end_at"),
            "outage_windows": [dict(w) for w in row.get("outage_windows", [])],
            "key_count": row.get("key_count", 0),
            "keys_issued": derive.room_keys_issued(row),
            "keys_lost_total": derive.room_keys_lost_total(row),
        }
    )
    return out


def term(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "term_start_date": row["term_start_date"],
            "term_end_date": row["term_end_date"],
            "priority_open_at": row["priority_open_at"],
            "general_open_at": row["general_open_at"],
            "status": row["status"],
            "current_draft_run_id": row.get("current_draft_run_id"),
        }
    )
    return out


def academic_block(row):
    out = _common(row)
    out.update(
        {
            "term_id": row["term_id"],
            "course_code": row["course_code"],
            "instructor_name": row["instructor_name"],
            "enrollment": row["enrollment"],
            "required_features": list(row.get("required_features", [])),
            "days_of_week": list(row.get("days_of_week", [])),
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "priority_score": row.get("priority_score", 0),
            "status": row["status"],
            "assigned_room_id": row.get("assigned_room_id"),
            "scheduling_run_id": row.get("scheduling_run_id"),
        }
    )
    return out


def scheduling_run(row):
    out = _common(row)
    out.update(
        {
            "term_id": row["term_id"],
            "status": row["status"],
            "placed_count": row.get("placed_count", 0),
            "bumped_event_ids": list(row.get("bumped_event_ids", [])),
            "unplaced_block_ids": list(row.get("unplaced_block_ids", [])),
            "finalized_at": row.get("finalized_at"),
        }
    )
    return out


def event(row):
    out = _common(row)
    out.update(
        {
            "requester_org_id": row.get("requester_org_id"),
            "room_id": row.get("room_id"),
            "title": row["title"],
            "expected_attendance": row["expected_attendance"],
            "required_features": list(row.get("required_features", [])),
            "start_at": row["start_at"],
            "end_at": row["end_at"],
            "setup_minutes": row.get("setup_minutes", 0),
            "teardown_minutes": row.get("teardown_minutes", 0),
            "precedence_tier": row.get("precedence_tier"),
            "status": row["status"],
            "decision_deadline": row.get("decision_deadline"),
            "confirm_deadline": row.get("confirm_deadline"),
            "checked_in_at": row.get("checked_in_at"),
            "pinned_hourly_rate_cents": row.get("pinned_hourly_rate_cents"),
            "pinned_peak_multiplier_bps": row.get("pinned_peak_multiplier_bps"),
            "cancellation_fee_cents": row.get("cancellation_fee_cents"),
            "cancel_reason": row.get("cancel_reason"),
            "approved_by_user_id": row.get("approved_by_user_id"),
            "decline_reason": row.get("decline_reason"),
        }
    )
    return out


def service_order(row):
    out = _common(row)
    out.update(
        {
            "event_id": row["event_id"],
            "category": row["category"],
            "quantity": row["quantity"],
            "unit_cost_cents": row.get("unit_cost_cents"),
            "quoted_total_cents": row.get("quoted_total_cents"),
            "service_start_at": row["service_start_at"],
            "service_end_at": row["service_end_at"],
            "crew_id": row.get("crew_id"),
            "status": row["status"],
            "fee_waived": row.get("fee_waived", False),
            "revision_note": row.get("revision_note"),
        }
    )
    return out


def service_crew(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "category": row["category"],
            "concurrent_capacity": row["concurrent_capacity"],
            "shift_start": row["shift_start"],
            "shift_end": row["shift_end"],
        }
    )
    return out


def invoice(row):
    out = _common(row)
    out.update(
        {
            "event_id": row["event_id"],
            "org_id": row["org_id"],
            "status": row["status"],
            "room_charge_cents": row.get("room_charge_cents", 0),
            "service_charge_cents": row.get("service_charge_cents", 0),
            "insurance_surcharge_cents": row.get("insurance_surcharge_cents", 0),
            "cancellation_fee_cents": row.get("cancellation_fee_cents", 0),
            "no_show_fee_cents": row.get("no_show_fee_cents", 0),
            "deposit_charge_cents": row.get("deposit_charge_cents", 0),
            "total_cents": row.get("total_cents", 0),
            "paid_cents": row.get("paid_cents", 0),
            "waived_cents": row.get("waived_cents", 0),
            "refunded_cents": row.get("refunded_cents", 0),
        }
    )
    return out


def access_grant(row):
    out = _common(row)
    out.update(
        {
            "event_id": row["event_id"],
            "room_id": row.get("room_id"),
            "grant_type": row["grant_type"],
            "status": row["status"],
            "key_slot": row.get("key_slot"),
            "deposit_cents": row.get("deposit_cents", 0),
            "deposit_forfeit_cents": row.get("deposit_forfeit_cents", 0),
            "return_deadline": row.get("return_deadline"),
            "returned_at": row.get("returned_at"),
        }
    )
    return out
