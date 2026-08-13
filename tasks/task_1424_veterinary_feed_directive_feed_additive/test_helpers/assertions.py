"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (or date-only string) into an aware UTC datetime.

    Handles 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SSZ', and millisecond forms.
    """
    assert isinstance(value, str) and value, f"Expected timestamp string, got {value!r}"
    text = value.strip()
    if "T" not in text:
        text = text + "T00:00:00Z"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_timestamp_equals(value: str, year, month, day, hour=0, minute=0, second=0):
    """Assert a timestamp string equals the given UTC instant (whole-minute precision)."""
    actual = parse_timestamp(value)
    expected = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    assert actual == expected, f"Expected {expected.isoformat()}, got {actual.isoformat()} (raw {value!r})"


def _assert_common_fields(data: dict):
    """PRD §2.4: every persisted resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_clinic(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["compliance_score"], int)
    assert isinstance(data["audit_ready"], bool)


def assert_veterinarian(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["clinic_id"], str) and data["clinic_id"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")


def assert_producer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["premise_id"], str) and data["premise_id"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DEBARRED")


def assert_animal_group(data: dict):
    _assert_common_fields(data)
    assert data["species"] in ("CATTLE", "SWINE", "POULTRY", "SHEEP", "GOAT")
    assert data["production_class"] in ("BEEF", "DAIRY", "LAYER", "BROILER", "BREEDING")
    assert isinstance(data["head_count"], int)
    assert isinstance(data["average_weight_lbs"], int)
    assert isinstance(data["earliest_market_date"], str) and data["earliest_market_date"]


def assert_drug(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["drug_code"], str) and data["drug_code"]
    assert isinstance(data["withdrawal_hours"], int)
    assert isinstance(data["allowed_species_classes"], list)
    assert isinstance(data["max_duration_days"], int)
    assert data["prohibited_extra_label"] is True


def assert_vcp_verification(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vet_id"], str) and data["vet_id"]
    assert isinstance(data["producer_id"], str) and data["producer_id"]
    assert is_iso8601_timestamp(data.get("verified_on", "")), "verified_on must be ISO 8601 UTC"
    assert isinstance(data["expires_on"], str) and data["expires_on"]
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_vfd_authorization(data: dict):
    _assert_common_fields(data)
    for field in ("producer_id", "animal_group_id", "vet_id", "drug_id"):
        assert isinstance(data[field], str) and data[field], f"{field} required"
    assert isinstance(data["authorized_animal_count"], int)
    assert isinstance(data["remaining_animal_count"], int)
    assert isinstance(data["feed_duration_days"], int)
    assert isinstance(data["issued_on"], str) and data["issued_on"]
    assert isinstance(data["expiration_date"], str) and data["expiration_date"]
    assert data["status"] in (
        "ISSUED", "PARTIALLY_USED", "FULLY_USED", "EXPIRED", "REVOKED", "SUPERSEDED",
    )


def assert_feed_mill(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fda_registration"], str) and data["fda_registration"]
    assert isinstance(data["pending_order_count"], int) and data["pending_order_count"] >= 0


def assert_feed_order(data: dict):
    _assert_common_fields(data)
    for field in ("feed_mill_id", "vfd_authorization_id", "producer_id"):
        assert isinstance(data[field], str) and data[field], f"{field} required"
    assert isinstance(data["animal_count"], int)
    assert isinstance(data["tons_of_feed"], int)
    assert isinstance(data["intended_use_label"], str)
    assert data["status"] in (
        "SUBMITTED", "VALIDATED", "SHIPPED", "DELIVERED", "CANCELLED", "REJECTED",
    )


def assert_feed_shipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["feed_order_id"], str) and data["feed_order_id"]
    assert isinstance(data["tons_shipped"], int)
    assert isinstance(data["shipped_at"], str) and data["shipped_at"]
    assert data["status"] in ("IN_TRANSIT", "DELIVERED", "RETURNED", "REJECTED_AT_RECEIPT")


def assert_withdrawal_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["feed_order_id"], str) and data["feed_order_id"]
    assert isinstance(data["provisional_market_date"], str) and data["provisional_market_date"]
    assert isinstance(data["withdrawal_window_hours"], int)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "VIOLATED")


def assert_distributor_acknowledgment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["feed_mill_id"], str) and data["feed_mill_id"]
    assert isinstance(data["distributor_name"], str) and data["distributor_name"]
    assert isinstance(data["covers_drug_id"], str) and data["covers_drug_id"]
    assert data["status"] in ("PENDING", "ACKNOWLEDGED", "LAPSED")


def assert_residue_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["producer_id"], str) and data["producer_id"]
    assert isinstance(data["feed_order_id"], str) and data["feed_order_id"]
    assert isinstance(data["detected_at"], str) and data["detected_at"]
    assert data["status"] in ("OPEN", "UNDER_INVESTIGATION", "CONFIRMED_VIOLATION", "DISMISSED")


def assert_audit_bundle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["producer_id"], str) and data["producer_id"]
    assert isinstance(data["window_start"], str) and data["window_start"]
    assert isinstance(data["window_end"], str) and data["window_end"]
    assert isinstance(data["required_record_count"], int) and data["required_record_count"] >= 0
    assert isinstance(data["produced_record_count"], int) and data["produced_record_count"] >= 0
    assert data["status"] in ("OPEN", "COMPLETE", "DEFICIENT")


def assert_clinic_invariants(data: dict):
    """PRD §2.9: audit_ready is true exactly when score >= 700 and no OPEN case exists.

    This checker validates only the score-side invariant, which must hold after
    any operation regardless of residue-case state.
    """
    assert isinstance(data["compliance_score"], int)
    if data["compliance_score"] < 700:
        assert data["audit_ready"] is False, (
            "audit_ready must be false when compliance_score < 700 (PRD §2.9)"
        )


def assert_vfd_quota_invariant(vfd: dict):
    """PRD §2.8: remaining_animal_count never exceeds authorized_animal_count."""
    assert 0 <= vfd["remaining_animal_count"] <= vfd["authorized_animal_count"], (
        f"remaining {vfd['remaining_animal_count']} outside [0, {vfd['authorized_animal_count']}]"
    )
