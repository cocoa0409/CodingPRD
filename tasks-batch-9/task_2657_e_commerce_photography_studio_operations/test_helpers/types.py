"""TypedDict shapes for every resource the Studio Operations API returns.

These describe the response payloads named in the PRD narrative. Every resource
carries `id` and `created_at` (§2.5); almost every resource additionally carries
`updated_at` and an integer `version`. `AssetProfile` is the single exception —
"the resource carries only id and created_at. Both updated_at and version are
absent from an AssetProfile payload."
"""

from typing import Any, Dict, List, Optional, TypedDict


class Vendor(TypedDict):
    id: str
    name: str
    vendor_code: str
    sample_sla_days: int
    contact_email: Optional[str]
    outstanding_sample_count: int
    late_return_count: int
    coordination_hold: bool
    created_at: str
    updated_at: str
    version: int


class AssetProfile(TypedDict):
    id: str
    category: str
    required_angles: List[str]
    required_detail_shots: int
    min_on_model_shots: int
    video_required: bool
    naming_pattern: str
    required_metadata_keys: List[str]
    created_at: str


class Station(TypedDict):
    id: str
    station_code: str
    station_type: str
    daily_capacity_minutes: int
    buffer_minutes: int
    max_concurrent_sessions: int
    calibrated_until: Optional[str]
    committed_minutes_today: int
    created_at: str
    updated_at: str
    version: int


class TalentProfile(TypedDict):
    id: str
    full_name: str
    talent_type: str
    agency_name: Optional[str]
    hourly_rate_cents: int
    day_rate_cents: int
    minimum_call_hours: int
    max_daily_minutes: int
    requires_release: bool
    booked_minutes_today: int
    created_at: str
    updated_at: str
    version: int


class StudioProvider(TypedDict):
    id: str
    provider_code: str
    provider_kind: str
    station_hour_rate_cents: int
    retouch_rate_cents_per_asset: int
    sla_hours: int
    quality_score: float
    style_quote_cents: int
    capacity_assets_per_day: int
    assigned_asset_count: int
    created_at: str
    updated_at: str
    version: int


class Style(TypedDict):
    id: str
    style_number: str
    category: str
    vendor_id: str
    asset_profile_id: str
    base_style_id: Optional[str]
    colorway_code: Optional[str]
    priority_tier: str
    content_state: str
    required_item_count: int
    delivered_asset_count: int
    allocated_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict):
    id: str
    barcode: str
    vendor_id: str
    declared_style_number: str
    matched_style_id: Optional[str]
    custody_state: str
    match_state: str
    received_at: Optional[str]
    due_return_at: Optional[str]
    returned_at: Optional[str]
    return_days_late: Optional[int]
    condition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseDocument(TypedDict):
    id: str
    talent_id: str
    scope: str
    territory: str
    valid_from: str
    valid_until: str
    doc_state: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShootSession(TypedDict):
    id: str
    station_id: str
    provider_id: str
    session_label: Optional[str]
    scheduled_start: str
    scheduled_end: str
    planned_minutes: int
    actual_minutes: Optional[int]
    required_usage_scope: str
    budget_cap_cents: int
    committed_talent_cost_cents: int
    session_state: str
    color_chart_code: str
    color_tolerance_delta_e: float
    color_check_state: str
    color_patch_deltas: List[float]
    color_composite_delta_e: Optional[float]
    color_measured_at: Optional[str]
    color_measured_by_talent_id: Optional[str]
    started_at: Optional[str]
    wrapped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TalentBooking(TypedDict):
    id: str
    session_id: str
    talent_id: str
    role_on_set: str
    call_time: str
    wrap_time: str
    booked_minutes: int
    regular_minutes: int
    overtime_minutes: int
    charge_cents: int
    booking_state: str
    usage_rights_scope: Optional[str]
    release_document_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShotListItem(TypedDict):
    id: str
    style_id: str
    session_id: Optional[str]
    asset_kind: str
    angle_code: str
    estimated_minutes: int
    required: bool
    item_state: str
    live_asset_count: int
    allocated_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    shot_list_item_id: str
    session_id: str
    captured_by_talent_id: str
    file_name: str
    sequence_number: int
    metadata_tags: Dict[str, Any]
    asset_state: str
    cms_asset_key: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetouchTask(TypedDict):
    id: str
    asset_id: str
    provider_id: str
    assigned_retoucher_id: Optional[str]
    task_state: str
    sla_hours: int
    due_at: str
    priority_score: Optional[float]
    rework_count: int
    rework_hours_total: float
    rework_started_at: Optional[str]
    claimed_at: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    turnaround_hours_gross: Optional[float]
    turnaround_hours_net: Optional[float]
    sla_state: str
    created_at: str
    updated_at: str
    version: int


class CostSummary(TypedDict):
    """The nine members of the computed cost summary described in PRD §3.9."""

    style_id: str
    provisional_cost_cents: int
    final_cost_cents: int
    provisional_cost_per_asset_cents: int
    final_cost_per_asset_cents: int
    outsourced_quote_cents: Optional[int]
    outsourced_provider_id: Optional[str]
    variance_cents: Optional[int]
    recommended_source: str


class ClockEcho(TypedDict):
    current_utc: str
