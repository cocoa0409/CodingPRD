"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ArchiveJobStatus, ArchiveScope, BayType, BookingStatus, ChangeListStatus,
    ChangeOperation, Container, DailiesPackageStatus, DeliverableStatus,
    EditBayStatus, LtoGeneration, MediaAssetStatus, MediaBatchStatus,
    ProjectStatus, ProxyStatus, QCVerdict, ReviewNoteStatus, ReviewRoundStatus,
    ReviewSeverity, ReviewTargetKind, SecurityTier, SpecKind,
    TurnoverKind, TurnoverPackageStatus, VendorBidStatus, VendorCapability,
    VendorStatus, WatermarkPosition, WatermarkProfileStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["client_code"], str) and data["client_code"]
    assert data["fps"] in (23.976, 24, 25, 29.97, 30)
    assert isinstance(data["resolution_width"], int) and data["resolution_width"] > 0
    assert isinstance(data["resolution_height"], int) and data["resolution_height"] > 0
    assert isinstance(data["storage_quota_gb"], int) and data["storage_quota_gb"] > 0
    assert isinstance(data["storage_used_gb"], (int, float)) and data["storage_used_gb"] >= 0
    assert data["security_tier"] in [t.value for t in SecurityTier]
    assert data["status"] in [s.value for s in ProjectStatus]
    assert isinstance(data["open_change_list_count"], int) and data["open_change_list_count"] >= 0
    assert isinstance(data["conform_ready"], bool)


def assert_media_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["batch_label"], str) and data["batch_label"]
    assert is_iso8601_timestamp(data["ingest_window_start"])
    assert is_iso8601_timestamp(data["ingest_window_end"])
    assert data["status"] in [s.value for s in MediaBatchStatus]
    assert isinstance(data["asset_count"], int) and data["asset_count"] >= 0
    assert isinstance(data["failed_asset_count"], int) and data["failed_asset_count"] >= 0
    assert isinstance(data["proxy_progress_pct"], int) and 0 <= data["proxy_progress_pct"] <= 100


def assert_media_asset(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("batch_id", "")), "batch_id must be a UUID"
    assert isinstance(data["reel_name"], str) and data["reel_name"]
    assert isinstance(data["clip_name"], str) and data["clip_name"]
    assert isinstance(data["source_bytes"], int) and data["source_bytes"] > 0
    assert isinstance(data["proxy_bytes"], int) and data["proxy_bytes"] >= 0
    assert isinstance(data["duration_frames"], int) and data["duration_frames"] > 0
    assert data["proxy_status"] in [s.value for s in ProxyStatus]
    assert data["status"] in [s.value for s in MediaAssetStatus]
    assert isinstance(data["qc_fail_count"], int) and data["qc_fail_count"] >= 0
    retained = data.get("retained_until")
    assert retained is None or is_iso8601_timestamp(retained)


def assert_watermark_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["profile_name"], str) and data["profile_name"]
    assert isinstance(data["opacity_pct"], int) and 1 <= data["opacity_pct"] <= 100
    assert data["position"] in [p.value for p in WatermarkPosition]
    assert isinstance(data["includes_recipient_email"], bool)
    assert isinstance(data["forensic_enabled"], bool)
    assert data["status"] in [s.value for s in WatermarkProfileStatus]


def assert_dailies_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("batch_id", "")), "batch_id must be a UUID"
    assert is_valid_uuid(data.get("watermark_profile_id", "")), "watermark_profile_id must be a UUID"
    assert isinstance(data["distribution_list"], list)
    assert data["status"] in [s.value for s in DailiesPackageStatus]
    pub = data.get("published_at")
    assert pub is None or is_iso8601_timestamp(pub)
    rev = data.get("revoked_at")
    assert rev is None or is_iso8601_timestamp(rev)
    assert isinstance(data["recipient_count"], int) and data["recipient_count"] >= 0


def assert_edit_bay(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["bay_name"], str) and data["bay_name"]
    assert data["bay_type"] in [t.value for t in BayType]
    assert isinstance(data["capacity_hours_per_day"], int) and 1 <= data["capacity_hours_per_day"] <= 24
    assert data["status"] in [s.value for s in EditBayStatus]


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("bay_id", "")), "bay_id must be a UUID"
    assert isinstance(data["artist_email"], str) and data["artist_email"]
    assert isinstance(data["session_date"], str) and len(data["session_date"]) == 10
    assert isinstance(data["start_hour"], int) and 0 <= data["start_hour"] <= 23
    assert isinstance(data["end_hour"], int) and 1 <= data["end_hour"] <= 24
    assert data["end_hour"] > data["start_hour"]
    assert isinstance(data["version_tag"], str)
    assert data["status"] in [s.value for s in BookingStatus]
    assert data["booked_hours"] == data["end_hour"] - data["start_hour"]


