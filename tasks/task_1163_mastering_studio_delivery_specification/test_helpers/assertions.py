"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.4: every primary resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ("PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["account_credit_cents"], int)
    assert isinstance(data["lifetime_revision_count"], int)


def assert_engineer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["tier"] in ("JUNIOR", "STAFF", "SENIOR", "MASTER")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["capacity_minutes_per_day"], int) and data["capacity_minutes_per_day"] >= 0
    assert data["availability_status"] in ("AVAILABLE", "ON_LEAVE", "INACTIVE")
    assert isinstance(data["active_project_count"], int)


def assert_platform_profile(data: dict):
    _assert_common_fields(data)
    assert data["platform_code"] in (
        "SPOTIFY", "APPLE_MUSIC", "YOUTUBE_MUSIC", "TIDAL", "DEEZER",
        "BANDCAMP", "VINYL", "CD", "CLUB",
    )
    assert -30.0 <= data["integrated_lufs"] <= -5.0
    assert -6.0 <= data["true_peak_dbtp"] <= 0.0
    assert data["loudness_range_lu"] > 0
    assert isinstance(data["required_sample_rate_hz"], int)
    assert data["required_bit_depth"] in (16, 24, 32)
    assert data["container_format"] in (
        "WAV", "AIFF", "FLAC", "MP3_320", "AAC_256", "DDP", "VINYL_PREMASTER",
    )


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str) and data["client_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in (
        "DRAFT", "BOOKED", "INTAKE", "QC_PASSED", "MASTERING", "REVISION",
        "APPROVED", "DELIVERING", "DELIVERED", "ARCHIVED", "RECALLED", "CANCELLED",
    )
    assert isinstance(data["scheduled_duration_minutes"], int)
    assert isinstance(data["target_platform_profile_id"], str)
    assert data["rush_tier"] in ("STANDARD", "EXPRESS", "RUSH", "EMERGENCY")
    assert isinstance(data["revision_round_count"], int)


def assert_session_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["engineer_id"], str) and data["engineer_id"]
    assert is_iso8601_timestamp(data["slot_start_at"])
    assert is_iso8601_timestamp(data["slot_end_at"])
    assert data["status"] in ("HELD", "BOOKED", "RELEASED", "CONSUMED", "CANCELLED")


def assert_source_asset(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["filename"], str) and data["filename"]
    sha = data["sha256"]
    assert isinstance(sha, str) and len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha), "sha256 must be 64 lowercase hex chars"
    assert isinstance(data["sample_rate_hz"], int)
    assert isinstance(data["bit_depth"], int)
    assert data["duration_seconds"] > 0
    assert data["channels"] in (1, 2, 6, 8)
    assert data["qc_status"] in ("PENDING", "PASSED", "FAILED", "WAIVED")


def assert_revision_round(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["status"] in ("OPEN", "SUBMITTED", "APPROVED", "REJECTED", "EXPIRED")
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["deadline_at"])


def assert_deliverable(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["revision_round_id"], str) and data["revision_round_id"]
    assert data["deliverable_kind"] in (
        "DDP", "STEM_PACK", "INSTRUMENTAL", "MASTER_WAV", "MASTER_FLAC",
        "MASTER_AAC", "VINYL_PREMASTER",
    )
    assert isinstance(data["integrated_lufs"], (int, float))
    assert isinstance(data["true_peak_dbtp"], (int, float))
    assert isinstance(data["loudness_range_lu"], (int, float))
    assert isinstance(data["sample_rate_hz"], int)
    assert isinstance(data["bit_depth"], int)
    assert data["status"] in (
        "BUILDING", "QC_PENDING", "QC_FAILED", "READY", "EMBEDDED", "VERIFIED", "RETIRED",
    )


def assert_qc_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deliverable_id"], str) and data["deliverable_id"]
    assert data["check_code"] in (
        "LOUDNESS_IN_TOL", "TRUE_PEAK_IN_TOL", "LRA_IN_TOL", "FORMAT_MATCH",
        "ISRC_PRESENT", "UPC_MATCH", "CLIP_FREE", "DC_OFFSET_OK", "PHASE_COHERENT",
    )
    assert isinstance(data["passed"], bool)


def assert_metadata_tag(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deliverable_id"], str) and data["deliverable_id"]
    isrc = data["isrc"]
    assert isinstance(isrc, str) and len(isrc) == 12
    assert data["embedding_status"] in ("DRAFT", "EMBEDDED", "VERIFIED", "MISMATCH", "REVOKED")


def assert_archive_bundle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["storage_class"] in ("HOT", "WARM", "COLD", "GLACIER")
    assert isinstance(data["archive_size_bytes"], int) and data["archive_size_bytes"] >= 0
    assert data["recall_status"] in ("NONE", "PENDING", "RESTORING", "RESTORED", "FAILED")
    assert isinstance(data["recall_fee_cents"], int)


def assert_rush_tier_rule(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ("STANDARD", "EXPRESS", "RUSH", "EMERGENCY")
    assert isinstance(data["multiplier_bp"], int)
    assert data["sla_hours"] > 0
    assert isinstance(data["surcharge_breach_cents"], int)
    assert isinstance(data["included_revision_rounds"], int)
    assert isinstance(data["per_round_cents"], int)


def assert_client_credit_nonnegative(data: dict):
    """Domain invariant (PRD §2.7): no debit may drive the balance below zero."""
    assert data["account_credit_cents"] >= 0, "client balance must never go negative"
