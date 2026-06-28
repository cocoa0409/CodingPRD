"""Entity assertions and domain invariant checkers for the jewelry-insurance API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version for mutable resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_policyholder(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["residence_zip"], str)
    assert data["status"] == "ACTIVE"


def assert_risk_zone(data: dict):
    """RiskZone is immutable: id + created_at only, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["zip_prefix"], str)
    assert data["risk_band"] in ["LOW", "MODERATE", "HIGH", "SEVERE"]
    assert isinstance(data["rate_per_thousand_cents"], int)


def assert_repair_shop(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["service_zip"], str)
    assert isinstance(data["in_network"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_policy(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["policyholder_id"], str)
    assert data["coverage_type"] in ["ALL_RISK", "NAMED_PERIL"]
    assert data["valuation_basis"] in ["AGREED_VALUE", "REPLACEMENT_COST"]
    assert data["deductible_option"] in ["ZERO", "LOW", "STANDARD", "HIGH"]
    assert data["coverage_status"] in [
        "QUOTED", "BOUND", "ACTIVE", "LAPSED", "CANCELLED"
    ]
    assert data["billing_status"] in ["UNBILLED", "PAID", "PAST_DUE"]


def assert_scheduled_item(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["description"], str)
    assert data["category"] in ["RING", "NECKLACE", "WATCH", "LOOSE_STONE", "OTHER"]
    assert isinstance(data["scheduled_value_cents"], int)
    assert data["item_status"] in ["PENDING", "ACTIVE", "SUSPENDED", "REMOVED"]


def assert_appraisal(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["policyholder_id"], str)
    assert isinstance(data["appraised_value_cents"], int)
    assert data["status"] in ["VALID", "EXPIRED", "SUPERSEDED"]


def assert_endorsement(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["policy_id"], str)
    assert data["endorsement_type"] in ["ADD_ITEM", "REMOVE_ITEM", "CHANGE_DEDUCTIBLE"]
    assert data["status"] in ["DRAFT", "APPLIED", "REJECTED"]


def assert_claim(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["scheduled_item_id"], str)
    assert data["peril"] in [
        "THEFT", "FIRE", "FLOOD", "ACCIDENTAL_DAMAGE", "MYSTERIOUS_DISAPPEARANCE"
    ]
    assert data["loss_type"] in ["TOTAL_LOSS", "PARTIAL_DAMAGE"]
    assert data["status"] in [
        "FNOL", "UNDER_REVIEW", "INFO_REQUESTED",
        "APPROVED", "DENIED", "SETTLED", "CLOSED",
    ]


def assert_repair_order(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["repair_shop_id"], str)
    assert isinstance(data["authorized_amount_cents"], int)
    assert data["status"] in [
        "ASSIGNED", "IN_PROGRESS", "REPAIRED", "DEEMED_TOTAL_LOSS", "CLOSED"
    ]


def assert_premium_payment(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["RECEIVED", "REVERSED"]