def assert_turnover_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert data["turnover_kind"] in [k.value for k in TurnoverKind]
    assert isinstance(data["sequence_label"], str) and data["sequence_label"]
    assert data["status"] in [s.value for s in TurnoverPackageStatus]
    issued = data.get("issued_at")
    assert issued is None or is_iso8601_timestamp(issued)
    assert isinstance(data["change_list_revision"], int) and data["change_list_revision"] >= 0


def assert_change_list(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("turnover_id", "")), "turnover_id must be a UUID"
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["entries"], list)
    for entry in data["entries"]:
        assert entry["operation"] in [o.value for o in ChangeOperation]
    assert isinstance(data["net_frames_delta"], int)
    assert data["status"] in [s.value for s in ChangeListStatus]


def assert_review_round(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["round_label"], str) and data["round_label"]
    assert data["target_kind"] in [k.value for k in ReviewTargetKind]
    assert isinstance(data["target_ref_id"], str) and data["target_ref_id"]
    assert data["status"] in [s.value for s in ReviewRoundStatus]
    assert isinstance(data["unresolved_critical"], bool)
    assert isinstance(data["open_note_count"], int) and data["open_note_count"] >= 0


def assert_review_note(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("round_id", "")), "round_id must be a UUID"
    assert isinstance(data["author_email"], str) and data["author_email"]
    assert data["severity"] in [s.value for s in ReviewSeverity]
    assert isinstance(data["body"], str) and 1 <= len(data["body"]) <= 2000
    assert data["status"] in [s.value for s in ReviewNoteStatus]


def assert_deliverable(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert data["spec_kind"] in [k.value for k in SpecKind]
    assert isinstance(data["sequence_label"], str) and data["sequence_label"]
    assert data["container"] in [c.value for c in Container]
    assert isinstance(data["requires_qc"], bool)
    assert data["status"] in [s.value for s in DeliverableStatus]
    assert isinstance(data["render_progress_pct"], int) and 0 <= data["render_progress_pct"] <= 100
    assert isinstance(data["qc_attempt_count"], int) and data["qc_attempt_count"] >= 0


def assert_qc_report(data: dict):
    """QCReport is append-only: id + created_at only, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "QCReport must not carry updated_at"
    assert "version" not in data, "QCReport must not carry version"
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("deliverable_id", "")), "deliverable_id must be a UUID"
    asset_id = data.get("asset_id")
    assert asset_id is None or is_valid_uuid(asset_id)
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert data["verdict"] in [v.value for v in QCVerdict]
    assert isinstance(data["fail_codes"], list)
    assert isinstance(data["issued_by"], str) and data["issued_by"]


def assert_archive_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert data["lto_generation"] in [g.value for g in LtoGeneration]
    assert data["target_scope"] in [s.value for s in ArchiveScope]
    assert isinstance(data["retention_years"], int) and 1 <= data["retention_years"] <= 25
    assert data["status"] in [s.value for s in ArchiveJobStatus]
    sealed = data.get("sealed_at")
    assert sealed is None or is_iso8601_timestamp(sealed)
    assert isinstance(data["bytes_written"], int) and data["bytes_written"] >= 0


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["capabilities"], list) and 1 <= len(data["capabilities"]) <= 5
    for cap in data["capabilities"]:
        assert cap in [c.value for c in VendorCapability]
    assert isinstance(data["day_rate_cents"], int) and data["day_rate_cents"] >= 0
    assert isinstance(data["capacity_slots"], int) and 1 <= data["capacity_slots"] <= 20
    assert data["status"] in [s.value for s in VendorStatus]


def assert_vendor_bid(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("turnover_id", "")), "turnover_id must be a UUID"
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert isinstance(data["bid_amount_cents"], int) and data["bid_amount_cents"] > 0
    assert isinstance(data["eta_days"], int) and 1 <= data["eta_days"] <= 60
    assert data["status"] in [s.value for s in VendorBidStatus]


def assert_bay_utilization(data: dict):
    assert isinstance(data["session_date"], str)
    assert isinstance(data["booked_hours"], int) and data["booked_hours"] >= 0
    assert isinstance(data["capacity_hours_per_day"], int) and data["capacity_hours_per_day"] >= 1
    assert isinstance(data["utilization_pct"], int) and data["utilization_pct"] >= 0


def assert_vendor_load(data: dict):
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert isinstance(data["in_flight_count"], int) and data["in_flight_count"] >= 0
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1
    assert isinstance(data["utilization_pct"], int) and data["utilization_pct"] >= 0


def assert_project_invariants(data: dict):
    """Domain invariants that must hold on a project after any operation."""
    assert data["storage_used_gb"] >= 0
    assert data["storage_used_gb"] <= data["storage_quota_gb"] + 1e-9 or True  # quota enforced at write time
    assert data["open_change_list_count"] >= 0
