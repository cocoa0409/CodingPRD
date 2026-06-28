"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware datetime instant.

    The PRD pins the three-fractional-digit format only for `created_at`,
    `updated_at`, and `api_request_timestamp` (§2.2, §2.4). It does NOT pin a
    serialization for clock-derived domain timestamps such as `due_at` or
    `last_skin_check_at` (§3.2/§3.5 specify only the *instant* — "the clock's
    current time" / "twelve months after the clock's current time"). A faithful
    PRD-only implementer may echo the clock value verbatim (no fractional digits)
    or normalize to three fractional digits; both are PRD-consistent. So domain
    timestamps are compared by INSTANT, never by exact string form.
    """
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """Assert two ISO 8601 strings denote the same UTC instant (format-agnostic)."""
    assert is_iso8601_timestamp(actual), f"{actual!r} must be a valid ISO 8601 timestamp"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npi"], str)
    assert isinstance(data["can_perform_mohs"], bool)
    assert isinstance(data["active"], bool)


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["room_kind"] in ["STANDARD", "MOHS_SUITE"]
    assert isinstance(data["turnover_buffer_minutes"], int)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["has_active_insurance"], bool)
    assert isinstance(data["insurance_coinsurance_rate"], (int, float))
    assert isinstance(data["insurance_deductible_remaining_cents"], int)
    assert data["insurance_deductible_remaining_cents"] >= 0


def assert_encounter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be valid UUID"
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be valid UUID"
    assert data["visit_type"] in ["MEDICAL", "SKIN_CHECK", "COSMETIC"]
    assert data["clinical_status"] in [
        "SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "CLINICALLY_CLOSED", "CANCELLED"
    ]
    assert data["billing_status"] in ["BILLING_OPEN", "BILLING_FINALIZED", "BILLING_VOID"]
    assert data["pay_path"] in ["INSURANCE", "CASH"]
    assert isinstance(data["open_biopsy_count"], int)
    assert data["open_biopsy_count"] >= 0


def assert_biopsy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("encounter_id", "")), "encounter_id must be valid UUID"
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be valid UUID"
    assert isinstance(data["body_site"], str)
    assert data["status"] in ["COLLECTED", "AT_LAB", "RESULTED", "SIGNED_OUT", "CANCELLED"]
    if data.get("result") is not None:
        assert data["result"] in ["BENIGN", "MALIGNANT", "INDETERMINATE"]


def assert_procedure_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be valid UUID"
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be valid UUID"
    assert is_valid_uuid(data.get("encounter_id", "")), "encounter_id must be valid UUID"
    assert data["procedure_kind"] in ["EXCISION", "MOHS"]
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED"]


def assert_prior_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be valid UUID"
    assert isinstance(data["drug_name"], str)
    assert isinstance(data["required_step_count"], int)
    assert isinstance(data["list_price_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "DENIED"]
    assert isinstance(data["satisfied_step_count"], int)
    assert isinstance(data["submission_round"], int)


def assert_cosmetic_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be valid UUID"
    assert data["tier"] in ["SILVER", "GOLD"]
    assert isinstance(data["purchased_unit_cents"], int)
    assert isinstance(data["unit_balance_cents"], int)
    assert data["unit_balance_cents"] >= 0, "wallet balance must never go negative"
    assert data["status"] in ["PENDING", "ACTIVE", "EXHAUSTED", "CANCELLED"]


def assert_cosmetic_treatment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("encounter_id", "")), "encounter_id must be valid UUID"
    assert is_valid_uuid(data.get("membership_id", "")), "membership_id must be valid UUID"
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["redeemed_cents"], int)
    assert isinstance(data["out_of_pocket_cents"], int)
    assert data["redeemed_cents"] >= 0
    assert data["out_of_pocket_cents"] >= 0


def assert_charge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be valid UUID"
    assert is_valid_uuid(data.get("encounter_id", "")), "encounter_id must be valid UUID"
    assert data["source_kind"] in ["ENCOUNTER", "COSMETIC_TREATMENT", "PROCEDURE_BOOKING"]
    assert data["charge_kind"] in ["OFFICE_VISIT", "PROCEDURE", "BIOLOGIC", "COSMETIC"]
    assert isinstance(data["billed_amount_cents"], int)
    assert data["pay_path"] in ["INSURANCE", "CASH"]
    assert isinstance(data["patient_responsibility_cents"], int)
    assert isinstance(data["insurer_responsibility_cents"], int)
    assert isinstance(data["deductible_applied_cents"], int)
    assert data["status"] in ["POSTED", "PAID", "VOIDED"]


def assert_recall_reminder(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be valid UUID"
    assert data["reason"] in ["ROUTINE_SKIN_CHECK", "BIOPSY_FOLLOWUP"]
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert data["status"] in ["PENDING", "SENT", "DISMISSED"]


def assert_skin_exam_photo(data: dict):
    """Append-only entity: carries only id + created_at (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
