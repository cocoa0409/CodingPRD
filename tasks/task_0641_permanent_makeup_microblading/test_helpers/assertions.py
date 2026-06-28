"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates response structure against the PRD contract.
Append-only records (ConsentRecord, DepositTransaction, HealingLog) carry only
id + created_at and must NOT expose updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_studio(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["min_client_age"], int) and data["min_client_age"] >= 18
    assert isinstance(data["sterile_kit_total"], int) and data["sterile_kit_total"] >= 0
    assert isinstance(data["sterile_kit_consumed"], int) and data["sterile_kit_consumed"] >= 0
    assert isinstance(data["sterile_kit_available"], int) and data["sterile_kit_available"] >= 0
    assert data["compliance_posture"] in ("OPEN", "RESTRICTED", "FROZEN")


def assert_studio_kit_conservation(data: dict):
    """Kit conservation invariant: consumed + available == total while consumed
    does not exceed total; available is never negative."""
    assert data["sterile_kit_available"] >= 0
    if data["sterile_kit_consumed"] <= data["sterile_kit_total"]:
        assert (
            data["sterile_kit_consumed"] + data["sterile_kit_available"]
            == data["sterile_kit_total"]
        )


def assert_technician(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["license_status"] in (
        "LICENSE_ACTIVE",
        "LICENSE_SUSPENDED",
        "LICENSE_EXPIRED",
    )


def assert_client(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["risk_score"], int)
    assert data["risk_band"] in ("STANDARD", "HIGH_RISK")
    assert isinstance(data["medical_cleared"], bool)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["client_status"] in ("ACTIVE", "BLOCKED")


def assert_patch_test(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ("APPLIED", "READ", "VOIDED")
    assert is_iso8601_timestamp(data.get("applied_at", "")), "applied_at must be ISO 8601"


def assert_color_formula(data: dict):
    _assert_common_mutable(data)
    assert data["procedure_type"] in ("BROWS", "EYELINER", "LIP_BLUSH")
    assert isinstance(data["pigment_count"], int) and data["pigment_count"] >= 1


def assert_appointment(data: dict):
    _assert_common_mutable(data)
    assert data["procedure_type"] in ("BROWS", "EYELINER", "LIP_BLUSH")
    assert data["appointment_kind"] in ("INITIAL", "TOUCH_UP", "ANNUAL_REFRESH", "REDO")
    assert data["lifecycle_status"] in (
        "BOOKED",
        "IN_PROCEDURE",
        "HEALING",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
        "VOIDED",
    )
    assert data["payment_status"] in (
        "AWAITING_DEPOSIT",
        "DEPOSIT_PAID",
        "BALANCE_DUE",
        "PAID_IN_FULL",
        "REFUNDED",
    )
    assert isinstance(data["session_price_cents"], int)
    assert isinstance(data["deposit_required_cents"], int)


def assert_package_order(data: dict):
    _assert_common_mutable(data)
    assert data["pricing_mode"] in ("PAYG", "BUNDLE")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")
    assert isinstance(data["package_price_cents"], int)


def assert_redo_request(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in (
        "REQUESTED",
        "APPROVED",
        "DENIED",
        "SCHEDULED",
        "FULFILLED",
    )


def assert_consent_record(data: dict):
    _assert_append_only(data)
    assert data["consent_type"] in (
        "PROCEDURE_CONSENT",
        "MEDICAL_DISCLOSURE",
        "PHOTO_RELEASE",
    )


def assert_deposit_transaction(data: dict):
    _assert_append_only(data)
    assert data["txn_type"] in ("CHARGE", "REFUND", "FORFEIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_healing_log(data: dict):
    _assert_append_only(data)
    assert data["outcome_flag"] in ("GOOD", "POOR")
    assert isinstance(data["day_offset"], int) and data["day_offset"] >= 0
