"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates structural shape (uuid id, ISO timestamps,
enum membership, field types). Invariant helpers verify ledger-conservation
rules that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CAMPAIGN_STATUSES = ["DRAFT", "OPEN", "CLOSED"]
_GIFT_STATUSES = ["RECORDED", "ACKNOWLEDGED", "RECEIPTED", "REFUNDED"]
_PLEDGE_STATUSES = ["ACTIVE", "DELINQUENT", "FULFILLED", "CANCELLED"]
_INSTALLMENT_STATUSES = ["DUE", "PAID", "WAIVED"]
_MATCH_STATUSES = ["SUBMITTED", "APPROVED", "PAID", "DENIED"]
_PLANNED_STATUSES = ["INTENT", "CONFIRMED", "REALIZED", "LAPSED"]
_LIFECYCLE_STATUSES = ["PROSPECT", "ACTIVE", "LAPSED", "REACTIVATED", "ARCHIVED"]
_GIVING_STATUSES = ["NONE", "ENTRY", "MID", "MAJOR"]
_POLICIES = ["FULL_TO_ALL", "SPLIT_EVEN", "PRIMARY_ONLY"]
_CHANNELS = ["EMAIL", "DIRECT_MAIL", "EVENT", "PHONE", "WEB"]
_FREQUENCIES = ["ONE_TIME", "MONTHLY", "QUARTERLY", "ANNUAL"]
_SCHEDULE_BASES = ["FRONT_LOADED", "BACK_LOADED"]
_PAYMENT_METHODS = ["CARD", "CHECK", "ACH", "CASH", "STOCK"]
_VEHICLES = ["BEQUEST", "CHARITABLE_TRUST", "LIFE_INSURANCE", "IRA_ROLLOVER"]
_ACK_KINDS = ["ACKNOWLEDGEMENT", "RECEIPT"]


def _assert_common(data: dict):
    """Standard audit fields for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["soft_credit_policy"] in _POLICIES
    assert isinstance(data["total_soft_credit_cents"], int) and data["total_soft_credit_cents"] >= 0
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0


def assert_donor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["lifecycle_status"] in _LIFECYCLE_STATUSES
    assert data["giving_status"] in _GIVING_STATUSES
    assert isinstance(data["lifetime_hard_credit_cents"], int) and data["lifetime_hard_credit_cents"] >= 0
    assert isinstance(data["lapse_threshold_days"], int) and 30 <= data["lapse_threshold_days"] <= 3650
    if data.get("last_gift_at") is not None:
        assert is_iso8601_timestamp(data["last_gift_at"]), "last_gift_at must be ISO 8601 when set"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["match_ratio"], (int, float)) and 0 < data["match_ratio"] <= 3.0
    assert isinstance(data["min_gift_cents"], int) and data["min_gift_cents"] >= 0
    assert isinstance(data["max_match_cents"], int) and data["max_match_cents"] >= 1
    assert isinstance(data["annual_match_cap_cents"], int) and data["annual_match_cap_cents"] >= 1


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["goal_cents"], int) and data["goal_cents"] >= 1
    assert data["status"] in _CAMPAIGN_STATUSES
    assert isinstance(data["raised_hard_cents"], int) and data["raised_hard_cents"] >= 0
    assert isinstance(data["raised_with_match_cents"], int) and data["raised_with_match_cents"] >= 0
    # raised_with_match is hard plus paid match, hence never below hard.
    assert data["raised_with_match_cents"] >= data["raised_hard_cents"], \
        "raised_with_match_cents must be >= raised_hard_cents"


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["campaign_id"])
    assert data["channel"] in _CHANNELS
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 40
    assert isinstance(data["attributed_gift_count"], int) and data["attributed_gift_count"] >= 0


def assert_pledge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["donor_id"])
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] >= 1
    assert isinstance(data["installment_count"], int) and 1 <= data["installment_count"] <= 60
    assert data["frequency"] in _FREQUENCIES
    assert data["schedule_basis"] in _SCHEDULE_BASES
    assert data["status"] in _PLEDGE_STATUSES
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert isinstance(data["installments_due_count"], int) and data["installments_due_count"] >= 0


def assert_pledge_installment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pledge_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert is_iso8601_timestamp(data["due_on"]), "due_on must be ISO 8601"
    assert data["status"] in _INSTALLMENT_STATUSES


def assert_gift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["donor_id"])
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["payment_method"] in _PAYMENT_METHODS
    assert data["status"] in _GIFT_STATUSES
    assert isinstance(data["deductible_amount_cents"], int) and data["deductible_amount_cents"] >= 0
    assert isinstance(data["benefit_value_cents"], int) and data["benefit_value_cents"] >= 0


def assert_match_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["gift_id"])
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] >= 0
    assert isinstance(data["matched_amount_cents"], int) and data["matched_amount_cents"] >= 0
    assert data["status"] in _MATCH_STATUSES


def assert_planned_gift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["donor_id"])
    assert data["vehicle"] in _VEHICLES
    assert isinstance(data["expected_amount_cents"], int) and data["expected_amount_cents"] >= 1
    assert data["status"] in _PLANNED_STATUSES


def assert_acknowledgement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["gift_id"])
    assert is_valid_uuid(data["donor_id"])
    assert data["kind"] in _ACK_KINDS


def assert_segment(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data["min_lifetime_cents"], int) and data["min_lifetime_cents"] >= 0
    assert isinstance(data["giving_status_in"], list)
    assert isinstance(data["lifecycle_status_in"], list)
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0


def assert_soft_credit(data: dict):
    """SoftCredit is append-only (common_fields:false): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "SoftCredit must NOT expose updated_at"
    assert "version" not in data, "SoftCredit must NOT expose version"
    assert is_valid_uuid(data["gift_id"])
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["beneficiary_donor_id"])
    assert isinstance(data["soft_credit_cents"], int) and data["soft_credit_cents"] >= 0
    assert isinstance(data["reversed"], bool)
