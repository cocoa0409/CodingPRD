"""Resource serialisers.  Denormalised counters are rendered from a full
recount so they can never disagree with their source rows."""
from core import iso3, num_out
from logic import (
    item_live_asset_count, priority_score, provider_assigned_asset_count,
    refresh_release, station_committed_minutes_today,
    style_delivered_asset_count, style_required_item_count,
    session_committed_talent_cost, talent_booked_minutes_today,
    vendor_outstanding,
)


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso3(row["created_at"]),
        "updated_at": iso3(row["updated_at"]),
        "version": row["version"],
    }


def vendor_out(row):
    out = {
        "name": row["name"],
        "vendor_code": row["vendor_code"],
        "sample_sla_days": row["sample_sla_days"],
        "contact_email": row["contact_email"],
        "outstanding_sample_count": vendor_outstanding(row["id"]),
        "late_return_count": row["late_return_count"],
        "coordination_hold": row["coordination_hold"],
    }
    out.update(_common(row))
    return out


def asset_profile_out(row):
    return {
        "id": row["id"],
        "category": row["category"],
        "required_angles": list(row["required_angles"]),
        "required_detail_shots": row["required_detail_shots"],
        "min_on_model_shots": row["min_on_model_shots"],
        "video_required": row["video_required"],
        "naming_pattern": row["naming_pattern"],
        "required_metadata_keys": list(row["required_metadata_keys"]),
        "created_at": iso3(row["created_at"]),
    }


def station_out(row):
    out = {
        "station_code": row["station_code"],
        "station_type": row["station_type"],
        "daily_capacity_minutes": row["daily_capacity_minutes"],
        "buffer_minutes": row["buffer_minutes"],
        "max_concurrent_sessions": row["max_concurrent_sessions"],
        "calibrated_until": iso3(row["calibrated_until"]),
        "committed_minutes_today": station_committed_minutes_today(row["id"]),
    }
    out.update(_common(row))
    return out


def talent_out(row):
    out = {
        "full_name": row["full_name"],
        "talent_type": row["talent_type"],
        "agency_name": row["agency_name"],
        "hourly_rate_cents": row["hourly_rate_cents"],
        "day_rate_cents": row["day_rate_cents"],
        "minimum_call_hours": row["minimum_call_hours"],
        "max_daily_minutes": row["max_daily_minutes"],
        "booked_minutes_today": talent_booked_minutes_today(row["id"]),
        "requires_release": row["requires_release"],
    }
    out.update(_common(row))
    return out


def provider_out(row):
    out = {
        "provider_code": row["provider_code"],
        "provider_kind": row["provider_kind"],
        "station_hour_rate_cents": row["station_hour_rate_cents"],
        "retouch_rate_cents_per_asset": row["retouch_rate_cents_per_asset"],
        "sla_hours": row["sla_hours"],
        "quality_score": num_out(row["quality_score"], 2),
        "style_quote_cents": row["style_quote_cents"],
        "capacity_assets_per_day": row["capacity_assets_per_day"],
        "assigned_asset_count": provider_assigned_asset_count(row["id"]),
    }
    out.update(_common(row))
    return out


def style_out(row):
    out = {
        "style_number": row["style_number"],
        "category": row["category"],
        "vendor_id": row["vendor_id"],
        "asset_profile_id": row["asset_profile_id"],
        "base_style_id": row["base_style_id"],
        "colorway_code": row["colorway_code"],
        "priority_tier": row["priority_tier"],
        "content_state": row["content_state"],
        "required_item_count": style_required_item_count(row["id"]),
        "allocated_cost_cents": row["allocated_cost_cents"],
        "delivered_asset_count": style_delivered_asset_count(row["id"]),
    }
    out.update(_common(row))
    return out


def sample_out(row):
    out = {
        "barcode": row["barcode"],
        "vendor_id": row["vendor_id"],
        "declared_style_number": row["declared_style_number"],
        "matched_style_id": row["matched_style_id"],
        "custody_state": row["custody_state"],
        "match_state": row["match_state"],
        "received_at": iso3(row["received_at"]),
        "due_return_at": iso3(row["due_return_at"]),
        "returned_at": iso3(row["returned_at"]),
        "return_days_late": row["return_days_late"],
        "condition_note": row["condition_note"],
    }
    out.update(_common(row))
    return out


