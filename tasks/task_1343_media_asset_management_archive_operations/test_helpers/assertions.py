"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every resource carries id / created_at / updated_at / version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_staff_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["department"], str)
    assert isinstance(data["active"], bool)


def assert_ingest_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["batch_name"], str)
    assert isinstance(data["source_department"], str)
    assert data["status"] in ("OPEN", "FINALIZED")
    assert isinstance(data["asset_count"], int) and data["asset_count"] >= 0


def assert_asset(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("ingest_batch_id", ""))
    assert isinstance(data["title"], str)
    assert data["media_type"] in ("VIDEO", "AUDIO", "FILM", "PHOTO", "DOCUMENT")
    assert data["format_class"] in (
        "BETACAM_SP", "UMATIC", "VHS", "FILM_16MM", "AUDIO_REEL", "AUDIO_DAT",
        "DIGITAL_FILE", "PRORES_FILE",
    )
    assert data["catalog_status"] in (
        "METADATA_DRAFT", "IN_REVIEW", "CATALOGED", "ARCHIVED",
        "DISPOSAL_SCHEDULED", "DISPOSED",
    )
    assert data["storage_tier"] in ("ONLINE", "NEARLINE", "DEEP_ARCHIVE")
    assert data["rights_posture"] in ("CLEARED", "RESTRICTED", "EXPIRED")
    assert data["hold_status"] in ("HELD", "CLEAR")


def assert_proxy_rendition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["rendition_type"] in ("PROXY_LOWRES", "PROXY_HIGHRES")
    assert data["status"] in ("QUEUED", "RENDERING", "READY", "FAILED")
    assert isinstance(data["retry_count"], int) and data["retry_count"] >= 0


def assert_rights_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["grant_type"] in ("BROADCAST", "STREAMING", "SYNDICATION", "ARCHIVAL_ONLY")
    assert data["territory"] in ("DOMESTIC", "REGIONAL", "GLOBAL")
    assert isinstance(data["exclusive"], bool)
    assert isinstance(data["restriction_flags"], list)
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_legal_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert isinstance(data["matter_reference"], str)
    assert isinstance(data["placed_by_user_id"], str)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_retention_policy(data: dict):
    _assert_common(data)
    assert data["media_type"] in ("VIDEO", "AUDIO", "FILM", "PHOTO", "DOCUMENT")
    assert isinstance(data["min_retention_years"], int)


def assert_disposal_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert isinstance(data["created_by_user_id"], str)
    assert isinstance(data["pinned_asset_version"], int)
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "EXECUTED",
        "REJECTED", "WITHDRAWN", "BLOCKED",
    )


def assert_retrieval_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert isinstance(data["requester_id"], str)
    assert data["purpose"] in ("BROADCAST", "INTERNAL_REVIEW", "EXHIBITION")
    assert data["delivery_tier"] in ("STANDARD", "EXPEDITE")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "RECALLING", "STAGED",
        "DELIVERED", "REJECTED", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0


def assert_usage_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert isinstance(data["reported_by_id"], str)
    assert data["usage_type"] in ("BROADCAST", "REBROADCAST", "STREAMING", "PROMO")
    assert isinstance(data["market_size"], int) and data["market_size"] > 0
    assert isinstance(data["duration_seconds_used"], int) and data["duration_seconds_used"] > 0
    assert data["status"] in ("REPORTED", "VERIFIED", "ROYALTY_POSTED", "DISPUTED")


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["rights_holder"], str)
    assert data["status"] in ("OPEN", "CLOSED", "POSTED")
    assert isinstance(data["event_ids"], list)
    assert isinstance(data["total_verified_seconds"], int)


def assert_migration_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["target_tier"] in ("ONLINE", "NEARLINE", "DEEP_ARCHIVE")
    assert data["status"] in (
        "QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED",
        "HOLD_PAUSED", "SUPERSEDED", "CANCELLED",
    )
    assert isinstance(data["retry_count"], int) and data["retry_count"] >= 0


def assert_digitization_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["output_format"] in ("PRORES_FILE", "H264_FILE")
    assert data["status"] in (
        "QUEUED", "ASSIGNED", "DIGITIZING", "QC_REVIEW",
        "COMPLETED", "QC_FAILED", "CANCELLED",
    )
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["priority_score"], int)


def assert_workstation(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["supported_formats"], list)
    assert data["status"] in ("ACTIVE", "MAINTENANCE")
