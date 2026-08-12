"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_GRADES = ["A", "B", "C", "D", "F"]


def _assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601"
        )
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["school_year"], str) and data["school_year"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUMMER_COLLECTION", "CLOSED"]


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_external_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["grade_level"], int)
    assert isinstance(data["free_lunch_eligible"], bool)
    assert data["family_agreement_status"] in ["PENDING", "SIGNED", "DECLINED"]
    assert isinstance(data["insurance_enrolled"], bool)
    assert data["financial_posture"] in ["CLEAR", "FEES_OUTSTANDING", "SUSPENDED"]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["lifetime_damage_count"], int)
    assert data["status"] in ["ENROLLED", "WITHDRAWN", "GRADUATED"]


def assert_family_agreement(data: dict):
    # Write-once record: id + created_at only; no updated_at / version (PRD §2.5)
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["signature_state"] in ["PENDING", "SIGNED", "DECLINED"]
    assert "version" not in data, "FamilyAgreement must not carry version"
    assert "updated_at" not in data, "FamilyAgreement must not carry updated_at"


def assert_insurance_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["premium_cents"], int)
    assert isinstance(data["deductible_cents"], int)
    assert isinstance(data["coverage_cap_cents"], int)
    assert isinstance(data["academic_year"], str)
    assert data["status"] in ["QUOTED", "ACTIVE", "EXHAUSTED", "CANCELLED", "EXPIRED"]


def assert_fleet(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fleet_name"], str)
    assert data["asset_class"] in ["DEVICE", "TEXTBOOK"]
    assert isinstance(data["unit_replacement_cost_cents"], int)
    assert isinstance(data["salvage_value_cents"], int)
    assert isinstance(data["useful_life_months"], int)
    assert is_iso8601_timestamp(data["in_service_date"])


def assert_asset_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["asset_tag_barcode"], str)
    assert isinstance(data["serial_number"], str)
    assert data["condition_grade"] in _GRADES
    assert data["lifecycle_status"] in [
        "READY", "DEPLOYED", "IN_REPAIR", "LOANER", "SUMMER_INTAKE",
        "RE_IMAGING", "END_OF_LIFE", "DISPOSED", "DONATED", "WRITTEN_OFF",
    ]
    assert isinstance(data["depreciated_value_cents"], int)
    assert isinstance(data["months_in_service"], int)


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_account_id"])
    assert is_valid_uuid(data["asset_unit_id"])
    assert is_iso8601_timestamp(data["expected_return_date"])
    assert data["status"] in ["ACTIVE", "RETURNED", "OVERDUE", "LOST"]


def assert_damage_report(data: dict):
    _assert_common_fields(data)
    assert data["reported_by_role"] in ["FAMILY", "SITE_TECH", "SYSTEM"]
    assert data["damage_category"] in [
        "COSMETIC", "FUNCTIONAL", "LIQUID", "SCREEN", "LOSS", "THEFT",
    ]
    assert data["observed_condition_grade"] in _GRADES
    assert isinstance(data["provisional_fee_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "CONFIRMED", "DISMISSED"]


def assert_fee(data: dict):
    _assert_common_fields(data)
    assert data["fee_type"] in [
        "DAMAGE", "LATE_RETURN", "NON_RETURN", "INSURANCE_DEDUCTIBLE",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["waived_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in ["ASSESSED", "APPEALED", "SETTLED", "WAIVED", "WRITTEN_OFF"]


def assert_loaner_checkout(data: dict):
    _assert_common_fields(data)
    assert data["checkout_reason"] in ["REPAIR", "LOSS_PENDING", "NEW_ENROLLMENT"]
    assert isinstance(data["max_loaner_days"], int)
    assert data["status"] in ["OPEN", "RETURNED", "OVERDUE", "ESCALATED"]


def assert_lifecycle_event(data: dict):
    # Write-once record: id + created_at only; no updated_at / version (PRD §2.5)
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["event_type"] in [
        "INTAKE", "DEPLOY", "RETURN", "REPAIR_START", "REPAIR_COMPLETE",
        "RE_IMAGE", "RETIRE", "DISPOSE", "DONATE", "WRITE_OFF", "CORRECTION",
    ]
    assert "version" not in data, "AssetLifecycleEvent must not carry version"
    assert "updated_at" not in data, "AssetLifecycleEvent must not carry updated_at"


def assert_audit_sweep(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sweep_label"], str)
    assert isinstance(data["unaccounted_count"], int)
    assert data["status"] in ["DRAFT", "IN_PROGRESS", "RECONCILING", "CLOSED"]


def assert_fee_conservation(fee: dict):
    """Monetary invariant: no transition creates or destroys cents.

    paid_cents + waived_cents never exceed amount_cents, and both are
    non-negative integers of cents (PRD §2.6, §3.7).
    """
    assert fee["paid_cents"] >= 0
    assert fee["waived_cents"] >= 0
    assert fee["paid_cents"] + fee["waived_cents"] <= fee["amount_cents"], (
        f"paid ({fee['paid_cents']}) + waived ({fee['waived_cents']}) "
        f"exceeds amount ({fee['amount_cents']})"
    )