def release_out(row):
    refresh_release(row)
    out = {
        "talent_id": row["talent_id"],
        "scope": row["scope"],
        "territory": row["territory"],
        "valid_from": iso3(row["valid_from"]),
        "valid_until": iso3(row["valid_until"]),
        "doc_state": row["doc_state"],
        "signed_at": iso3(row["signed_at"]),
    }
    out.update(_common(row))
    return out


def session_out(row):
    out = {
        "station_id": row["station_id"],
        "provider_id": row["provider_id"],
        "session_label": row["session_label"],
        "scheduled_start": iso3(row["scheduled_start"]),
        "scheduled_end": iso3(row["scheduled_end"]),
        "planned_minutes": row["planned_minutes"],
        "required_usage_scope": row["required_usage_scope"],
        "budget_cap_cents": row["budget_cap_cents"],
        "session_state": row["session_state"],
        "committed_talent_cost_cents": session_committed_talent_cost(row["id"]),
        "started_at": iso3(row["started_at"]),
        "wrapped_at": iso3(row["wrapped_at"]),
        "actual_minutes": row["actual_minutes"],
        "color_chart_code": row["color_chart_code"],
        "color_tolerance_delta_e": num_out(row["color_tolerance_delta_e"], 2),
        "color_patch_deltas": list(row["color_patch_deltas"]),
        "color_composite_delta_e": num_out(row["color_composite_delta_e"], 2),
        "color_check_state": row["color_check_state"],
        "color_measured_at": iso3(row["color_measured_at"]),
        "color_measured_by_talent_id": row["color_measured_by_talent_id"],
    }
    out.update(_common(row))
    return out


def booking_out(row):
    out = {
        "session_id": row["session_id"],
        "talent_id": row["talent_id"],
        "role_on_set": row["role_on_set"],
        "call_time": iso3(row["call_time"]),
        "wrap_time": iso3(row["wrap_time"]),
        "booked_minutes": row["booked_minutes"],
        "regular_minutes": row["regular_minutes"],
        "overtime_minutes": row["overtime_minutes"],
        "charge_cents": row["charge_cents"],
        "booking_state": row["booking_state"],
        "usage_rights_scope": row["usage_rights_scope"],
        "release_document_id": row["release_document_id"],
    }
    out.update(_common(row))
    return out


def item_out(row):
    out = {
        "style_id": row["style_id"],
        "session_id": row["session_id"],
        "asset_kind": row["asset_kind"],
        "angle_code": row["angle_code"],
        "required": row["required"],
        "estimated_minutes": row["estimated_minutes"],
        "item_state": row["item_state"],
        "live_asset_count": item_live_asset_count(row["id"]),
        "allocated_cost_cents": row["allocated_cost_cents"],
    }
    out.update(_common(row))
    return out


def asset_out(row):
    out = {
        "shot_list_item_id": row["shot_list_item_id"],
        "session_id": row["session_id"],
        "file_name": row["file_name"],
        "sequence_number": row["sequence_number"],
        "metadata_tags": dict(row["metadata_tags"]),
        "captured_by_talent_id": row["captured_by_talent_id"],
        "asset_state": row["asset_state"],
        "cms_asset_key": row["cms_asset_key"],
        "delivered_at": iso3(row["delivered_at"]),
    }
    out.update(_common(row))
    return out


def task_out(row):
    out = {
        "asset_id": row["asset_id"],
        "provider_id": row["provider_id"],
        "assigned_retoucher_id": row["assigned_retoucher_id"],
        "task_state": row["task_state"],
        "priority_score": num_out(priority_score(row), 2),
        "sla_hours": row["sla_hours"],
        "due_at": iso3(row["due_at"]),
        "rework_count": row["rework_count"],
        "rework_started_at": iso3(row["rework_started_at"]),
        "rework_hours_total": num_out(row["rework_hours_total"], 2),
        "claimed_at": iso3(row["claimed_at"]),
        "submitted_at": iso3(row["submitted_at"]),
        "approved_at": iso3(row["approved_at"]),
        "turnaround_hours_gross": num_out(row["turnaround_hours_gross"], 2),
        "turnaround_hours_net": num_out(row["turnaround_hours_net"], 2),
        "sla_state": row["sla_state"],
    }
    out.update(_common(row))
    return out
