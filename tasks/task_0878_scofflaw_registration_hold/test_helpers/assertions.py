"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CASE_STATUSES = ["COMPLIANT", "SCOFFLAW", "RESOLVED"]
HOLD_STATUSES = ["NO_HOLD", "HOLD_PLACED", "HOLD_RELEASED"]
VIOLATION_STATUSES = ["OUTSTANDING", "DISPUTED", "PAID", "WAIVED", "VOIDED", "IN_COLLECTIONS"]
DISPUTE_STATUSES = ["SUBMITTED", "SCHEDULED", "UPHELD", "DISMISSED", "WITHDRAWN"]
ORDER_STATUSES = ["DISPATCHED", "APPLIED", "RELEASED", "CANCELLED"]
PLAN_STATUSES = ["ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED"]
WAIVER_STATUSES = ["REQUESTED", "APPROVED", "DENIED"]
REFERRAL_STATUSES = ["REFERRED", "RECALLED", "SETTLED"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_owner(data: dict):
    _common_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["dmv_customer_id"], str) and data["dmv_customer_id"]
    assert data["hardship_status"] in ["NONE", "PENDING", "APPROVED"]


def assert_vehicle(data: dict):
    _common_versioned(data)
    assert isinstance(data["owner_id"], str)
    assert isinstance(data["hold_flag"], bool)
    assert data["registration_status"] in ["ACTIVE", "EXPIRED", "SUSPENDED"]


def assert_scofflaw_case(data: dict):
    _common_versioned(data)
    assert data["case_status"] in CASE_STATUSES
    assert data["hold_status"] in HOLD_STATUSES
    assert isinstance(data["outstanding_count"], int) and data["outstanding_count"] >= 0
    assert isinstance(data["assessed_balance_cents"], int) and data["assessed_balance_cents"] >= 0
    assert isinstance(data["collectible_balance_cents"], int) and data["collectible_balance_cents"] >= 0
    assert isinstance(data["eligible_for_boot"], bool)
    assert isinstance(data["eligible_for_tow"], bool)
    # Collectible view is a subset of the assessed view.
    assert data["collectible_balance_cents"] <= data["assessed_balance_cents"]


def assert_violation(data: dict):
    _common_versioned(data)
    assert data["status"] in VIOLATION_STATUSES
    assert isinstance(data["fine_amount_cents"], int) and data["fine_amount_cents"] >= 0
    assert isinstance(data["late_penalty_cents"], int) and data["late_penalty_cents"] >= 0
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0


def assert_dispute(data: dict):
    _common_versioned(data)
    assert data["status"] in DISPUTE_STATUSES
    assert isinstance(data["violation_id"], str)


def assert_boot_tow_order(data: dict):
    _common_versioned(data)
    assert data["status"] in ORDER_STATUSES
    assert data["action_type"] in ["BOOT", "TOW"]
    assert isinstance(data["release_fee_cents"], int) and data["release_fee_cents"] >= 0
    assert isinstance(data["release_fee_paid"], bool)


def assert_payment_plan(data: dict):
    _common_versioned(data)
    assert data["status"] in PLAN_STATUSES
    assert isinstance(data["installment_amount_cents"], int) and data["installment_amount_cents"] >= 0
    assert isinstance(data["paid_to_date_cents"], int) and data["paid_to_date_cents"] >= 0
    assert isinstance(data["missed_count"], int) and data["missed_count"] >= 0


def assert_hardship_waiver(data: dict):
    _common_versioned(data)
    assert data["status"] in WAIVER_STATUSES
    assert data["hardship_tier"] in ["TIER_1", "TIER_2"]
    assert isinstance(data["approved_amount_cents"], int) and data["approved_amount_cents"] >= 0


def assert_collections_referral(data: dict):
    _common_versioned(data)
    assert data["status"] in REFERRAL_STATUSES
    assert isinstance(data["referred_amount_cents"], int) and data["referred_amount_cents"] >= 0


# ---- append-only entities: id + created_at only, no version/updated_at ----

def assert_hearing_officer(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert "version" not in data, "HearingOfficer is append-only; must not carry version"


def assert_tow_yard(data: dict):
    _common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["occupied_slot_count"], int) and data["occupied_slot_count"] >= 0
    assert "version" not in data, "TowYard is append-only; must not carry version"


def assert_payment(data: dict):
    _common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data.get("allocation"), list)
    assert "version" not in data, "Payment is immutable; must not carry version"
