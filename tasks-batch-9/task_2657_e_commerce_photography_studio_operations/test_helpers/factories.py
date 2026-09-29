"""Request-payload factories for the Studio Operations API.

Each factory returns a plain dict carrying the required fields named in the PRD
narrative, with **overrides applied last so a caller can vary one field without
restating the rest. Every monetary field is an integer number of whole cents,
because "all money in this system is expressed in whole cents as integers;
there is no fractional-cent representation anywhere" (§2.8) — never a string,
never a float.
"""

from typing import Any, Dict, List, Optional

from .constants import CALIBRATED_FAR_FUTURE


# ─── Reference data (§3.1) ─────────────────────────────────────────────────

def vendor_payload(
    name: str = "Northline Apparel",
    vendor_code: str = "NRTH",
    sample_sla_days: int = 14,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "vendor_code": vendor_code,
        "sample_sla_days": sample_sla_days,
    }
    payload.update(overrides)
    return payload


def asset_profile_payload(
    category: str = "APPAREL_TOP",
    required_angles: Optional[List[str]] = None,
    required_detail_shots: int = 0,
    min_on_model_shots: int = 1,
    video_required: bool = False,
    naming_pattern: str = "{style_number}_{angle_code}_{seq}",
    required_metadata_keys: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category": category,
        "required_angles": required_angles
        if required_angles is not None
        else ["FRONT", "BACK"],
        "required_detail_shots": required_detail_shots,
        "min_on_model_shots": min_on_model_shots,
        "video_required": video_required,
        "naming_pattern": naming_pattern,
        "required_metadata_keys": required_metadata_keys
        if required_metadata_keys is not None
        else ["season"],
    }
    payload.update(overrides)
    return payload


def station_payload(
    station_code: str = "MODEL-1",
    station_type: str = "MODEL",
    daily_capacity_minutes: int = 1440,
    buffer_minutes: int = 0,
    max_concurrent_sessions: int = 1,
    calibrated_until: Optional[str] = CALIBRATED_FAR_FUTURE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_code": station_code,
        "station_type": station_type,
        "daily_capacity_minutes": daily_capacity_minutes,
        "buffer_minutes": buffer_minutes,
        "max_concurrent_sessions": max_concurrent_sessions,
        "calibrated_until": calibrated_until,
    }
    payload.update(overrides)
    return payload


def talent_payload(
    full_name: str = "Pia Ren",
    talent_type: str = "PHOTOGRAPHER",
    hourly_rate_cents: int = 12000,
    day_rate_cents: int = 80000,
    minimum_call_hours: int = 4,
    max_daily_minutes: int = 480,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "talent_type": talent_type,
        "hourly_rate_cents": hourly_rate_cents,
        "day_rate_cents": day_rate_cents,
        "minimum_call_hours": minimum_call_hours,
        "max_daily_minutes": max_daily_minutes,
    }
    payload.update(overrides)
    return payload


def _talent_of_type(
    full_name: str,
    talent_type: str,
    hourly_rate_cents: int,
    day_rate_cents: int,
    overrides: Dict[str, Any],
) -> Dict[str, Any]:
    """Per-type talent defaults with caller overrides winning.

    `overrides` is merged with `setdefault` rather than splatted into
    `talent_payload`, so a caller naming `full_name` (or any other per-type
    default) supplies it once instead of colliding with the positional default.
    """
    kwargs = dict(overrides)
    kwargs.setdefault("full_name", full_name)
    kwargs.setdefault("talent_type", talent_type)
    kwargs.setdefault("hourly_rate_cents", hourly_rate_cents)
    kwargs.setdefault("day_rate_cents", day_rate_cents)
    return talent_payload(**kwargs)


def photographer_payload(**overrides: Any) -> Dict[str, Any]:
    return _talent_of_type("Pia Ren", "PHOTOGRAPHER", 12000, 80000, overrides)


def retoucher_payload(**overrides: Any) -> Dict[str, Any]:
    return _talent_of_type("Remy Ott", "RETOUCHER", 6000, 40000, overrides)


def model_payload(**overrides: Any) -> Dict[str, Any]:
    return _talent_of_type("Ada Vell", "MODEL", 25000, 150000, overrides)


def stylist_payload(**overrides: Any) -> Dict[str, Any]:
    return _talent_of_type("Sol Grebe", "STYLIST", 9000, 60000, overrides)


def provider_payload(
    provider_code: str = "INHOUSE",
    provider_kind: str = "IN_HOUSE",
    station_hour_rate_cents: int = 18500,
    retouch_rate_cents_per_asset: int = 900,
    sla_hours: int = 12,
    quality_score: float = 92.00,
    style_quote_cents: int = 0,
    capacity_assets_per_day: int = 40,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "provider_code": provider_code,
        "provider_kind": provider_kind,
        "station_hour_rate_cents": station_hour_rate_cents,
        "retouch_rate_cents_per_asset": retouch_rate_cents_per_asset,
        "sla_hours": sla_hours,
        "quality_score": quality_score,
        "style_quote_cents": style_quote_cents,
        "capacity_assets_per_day": capacity_assets_per_day,
    }
    payload.update(overrides)
    return payload


