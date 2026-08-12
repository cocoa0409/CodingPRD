"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def _assert_audit_fields(data: dict):
    """Immutable audit records carry only id + created_at; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit record must not carry updated_at"
    assert "version" not in data, "audit record must not carry version"


def assert_donor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["donor_reference_code"], str) and data["donor_reference_code"]
    assert data["status"] in ["ENROLLED"]


def assert_consent_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("donor_id", "")), "donor_id must be a UUID"
    assert isinstance(data["permitted_uses"], list) and len(data["permitted_uses"]) > 0
    for use in data["permitted_uses"]:
        assert use in ["GENERAL_RESEARCH", "DISEASE_SPECIFIC", "GENETIC_ANALYSIS", "COMMERCIAL_USE"]
    assert isinstance(data["excluded_uses"], list)
    assert isinstance(data["allow_reidentification"], bool)
    assert data["status"] in ["ACTIVE", "WITHDRAWAL_PENDING", "WITHDRAWN", "SUPERSEDED"]


def assert_collection_kit(data: dict):
    _assert_common_fields(data)
    assert data["kit_type"] in ["BLOOD", "SALIVA", "TISSUE"]
    assert data["status"] in ["IN_STOCK", "DISTRIBUTED", "RETURNED", "CONSUMED", "EXPIRED"]


def assert_custody_event(data: dict):
    _assert_audit_fields(data)
    assert data["event_type"] in ["DISTRIBUTED", "RETURNED", "CONSUMED", "EXPIRED"]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]


def assert_specimen(data: dict):
    _assert_common_fields(data)
    assert data["specimen_type"] in ["BLOOD", "SALIVA", "TISSUE", "PLASMA"]
    assert data["lifecycle_status"] in ["ACCESSIONED", "IN_STORAGE", "DESTRUCTION_PENDING", "DESTROYED"]
    assert data["viability_status"] in ["USABLE", "QUARANTINED"]
    assert data["initial_volume_ml"] > 0


def assert_aliquot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "IN_STORAGE", "RESERVED", "QUARANTINED", "DESTRUCTION_PENDING",
        "DISTRIBUTED", "DESTROYED", "VOID",
    ]
    assert data["initial_volume_ml"] > 0


def assert_storage_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert data["posture"] in ["OPERATIONAL", "WARNING", "FAILURE"]


def assert_temperature_reading(data: dict):
    _assert_audit_fields(data)
    assert -100.0 <= data["temp_c"] <= 25.0, "temp_c must be within the plausible range"


def assert_storage_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["slot_code"], str) and data["slot_code"]
    assert data["capacity_ml"] > 0
    assert data["status"] in ["AVAILABLE", "OFFLINE"]


def assert_slot_reservation(data: dict):
    _assert_common_fields(data)
    assert data["purpose"] in ["MAINTENANCE", "TRANSFER_HOLD", "AUDIT"]
    assert data["status"] in ["BOOKED", "CANCELLED", "COMPLETED"]


def assert_sample_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED",
        "FULFILLED", "COMPROMISED", "REJECTED", "CANCELLED",
    ]
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)
    assert isinstance(data["handling_fee_cents"], int)


def assert_review_vote(data: dict):
    _assert_audit_fields(data)
    assert data["decision"] in ["APPROVE", "REJECT"]
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]


def assert_sharing_agreement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]
    assert data["total_committed_volume_ml"] > 0


def assert_deidentification_key(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "REVOKED"]
    assert isinstance(data["reveal_count"], int)


def assert_key_access_grant(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "EXPIRED"]
    assert isinstance(data["grantee_user_id"], str) and data["grantee_user_id"]


def assert_destruction_order(data: dict):
    _assert_common_fields(data)
    assert data["reason"] in ["CONSENT_WITHDRAWAL", "QUALITY_FAILURE", "OTHER"]
    assert data["status"] in ["PENDING", "COMPLETED"]


def assert_specimen_volume_invariant(specimen: dict, aliquots: list):
    """Invariant: initial == residual + SUM(child aliquot initial_volume_ml where status != VOID)."""
    live_sum = sum(a["initial_volume_ml"] for a in aliquots if a.get("status") != "VOID")
    assert specimen["residual_volume_ml"] == round(specimen["initial_volume_ml"] - live_sum, 3), (
        f"volume invariant violated: {specimen['initial_volume_ml']} != "
        f"{specimen['residual_volume_ml']} + {live_sum}"
    )


def assert_agreement_quota_invariant(agreement: dict):
    """Invariant: total_committed == remaining + reserved + fulfilled."""
    total = agreement["total_committed_volume_ml"]
    recon = round(
        agreement["remaining_volume_ml"]
        + agreement["reserved_volume_ml"]
        + agreement["fulfilled_volume_ml"],
        3,
    )
    assert round(total, 3) == recon, (
        f"quota invariant violated: {total} != remaining {agreement['remaining_volume_ml']} "
        f"+ reserved {agreement['reserved_volume_ml']} + fulfilled {agreement['fulfilled_volume_ml']}"
    )
