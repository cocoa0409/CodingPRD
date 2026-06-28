"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape the PRD promises for that resource.
Append-only/config entities (CarePackage) intentionally omit version/updated_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-free UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["parity"], int) and data["parity"] >= 0
    assert isinstance(data["insurance_payer"], str)
    assert isinstance(data["policy_number"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_care_package(data: dict):
    # Config entity: only id + created_at, NO version / updated_at.
    assert is_valid_uuid(data.get("id", "")) or data.get("id") == data.get("code"), \
        "CarePackage id is its code"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "CarePackage is immutable: must carry no version"
    assert "updated_at" not in data, "CarePackage is immutable: must carry no updated_at"
    assert data["package_type"] in ("BIRTH", "POSTPARTUM", "COMBINED")
    assert isinstance(data["global_fee_cents"], int) and data["global_fee_cents"] >= 0


def assert_supply_kit(data: dict):
    _assert_common(data)
    assert isinstance(data["on_hand_count"], int) and data["on_hand_count"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["consumed_count"], int) and data["consumed_count"] >= 0
    # Availability invariant (PRD §2.10).
    available = data["on_hand_count"] - data["reserved_count"]
    assert available >= 0, f"available (on_hand - reserved) must stay >= 0, got {available}"


def assert_provider(data: dict):
    _assert_common(data)
    assert data["role_type"] in ("MIDWIFE", "DOULA")
    assert isinstance(data["max_active_episodes"], int) and data["max_active_episodes"] >= 1
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0
    assert data["status"] in ("AVAILABLE", "UNAVAILABLE")


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["turnover_minutes"], int) and data["turnover_minutes"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_episode(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in ("PLANNING", "ACTIVE", "TRANSFERRED", "BORN", "COMPLETED")
    assert data["financial_status"] in ("UNBILLED", "PLAN_ACTIVE", "SETTLED", "WRITTEN_OFF")
    assert data["risk_tier"] in ("LOW", "ELEVATED", "TRANSFER_REQUIRED")
    assert isinstance(data["kit_issued"], bool)
    assert isinstance(data["global_fee_cents"], int) and data["global_fee_cents"] >= 0
    assert isinstance(data["balance_due_cents"], int)
    assert data["balance_due_cents"] >= 0, "balance_due_cents is floored at zero"


def assert_prenatal_visit(data: dict):
    _assert_common(data)
    assert data["visit_kind"] in ("PRENATAL", "POSTPARTUM", "LACTATION")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_on_call_assignment(data: dict):
    _assert_common(data)
    assert data["coverage_role"] in ("PRIMARY", "BACKUP")
    assert data["status"] in ("ASSIGNED", "ON_DUTY", "RELEASED", "PROMOTED", "STOOD_DOWN")


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "CONFIRMED", "IN_USE", "COMPLETED", "TRANSFERRED", "CANCELLED")


def assert_insurance_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "ADJUDICATED", "DENIED", "VOID")
    assert isinstance(data["billed_amount_cents"], int)


def assert_charge(data: dict):
    _assert_common(data)
    assert data["charge_kind"] in ("GLOBAL_FEE", "EXTRA_VISIT", "SUPPLY", "TRANSFER_FEE")
    assert data["status"] in ("DRAFT", "BILLED", "PAID", "VOID")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["client_responsibility_cents"], int)


def assert_payment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PAID_OFF", "DEFAULTED", "CANCELLED")
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert data["total_cents"] == data["paid_cents"] + data["remaining_cents"], \
        "total_cents must equal paid_cents + remaining_cents"
