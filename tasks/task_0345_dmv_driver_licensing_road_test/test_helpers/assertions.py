"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_driver_record(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["licensing_status"] in (
        "UNLICENSED", "ELIGIBLE", "ACTIVE", "SUSPENDED", "REVOKED",
    ), f"unexpected licensing_status {data.get('licensing_status')!r}"
    assert data["cdl_status"] in ("NONE", "ACTIVE", "MEDICALLY_DOWNGRADED")
    assert data["real_id_status"] in ("NONE", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["point_balance"], int) and data["point_balance"] >= 0
    assert isinstance(data["prior_suspension_count"], int) and data["prior_suspension_count"] >= 0
    assert isinstance(data["knowledge_test_passed"], bool)


def assert_examiner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certified_classes"], list)


def assert_knowledge_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED")
    assert isinstance(data["scheduled_period"], int)


def assert_road_test_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert is_valid_uuid(data.get("examiner_id", ""))
    assert data["status"] in ("BOOKED", "PROCTORED", "SCORED", "CANCELLED")
    assert data["license_class"] in ("D", "M", "A", "B", "C")


def assert_license(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert data["status"] in ("ISSUED", "RENEWED", "VOID")
    assert data["license_class"] in ("D", "M", "A", "B", "C")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_violation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert data["status"] in ("ACTIVE", "EXPIRED", "DISMISSED")
    assert isinstance(data["points"], int)


def assert_suspension(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert data["status"] in (
        "ACTIVE", "SERVED", "LIFTED_BY_REINSTATEMENT", "LIFTED_BY_DISMISSAL",
    )


def assert_cdl_endorsement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert data["status"] in ("GRANTED", "SUSPENDED", "WITHDRAWN")
    assert data["endorsement_code"] in ("H", "P", "S", "N", "T")


def assert_medical_card(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert data["status"] in ("VALID", "EXPIRED", "SUPERSEDED")


def assert_fee_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_record_id", ""))
    assert data["status"] == "CAPTURED"
    assert data["purpose"] in ("RENEWAL", "REINSTATEMENT", "ROAD_TEST", "KNOWLEDGE_TEST")
