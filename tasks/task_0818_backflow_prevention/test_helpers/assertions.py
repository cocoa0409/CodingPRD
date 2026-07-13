"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_POSTURES = {"COMPLIANT", "AT_RISK", "NON_COMPLIANT", "SHUTOFF"}
_TIERS = {"LOW", "MODERATE", "HIGH"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_connection(data: dict):
    _assert_common(data)
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["address"], str)
    assert isinstance(data["owner_user_id"], str)
    assert data["hazard_class"] in {"HIGH_HAZARD", "LOW_HAZARD"}
    assert data["compliance_posture"] in _POSTURES, \
        f"unexpected posture {data['compliance_posture']!r}"
    assert data["risk_tier"] in _TIERS, f"unexpected risk_tier {data['risk_tier']!r}"
    assert isinstance(data["water_service_active"], bool)
    for count in ("protected_device_count", "overdue_device_count",
                  "open_notice_count", "total_penalty_cents"):
        assert isinstance(data[count], int) and data[count] >= 0, \
            f"{count} must be a non-negative int, got {data[count]!r}"


def assert_device(data: dict):
    _assert_common(data)
    assert isinstance(data["service_connection_id"], str)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["device_type"] in {"RP", "DC", "PVB", "DCDA"}
    assert data["hazard_rating"] in {"HIGH", "LOW"}
    assert isinstance(data["test_interval_months"], int) and data["test_interval_months"] >= 1
    assert is_iso8601_timestamp(data["install_date"])
    assert data["status"] in {"ACTIVE", "NEEDS_REPAIR", "REPLACED", "REMOVED"}
    assert is_iso8601_timestamp(data["next_test_due_date"])


def assert_tester(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["certification_number"], str) and data["certification_number"]
    assert is_iso8601_timestamp(data["cert_effective_date"])
    assert is_iso8601_timestamp(data["cert_expiry_date"])
    assert data["status"] in {"ACTIVE", "SUSPENDED", "EXPIRED"}


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["tester_id"], str)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in {"BOOKED", "CANCELLED"}


def assert_report(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["tester_id"], str)
    assert is_iso8601_timestamp(data["test_date"])
    assert data["result"] in {"PASS", "FAIL"}
    assert data["status"] in {"SUBMITTED", "ACCEPTED", "REJECTED"}


def assert_survey(data: dict):
    _assert_common(data)
    assert isinstance(data["service_connection_id"], str)
    for score in ("premise_use_score", "chemical_exposure_score", "auxiliary_supply_score"):
        assert isinstance(data[score], int) and 0 <= data[score] <= 40
    assert data["status"] in {"DRAFT", "FINALIZED", "SUPERSEDED"}


def assert_notice(data: dict):
    _assert_common(data)
    assert isinstance(data["service_connection_id"], str)
    assert data["reason"] in {"OVERDUE_TEST", "FAILED_TEST", "UNREPAIRED_DEVICE"}
    assert data["status"] in {"ISSUED", "RESCINDED", "ENFORCED"}


def assert_repair_order(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert data["order_type"] in {"REPAIR", "REPLACEMENT"}
    assert data["status"] in {"OPEN", "COMPLETED", "CANCELLED"}
