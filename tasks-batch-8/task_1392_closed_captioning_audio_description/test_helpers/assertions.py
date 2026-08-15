"""Entity assertions and small domain invariant helpers (PRD §2.2-§2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """Two timestamps denote the same instant (PRD pins three fractional digits)."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_client(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["compliance_standard"] in ["FCC_BROADCAST", "SECTION_508", "INTERNAL"]
    assert data["client_status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["ytd_completed_minutes"], int) and data["ytd_completed_minutes"] >= 0


def assert_media_asset(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["intake_status"] in ["RECEIVED", "INSPECTING", "CLEARED", "REJECTED_INTAKE"]
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] > 0
    assert data["frame_rate"] in [
        "FPS_23_976", "FPS_24", "FPS_25", "FPS_29_97_DF", "FPS_29_97_NDF", "FPS_30",
    ]


def assert_work_order(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["order_status"] in [
        "DRAFT", "QUOTED", "QUOTE_EXPIRED", "CONFIRMED", "IN_PRODUCTION",
        "READY_FOR_DELIVERY", "DELIVERED", "REMEDIATION", "CLIENT_ACCEPTED", "CANCELLED",
    ]
    assert data["service_type"] in ["CAPTIONS", "AUDIO_DESCRIPTION", "BUNDLE"]
    assert data["turnaround_tier"] in ["STANDARD", "EXPRESS", "RUSH", "SAME_DAY"]
    assert isinstance(data["active_complaint_count"], int) and data["active_complaint_count"] >= 0


def assert_caption_track(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["track_status"] in [
        "AUTHORING", "INTERNAL_REVIEW", "QC_QUEUED", "QC_PASSED", "QC_FAILED",
        "QC_FAILED_PERMANENT", "CONFORMED", "DELIVERED", "DISPUTED", "SUPERSEDED", "ARCHIVED",
    ]
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["qc_attempts"], int) and 0 <= data["qc_attempts"] <= 3
    assert data["caption_format"] in ["SCC", "WEBVTT", "TTML", "SRT"]


def assert_qc_review(data: dict):
    """Immutable measurement record: id + created_at only among common fields."""
    _assert_common(data)
    assert "updated_at" not in data, "QCReview must not carry updated_at"
    assert "version" not in data, "QCReview must not carry version"
    assert data["review_mode"] in ["FULL_REVIEW", "SAMPLED_REVIEW"]
    assert data["outcome"] in ["PASS", "FAIL"]
    assert isinstance(data["weighted_errors"], int)


def assert_ad_track(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["ad_status"] in [
        "SCRIPTING", "SCRIPT_REVIEW", "RECORDING", "MIX_QC",
        "CONFORMED", "DELIVERED", "DISPUTED", "ARCHIVED",
    ]


def assert_live_event(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["event_status"] in ["SCHEDULED", "BRIEFED", "ON_AIR", "WRAP", "SETTLED", "CANCELLED"]
    assert data["required_certification"] in ["CERT_CBC", "CERT_CART"]


def assert_stenographer(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["steno_status"] in ["ACTIVE", "SUSPENDED", "CERTIFICATION_LAPSED"]
    assert data["certification"] in ["CERT_CBC", "CERT_CART"]
    assert isinstance(data["make_up_minutes_credited"], int)
    assert isinstance(data["no_show_count"], int)


def assert_live_assignment(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["assignment_status"] in [
        "OFFERED", "ACCEPTED", "DECLINED", "OFFER_EXPIRED", "CONFIRMED",
        "LIVE", "COMPLETED", "NO_SHOW", "PREEMPTED", "CANCELLED",
    ]
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] > 0
    assert data["origin"] in ["MANUAL", "AUTO_OFFER"]


def assert_complaint(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["complaint_status"] in [
        "OPEN", "TRIAGED", "REMEDIATING", "RESOLVED", "DISMISSED", "REOPENED",
    ]
    assert data["severity"] in ["FCC_CRITICAL", "MAJOR", "MINOR"]
    assert isinstance(data["escalation_level"], int) and data["escalation_level"] >= 0


def assert_conversion_job(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["job_status"] in [
        "QUEUED", "CONVERTING", "VALIDATING", "COMPLETED", "FAILED_VALIDATION", "CANCELLED",
    ]
    assert isinstance(data["attempt_count"], int) and 0 <= data["attempt_count"] <= 3
    assert data["target_format"] in ["SCC", "WEBVTT", "TTML", "SRT"]


def assert_archive_item(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["archive_status"] in [
        "ACTIVE_HOLD", "COLD_STORE", "RESTORE_PENDING", "RESTORED_HOT", "PURGED",
    ]
    assert data["retention_class"] in ["REGULATED_BROADCAST", "LIVE_ONLY", "STANDARD"]
    subjects = [
        data.get("caption_track_id"),
        data.get("audio_description_track_id"),
        data.get("live_event_id"),
    ]
    assert sum(1 for s in subjects if s) == 1, "exactly one archive subject must be non-null"
