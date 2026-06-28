"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract.
Domain invariant checkers verify cross-field relationships that must hold after
any operation (e.g. the package-credit conservation identity).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version, per PRD Section 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["payer_mode"] in ("CASH", "INSURANCE")
    assert data["intake_status"] in ("PENDING_INTAKE", "INTAKE_COMPLETE")
    assert data["membership_status"] in ("NONE", "ACTIVE", "LAPSED")
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0
    assert isinstance(data["coinsurance_rate"], (int, float))
    assert 0.0 <= float(data["coinsurance_rate"]) <= 1.0


def assert_intake(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["tongue_finding"] in ("PALE", "RED", "PURPLE", "NORMAL")
    assert data["tongue_coating"] in ("THIN_WHITE", "THICK_YELLOW", "NONE", "GREASY")
    assert data["pulse_finding"] in ("WIRY", "SLIPPERY", "THREADY", "RAPID", "DEEP", "FLOATING")
    assert data["tcm_pattern"] in (
        "QI_STAGNATION", "BLOOD_DEFICIENCY", "DAMP_HEAT", "YANG_DEFICIENCY", "YIN_DEFICIENCY")
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_treatment_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["practitioner_id"])
    assert is_valid_uuid(data["intake_id"])
    assert isinstance(data["acupoints"], list)
    assert isinstance(data["planned_sessions"], int) and data["planned_sessions"] >= 1
    assert data["status"] in ("ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED")


def assert_package_series(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["total_credits"], int) and data["total_credits"] >= 1
    assert isinstance(data["price_paid_cents"], int)
    assert isinstance(data["reserved_credits"], int)
    assert isinstance(data["consumed_credits"], int)
    assert isinstance(data["provisional_remaining_credits"], int)
    assert isinstance(data["finalized_remaining_credits"], int)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "CANCELLED")


def assert_package_balance_identity(data: dict):
    """The conservation identity from PRD 3.4:
    total_credits == reserved_credits + consumed_credits + provisional_remaining_credits.
    """
    total = data["total_credits"]
    assert data["provisional_remaining_credits"] == (
        total - data["reserved_credits"] - data["consumed_credits"]), \
        "provisional = total - reserved - consumed must hold"
    assert data["finalized_remaining_credits"] == (
        total - data["consumed_credits"]), \
        "finalized = total - consumed must hold"


def assert_practitioner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert isinstance(data["turnover_buffer_minutes"], int)


def assert_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["room_name"], str) and len(data["room_name"]) > 0
    assert isinstance(data["cleanup_buffer_minutes"], int)


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["treatment_plan_id"])
    assert is_valid_uuid(data["practitioner_id"])
    assert is_valid_uuid(data["room_id"])
    assert data["charge_source"] in ("PER_VISIT", "PACKAGE")
    assert data["clinical_status"] in (
        "SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "BILLED", "WAIVED", "PENALTY_DUE")
    assert data["arrival_class"] in ("PENDING", "ON_TIME", "LATE")
    assert isinstance(data["base_fee_cents"], int)


def assert_addon(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert data["modality"] in ("CUPPING", "MOXA")
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("ATTACHED", "VOIDED")


def assert_herb_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["herb_name"], str) and len(data["herb_name"]) > 0
    assert isinstance(data["initial_grams"], int)
    assert isinstance(data["on_hand_grams"], int)
    assert isinstance(data["reorder_threshold_grams"], int)
    assert data["stock_status"] in ("IN_STOCK", "LOW_STOCK")


def assert_formula(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["formula_name"], str) and len(data["formula_name"]) > 0
    assert isinstance(data["line_items"], list)


def assert_dispense(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["treatment_plan_id"])
    assert is_valid_uuid(data["herbal_formula_id"])
    assert isinstance(data["doses"], int) and data["doses"] >= 1
    assert data["status"] in ("REQUESTED", "FILLED", "REVERSED")


def assert_charge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["cash_discount_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["charge_type"] in ("VISIT", "PENALTY")
    assert data["status"] in ("OPEN", "VOID")


def assert_superbill(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["line_charges_cents"], list)
    assert isinstance(data["insurance_allowed_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert data["status"] in ("ISSUED", "VOID")
