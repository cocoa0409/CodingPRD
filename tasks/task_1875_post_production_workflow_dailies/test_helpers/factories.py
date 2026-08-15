"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def set_clock_payload(to_iso8601=TEST_DEFAULTS["INGEST_WINDOW_START"]) -> dict:
    return {"to_iso8601": to_iso8601}


def create_project_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Project",
        "client_code": "CL001",
        "fps": TEST_DEFAULTS["FPS"],
        "resolution_width": TEST_DEFAULTS["RESOLUTION_WIDTH"],
        "resolution_height": TEST_DEFAULTS["RESOLUTION_HEIGHT"],
        "storage_quota_gb": TEST_DEFAULTS["STORAGE_QUOTA_GB"],
        "security_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "batch_label": "DAY01",
        "ingest_window_start": TEST_DEFAULTS["INGEST_WINDOW_START"],
        "ingest_window_end": TEST_DEFAULTS["INGEST_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(batch_id, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "reel_name": "A001",
        "clip_name": "C001",
        "source_bytes": 1000,
        "duration_frames": 100,
    }
    defaults.update(overrides)
    return defaults


def proxy_complete_payload(proxy_bytes=500) -> dict:
    return {"proxy_bytes": proxy_bytes}


def create_watermark_profile_payload(**overrides) -> dict:
    defaults = {
        "profile_name": "wm",
        "opacity_pct": 80,
        "position": "CENTER",
        "includes_recipient_email": True,
        "forensic_enabled": True,
    }
    defaults.update(overrides)
    return defaults


def create_dailies_package_payload(batch_id, watermark_profile_id, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "watermark_profile_id": watermark_profile_id,
        "distribution_list": [TEST_DEFAULTS["DEFAULT_RECIPIENT"]],
    }
    defaults.update(overrides)
    return defaults


def create_bay_payload(**overrides) -> dict:
    defaults = {
        "bay_name": "BAY-01",
        "bay_type": "OFFLINE",
        "capacity_hours_per_day": TEST_DEFAULTS["CAPACITY_HOURS_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(bay_id, expected_bay_version, **overrides) -> dict:
    defaults = {
        "bay_id": bay_id,
        "artist_email": "art@x.com",
        "session_date": "2026-08-05",
        "start_hour": 10,
        "end_hour": 12,
        "version_tag": "v001",
        "expected_bay_version": expected_bay_version,
    }
    defaults.update(overrides)
    return defaults


def create_turnover_payload(**overrides) -> dict:
    defaults = {
        "turnover_kind": "CONFORM",
        "sequence_label": "SEQ-01",
    }
    defaults.update(overrides)
    return defaults


def create_change_list_payload(turnover_id, entries, **overrides) -> dict:
    defaults = {
        "turnover_id": turnover_id,
        "entries": entries,
    }
    defaults.update(overrides)
    return defaults


def change_list_entry(asset_id, operation="TRIM", frames_delta=10) -> dict:
    return {"asset_id": asset_id, "operation": operation, "frames_delta": frames_delta}


def apply_change_list_payload(expected_turnover_version) -> dict:
    return {"expected_turnover_version": expected_turnover_version}


def create_review_round_payload(target_kind, target_ref_id, **overrides) -> dict:
    defaults = {
        "round_label": "RR-01",
        "target_kind": target_kind,
        "target_ref_id": target_ref_id,
    }
    defaults.update(overrides)
    return defaults


def create_review_note_payload(round_id, **overrides) -> dict:
    defaults = {
        "round_id": round_id,
        "author_email": "rev@x.com",
        "severity": "MINOR",
        "body": "check slate",
    }
    defaults.update(overrides)
    return defaults


def create_deliverable_payload(**overrides) -> dict:
    defaults = {
        "spec_kind": "MEZZANINE",
        "sequence_label": "SEQ-01",
        "container": "MOV_PRORES",
        "requires_qc": True,
    }
    defaults.update(overrides)
    return defaults


def render_deliverable_payload(expected_project_version) -> dict:
    return {"expected_project_version": expected_project_version}


def create_qc_report_payload(verdict="FAIL", **overrides) -> dict:
    defaults = {"verdict": verdict}
    if verdict == "FAIL":
        defaults["fail_codes"] = ["GAMUT"]
    defaults.update(overrides)
    return defaults


def create_archive_job_payload(**overrides) -> dict:
    defaults = {
        "lto_generation": "LTO9",
        "target_scope": "SOURCES_ONLY",
        "retention_years": TEST_DEFAULTS["RETENTION_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "V1 Color",
        "capabilities": ["COLOR"],
        "day_rate_cents": TEST_DEFAULTS["DAY_RATE_CENTS"],
        "capacity_slots": 2,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_bid_payload(turnover_id, vendor_id, **overrides) -> dict:
    defaults = {
        "turnover_id": turnover_id,
        "vendor_id": vendor_id,
        "bid_amount_cents": TEST_DEFAULTS["BID_AMOUNT_CENTS"],
        "eta_days": TEST_DEFAULTS["ETA_DAYS"],
    }
    defaults.update(overrides)
    return defaults
