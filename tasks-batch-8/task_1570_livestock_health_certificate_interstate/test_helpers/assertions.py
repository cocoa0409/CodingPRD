"""Entity assertions and domain invariant checkers (PRD §2.6, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_CVI_RE = re.compile(r"^CVI-[A-Z]{2}-\d{6}$")
_PERMIT_RE = re.compile(r"^EP-[A-Z]{2}-\d{6}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_premises(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["county"], str) and data["county"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["species_code"] in ["CATTLE", "SWINE", "POULTRY", "SHEEP_GOAT", "EQUINE"]
    assert isinstance(data["initial_head_count"], int) and data["initial_head_count"] >= 0
    assert isinstance(data["current_head_count"], int)
    assert data["disease_status"] in [
        "ACCREDITED_FREE", "MONITORED", "QUARANTINE_HOLD", "INFECTED",
    ]


def assert_veterinarian(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["accreditation_number"], str) and data["accreditation_number"]
    assert is_iso8601_timestamp(data["accreditation_expires_at"])
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["is_credential_current"], bool)


def assert_entry_requirement(data: dict):
    _assert_common(data)
    assert isinstance(data["destination_state_code"], str)
    assert data["species_code"] in ["CATTLE", "SWINE", "POULTRY", "SHEEP_GOAT", "EQUINE"]
    assert data["test_type"] in ["BRUCELLOSIS", "TUBERCULOSIS", "EIA", "PULLORUM", "NONE"]
    assert isinstance(data["test_validity_days"], int) and data["test_validity_days"] > 0
    assert isinstance(data["vaccination_required"], bool)
    assert isinstance(data["vaccination_min_days_before_inspection"], int)
    assert data["vaccination_min_days_before_inspection"] >= 0
    assert isinstance(data["permit_required"], bool)
    assert is_iso8601_timestamp(data["effective_from"])
    assert data.get("effective_until") is None or is_iso8601_timestamp(data["effective_until"])
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_test_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["premises_id"])
    assert data["species_code"] in ["CATTLE", "SWINE", "POULTRY", "SHEEP_GOAT", "EQUINE"]
    assert data["test_type"] in ["BRUCELLOSIS", "TUBERCULOSIS", "EIA", "PULLORUM"]
    assert is_iso8601_timestamp(data["test_date"])
    assert isinstance(data["lab_reference"], str) and data["lab_reference"]
    assert data["result"] in ["RESULT_PENDING", "NEGATIVE", "POSITIVE"]


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["origin_premises_id"])
    assert isinstance(data["vet_id"], str) and data["vet_id"]
    assert isinstance(data["destination_state_code"], str)
    assert data["species_code"] in ["CATTLE", "SWINE", "POULTRY", "SHEEP_GOAT", "EQUINE"]
    assert isinstance(data["head_count"], int) and data["head_count"] > 0
    assert is_iso8601_timestamp(data["inspection_date"])
    assert data["status"] in [
        "DRAFT", "PENDING_REVIEW", "REJECTED", "ISSUED",
        "TRANSMITTED", "ENTRY_BLOCKED", "LAPSED", "VOID",
    ]
    assert data.get("pre_block_status") in (None, "ISSUED", "TRANSMITTED")
    if data.get("cvi_number") is not None:
        assert _CVI_RE.match(data["cvi_number"]), (
            f"cvi_number must match CVI-<state>-<6 digits>: {data['cvi_number']!r}"
        )
    for field in ("issued_at", "valid_until"):
        if data.get(field) is not None:
            assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"
    for field in ("provisional_fee_cents", "final_fee_cents"):
        if data.get(field) is not None:
            assert isinstance(data[field], int), f"{field} must be whole cents (int)"


def assert_movement_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["allocated_head_count"], int) and data["allocated_head_count"] > 0
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["status"] in ["REQUESTED", "ISSUED", "SUSPENDED", "VOIDED"]
    if data.get("permit_number") is not None:
        assert _PERMIT_RE.match(data["permit_number"]), (
            f"permit_number must match EP-<state>-<6 digits>: {data['permit_number']!r}"
        )
    assert isinstance(data["committed_headroom"], int)
    assert isinstance(data["projected_headroom"], int)
    assert isinstance(data["total_movement_fees_cents"], int)


def assert_movement_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["permit_id"])
    assert isinstance(data["head_count"], int) and data["head_count"] > 0
    assert isinstance(data["destination_name"], str) and data["destination_name"]
    assert is_iso8601_timestamp(data["planned_ship_date"])
    assert data["status"] in ["SCHEDULED", "IN_TRANSIT", "DELIVERED", "CANCELLED"]
    if data.get("departed_at") is not None:
        assert is_iso8601_timestamp(data["departed_at"])
    if data.get("arrived_at") is not None:
        assert is_iso8601_timestamp(data["arrived_at"])
    assert isinstance(data["movement_fee_cents"], int)


def assert_outbreak_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["county"], str) and data["county"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["disease_code"] in [
        "AVIAN_INFLUENZA", "BRUCELLOSIS", "TUBERCULOSIS", "EIA",
        "PULLORUM", "VESICULAR_STOMATITIS", "PSEUDORABIES",
    ]
    assert data["species_code"] in ["CATTLE", "SWINE", "POULTRY", "SHEEP_GOAT", "EQUINE"]
    assert data["severity"] in ["LOW", "MODERATE", "HIGH"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert data.get("effective_until") is None or is_iso8601_timestamp(data["effective_until"])
    assert data["status"] in ["MONITORING", "ACTIVE", "CONTAINED", "RESOLVED"]


def assert_quarantine_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["premises_id"])
    assert data["species_code"] in ["CATTLE", "SWINE", "POULTRY", "SHEEP_GOAT", "EQUINE"]
    assert data["disease_code"] in [
        "AVIAN_INFLUENZA", "BRUCELLOSIS", "TUBERCULOSIS", "EIA",
        "PULLORUM", "VESICULAR_STOMATITIS", "PSEUDORABIES",
    ]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["reason"], str) and data["reason"]
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert data["status"] in ["ACTIVE", "LIFTED", "EXPIRED"]


def assert_transmission_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["destination_state_code"], str)
    assert data["channel"] in ["XML_GATEWAY", "EMAIL", "PORTAL"]
    assert _SHA256_HEX_RE.match(data["payload_digest"]), (
        "payload_digest must be 64 lowercase hex chars (SHA-256, PRD §2.10)"
    )
    assert data["status"] in ["QUEUED", "ACKNOWLEDGED", "FAILED"]
    if data.get("acknowledged_at") is not None:
        assert is_iso8601_timestamp(data["acknowledged_at"])
