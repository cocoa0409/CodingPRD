"""Entity serializers. Derived fields are computed at read time (PRD 2.11)."""

import calc
from store import iso


def _common(row, out, with_version=True):
    out["id"] = row["id"]
    out["created_at"] = iso(row["created_at"])
    if with_version:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def venue(row):
    out = {
        "name": row["name"],
        "rigging_capacity_kg": row["rigging_capacity_kg"],
        "dock_count": row["dock_count"],
        "max_bowl_seats": row["max_bowl_seats"],
        "crew_headcount_cap": row["crew_headcount_cap"],
        "min_turnaround_buffer_minutes": row["min_turnaround_buffer_minutes"],
        "dock_buffer_minutes": row["dock_buffer_minutes"],
        "overnight_shift_start_local_hour": row["overnight_shift_start_local_hour"],
        "ice_deck_status": calc.ice_deck_status(row["id"]),
        "rigging_committed_load_kg": calc.as_number(calc.rigging_committed_load_kg(row["id"])),
        "open_hold_count": calc.open_hold_count(row["id"]),
        "changeover_debt_minutes": row["changeover_debt_minutes"],
    }
    return _common(row, out)


def profile(row):
    out = {
        "venue_id": row["venue_id"],
        "code": row["code"],
        "requires_ice": row["requires_ice"],
        "ice_cover_required": row["ice_cover_required"],
        "seating_mode": row["seating_mode"],
        "nominal_seats": row["nominal_seats"],
        "base_changeover_minutes": row["base_changeover_minutes"],
        "crew_size_required": row["crew_size_required"],
        "floor_protection_panels_required": row["floor_protection_panels_required"],
        "dehumidification_required_lph": row["dehumidification_required_lph"],
        "rigging_points_required": row["rigging_points_required"],
    }
    # PRD 2.4: a configuration profile is immutable, so it carries neither
    # updated_at nor version.
    return _common(row, out, with_version=False)


def tenant(row):
    out = {
        "venue_id": row["venue_id"],
        "name": row["name"],
        "hold_priority_tier": row["hold_priority_tier"],
        "guaranteed_holds_per_season": row["guaranteed_holds_per_season"],
        "holds_consumed": calc.holds_consumed(row["id"]),
        "challenge_credits": row["challenge_credits"],
    }
    return _common(row, out)


def booking(row):
    out = {
        "venue_id": row["venue_id"],
        "tenant_id": row["tenant_id"],
        "config_profile_id": row["config_profile_id"],
        "displaced_by_booking_id": row["displaced_by_booking_id"],
        "title": row["title"],
        "promoter_name": row["promoter_name"],
        "event_start_utc": iso(row["event_start_utc"]),
        "event_end_utc": iso(row["event_end_utc"]),
        "rigging_load_kg": row["rigging_load_kg"],
        "expected_attendance": row["expected_attendance"],
        "status": row["status"],
        "hold_tier": row["hold_tier"],
        "hold_placed_at": iso(row["hold_placed_at"]),
        "hold_expires_at": iso(row["hold_expires_at"]),
        "release_reason": row["release_reason"],
        "displacement_penalty_cents": row["displacement_penalty_cents"],
    }
    return _common(row, out)


def challenge(row):
    out = {
        "booking_id": row["booking_id"],
        "challenger_tenant_id": row["challenger_tenant_id"],
        "challenger_booking_id": row["challenger_booking_id"],
        "status": row["status"],
        "priority_delta": row["priority_delta"],
        "ruled_at": iso(row["ruled_at"]),
        "ruling_note": row["ruling_note"],
    }
    return _common(row, out)


def order(row):
    out = {
        "venue_id": row["venue_id"],
        "from_booking_id": row["from_booking_id"],
        "to_booking_id": row["to_booking_id"],
        "window_start_utc": iso(row["window_start_utc"]),
        "window_end_utc": iso(row["window_end_utc"]),
        "window_minutes": row["window_minutes"],
        "crew_headcount": row["crew_headcount"],
        "overnight_shift": row["overnight_shift"],
        "planned_turnaround_minutes": row["planned_turnaround_minutes"],
        "actual_turnaround_minutes": row["actual_turnaround_minutes"],
        "overrun_minutes": row["overrun_minutes"],
        "floor_stage": row["floor_stage"],
        "seating_stage": row["seating_stage"],
        "infra_stage": row["infra_stage"],
        "status": row["status"],
        "rework_count": row["rework_count"],
        "started_at_utc": iso(row["started_at_utc"]),
        "completed_at_utc": iso(row["completed_at_utc"]),
        "opened_by_user_id": row["opened_by_user_id"],
        "signed_off_by_user_id": row["signed_off_by_user_id"],
        "abandon_reason": row["abandon_reason"],
    }
    return _common(row, out)


def ice_sheet(row):
    out = {
        "venue_id": row["venue_id"],
        "sheet_thickness_mm": row["sheet_thickness_mm"],
        "required_dehumidification_lph": row["required_dehumidification_lph"],
        "dehumidification_lph_applied": row["dehumidification_lph_applied"],
        "status": row["status"],
        "cover_installed_at_utc": iso(row["cover_installed_at_utc"]),
        "cover_hours_accumulated": calc.as_number(row["cover_hours_accumulated"]),
        "cover_cycles": row["cover_cycles"],
        "condensation_risk_score": calc.as_number(row["condensation_risk_score"]),
    }
    return _common(row, out)


def dock(row):
    out = {
        "booking_id": row["booking_id"],
        "dock_number": row["dock_number"],
        "purpose": row["purpose"],
        "window_start_utc": iso(row["window_start_utc"]),
        "window_end_utc": iso(row["window_end_utc"]),
        "truck_count": row["truck_count"],
        "status": row["status"],
        "release_reason": row["release_reason"],
    }
    return _common(row, out)


def labor_call(row):
    out = {
        "changeover_order_id": row["changeover_order_id"],
        "booking_id": row["booking_id"],
        "craft": row["craft"],
        "headcount": row["headcount"],
        "call_start_utc": iso(row["call_start_utc"]),
        "call_end_utc": iso(row["call_end_utc"]),
        "guaranteed_hours": row["guaranteed_hours"],
        "actual_hours": row["actual_hours"],
        "overnight": row["overnight"],
        "status": row["status"],
        "estimated_cost_cents": row["estimated_cost_cents"],
        "settled_cost_cents": row["settled_cost_cents"],
        "cancellation_fee_cents": row["cancellation_fee_cents"],
    }
    return _common(row, out)


def asset(row):
    out = {
        "venue_id": row["venue_id"],
        "asset_class": row["asset_class"],
        "units_total": row["units_total"],
        "units_available": calc.equipment_units_available(row),
        "units_out_of_service": row["units_out_of_service"],
        "service_interval_cycles": row["service_interval_cycles"],
        "cycles_since_service": row["cycles_since_service"],
        "service_due": calc.service_due(row),
        "status": row["status"],
    }
    return _common(row, out)


def issue(row):
    out = {
        "asset_id": row["asset_id"],
        "changeover_order_id": row["changeover_order_id"],
        "units_issued": row["units_issued"],
        "damaged_units": row["damaged_units"],
        "status": row["status"],
        "returned_at_utc": iso(row["returned_at_utc"]),
        "return_reason": row["return_reason"],
    }
    return _common(row, out)