def outsourced_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """Outsourced-provider defaults with caller overrides winning."""
    kwargs = dict(overrides)
    kwargs.setdefault("provider_code", "OUT1")
    kwargs.setdefault("provider_kind", "OUTSOURCED")
    kwargs.setdefault("station_hour_rate_cents", 21000)
    kwargs.setdefault("retouch_rate_cents_per_asset", 1200)
    kwargs.setdefault("sla_hours", 24)
    kwargs.setdefault("quality_score", 88.00)
    kwargs.setdefault("style_quote_cents", 120000)
    kwargs.setdefault("capacity_assets_per_day", 40)
    return provider_payload(**kwargs)


# ─── Styles (§3.2) ─────────────────────────────────────────────────────────

def style_payload(
    vendor_id: str,
    asset_profile_id: str,
    style_number: str = "TOP1001",
    category: str = "APPAREL_TOP",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "style_number": style_number,
        "category": category,
        "vendor_id": vendor_id,
        "asset_profile_id": asset_profile_id,
    }
    payload.update(overrides)
    return payload


# ─── Samples (§3.3) ────────────────────────────────────────────────────────

def sample_payload(
    vendor_id: str,
    declared_style_number: str = "TOP1001",
    barcode: str = "SMP-1001",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "barcode": barcode,
        "vendor_id": vendor_id,
        "declared_style_number": declared_style_number,
    }
    payload.update(overrides)
    return payload


def custody_move_payload(to_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


def match_payload(style_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"style_id": style_id}
    payload.update(overrides)
    return payload


# ─── Release documents (§3.5) ──────────────────────────────────────────────

def release_payload(
    talent_id: str,
    scope: str = "ECOM_ONLY",
    territory: str = "US",
    valid_from: str = "2026-08-01T00:00:00Z",
    valid_until: str = "2026-12-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "talent_id": talent_id,
        "scope": scope,
        "territory": territory,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload


# ─── Shoot sessions (§3.4) ─────────────────────────────────────────────────

def session_payload(
    station_id: str,
    provider_id: str,
    scheduled_start: str = "2026-08-03T09:00:00Z",
    scheduled_end: str = "2026-08-03T13:00:00Z",
    required_usage_scope: str = "ECOM_ONLY",
    budget_cap_cents: int = 500000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "provider_id": provider_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "required_usage_scope": required_usage_scope,
        "budget_cap_cents": budget_cap_cents,
    }
    payload.update(overrides)
    return payload


# ─── Talent bookings (§3.5) ────────────────────────────────────────────────

def booking_payload(
    session_id: str,
    talent_id: str,
    expected_session_version: int,
    role_on_set: str = "PHOTOGRAPHER",
    call_time: str = "2026-08-03T09:00:00Z",
    wrap_time: str = "2026-08-03T13:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "talent_id": talent_id,
        "role_on_set": role_on_set,
        "call_time": call_time,
        "wrap_time": wrap_time,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


# ─── Shot-list items (§3.6) ────────────────────────────────────────────────

def shot_item_payload(
    style_id: str,
    expected_style_version: int,
    asset_kind: str = "ON_MODEL",
    angle_code: str = "FRONT",
    estimated_minutes: int = 60,
    required: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "style_id": style_id,
        "asset_kind": asset_kind,
        "angle_code": angle_code,
        "estimated_minutes": estimated_minutes,
        "required": required,
        "expected_style_version": expected_style_version,
    }
    payload.update(overrides)
    return payload


# ─── Assets (§3.7) ─────────────────────────────────────────────────────────

def asset_payload(
    shot_list_item_id: str,
    file_name: str,
    sequence_number: int = 1,
    metadata_tags: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shot_list_item_id": shot_list_item_id,
        "file_name": file_name,
        "sequence_number": sequence_number,
        "metadata_tags": metadata_tags
        if metadata_tags is not None
        else {"season": "FW26"},
    }
    payload.update(overrides)
    return payload


def expand_file_name(style_number: str, angle_code: str, sequence_number: int) -> str:
    """Expand the naming pattern of §3.7: style number, angle code, seq to width 3."""
    return f"{style_number}_{angle_code}_{sequence_number:03d}"


# ─── Retouch tasks (§3.8) ──────────────────────────────────────────────────

def retouch_task_payload(
    asset_id: str, provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"asset_id": asset_id, "provider_id": provider_id}
    payload.update(overrides)
    return payload


def qc_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Colour measurement (§3.7) ─────────────────────────────────────────────

def color_measurement_payload(
    patch_deltas: List[float], **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"patch_deltas": patch_deltas}
    payload.update(overrides)
    return payload


# ─── Logical clock (§2.4) ──────────────────────────────────────────────────

def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
