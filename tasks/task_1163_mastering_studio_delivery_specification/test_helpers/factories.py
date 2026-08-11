"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from .constants import DEFAULT_SESSION_START, DEFAULT_UPC, DEFAULT_ISRC

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_client_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "legal_name": f"Label {n}",
        "contact_email": f"label{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_engineer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "display_name": f"Engineer {n}",
        "tier": "STAFF",
        "hourly_rate_cents": 80000,
        "capacity_minutes_per_day": 480,
    }
    defaults.update(overrides)
    return defaults


def create_platform_profile_payload(**overrides) -> dict:
    defaults = {
        "platform_code": "SPOTIFY",
        "integrated_lufs": -14.0,
        "true_peak_dbtp": -1.0,
        "loudness_range_lu": 12.0,
        "required_sample_rate_hz": 44100,
        "required_bit_depth": 24,
        "container_format": "WAV",
    }
    defaults.update(overrides)
    return defaults


def create_rush_tier_rule_payload(**overrides) -> dict:
    defaults = {
        "tier": "STANDARD",
        "multiplier_bp": 10000,
        "sla_hours": 72,
        "surcharge_breach_cents": 0,
        "included_revision_rounds": 1,
        "per_round_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id, target_platform_profile_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "client_id": client_id,
        "title": f"Project {n}",
        "target_platform_profile_id": target_platform_profile_id,
        "scheduled_start_at": DEFAULT_SESSION_START,
        "scheduled_duration_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_session_slot_payload(engineer_id, **overrides) -> dict:
    defaults = {
        "engineer_id": engineer_id,
        "slot_start_at": "2026-05-11T10:00:00Z",
        "slot_end_at": "2026-05-11T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_source_asset_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "filename": f"track{n}.wav",
        "sha256": f"{n:064x}",
        "sample_rate_hz": 44100,
        "bit_depth": 24,
        "duration_seconds": 60.0,
        "channels": 2,
    }
    defaults.update(overrides)
    return defaults


def create_deliverable_payload(revision_round_id, **overrides) -> dict:
    defaults = {
        "revision_round_id": revision_round_id,
        "deliverable_kind": "MASTER_WAV",
        "integrated_lufs": -14.0,
        "true_peak_dbtp": -1.0,
        "loudness_range_lu": 12.0,
        "sample_rate_hz": 44100,
        "bit_depth": 24,
    }
    defaults.update(overrides)
    return defaults


def create_metadata_tag_payload(**overrides) -> dict:
    defaults = {
        "isrc": DEFAULT_ISRC,
        "upc": DEFAULT_UPC,
    }
    defaults.update(overrides)
    return defaults


def create_qc_report_payload(**overrides) -> dict:
    defaults = {
        "check_code": "LOUDNESS_IN_TOL",
        "passed": True,
        "measured_value": -14.0,
        "tolerance": 0.5,
    }
    defaults.update(overrides)
    return defaults


def create_credit_adjustment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100000,
        "reason": "seed",
    }
    defaults.update(overrides)
    return defaults


def create_archive_payload(**overrides) -> dict:
    defaults = {
        "storage_class": "HOT",
        "archive_size_bytes": 1073741824,
    }
    defaults.update(overrides)
    return defaults
