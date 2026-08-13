"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_client_payload(**overrides) -> dict:
    defaults = {"name": "Acme", "compliance_standard": "INTERNAL"}
    defaults.update(overrides)
    return defaults


def create_media_asset_payload(**overrides) -> dict:
    defaults = {
        "title": "Prog",
        "media_kind": "FILE_BASED",
        "duration_seconds": 3600,
        "frame_rate": "FPS_30",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "service_type": "CAPTIONS",
        "turnaround_tier": "STANDARD",
        "language": "en-US",
    }
    defaults.update(overrides)
    return defaults


def create_caption_track_payload(**overrides) -> dict:
    defaults = {
        "language": "en-US",
        "caption_format": "SRT",
        "speaker_id_style": "DASH",
    }
    defaults.update(overrides)
    return defaults


def create_qc_review_payload(**overrides) -> dict:
    defaults = {
        "review_mode": "FULL_REVIEW",
        "total_words": 10000,
        "minor_errors": 100,
        "major_errors": 0,
        "critical_errors": 0,
    }
    defaults.update(overrides)
    return defaults


def create_ad_track_payload(**overrides) -> dict:
    defaults = {
        "language": "en-US",
        "narrator_name": "Narrator One",
        "gaps": [{"start_ms": 1000, "end_ms": 21000}],
        "segments": [{"gap_index": 0, "duration_ms": 10000, "text": "d"}],
    }
    defaults.update(overrides)
    return defaults


def create_live_event_payload(**overrides) -> dict:
    defaults = {
        "title": "E",
        "channel_id": "CH1",
        "start_at": "2026-08-10T14:00:00Z",
        "end_at": "2026-08-10T15:00:00Z",
        "required_certification": "CERT_CBC",
    }
    defaults.update(overrides)
    return defaults


def create_stenographer_payload(**overrides) -> dict:
    defaults = {
        "display_name": "S1",
        "certification": "CERT_CBC",
        "certified_since": "2020-01-01T00:00:00Z",
        "cert_valid_until": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    defaults = {"severity": "MINOR", "description": "caption error"}
    defaults.update(overrides)
    return defaults


def create_conversion_job_payload(**overrides) -> dict:
    defaults = {"target_format": "WEBVTT"}
    defaults.update(overrides)
    return defaults
