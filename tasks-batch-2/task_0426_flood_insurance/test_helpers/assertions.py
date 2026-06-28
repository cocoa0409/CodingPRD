"""Entity assertions and domain invariant checkers for the Flood Insurance API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Versioned, mutable record: id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments"


def assert_community(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["county_code"], str) and len(data["county_code"]) > 0
    assert isinstance(data["participating"], bool)
    assert isinstance(data["crs_class"], int) and 1 <= data["crs_class"] <= 10
    assert isinstance(data["crs_discount_pct"], (int, float))
    assert 0.0 <= data["crs_discount_pct"] <= 0.45


def assert_property(data: dict):
    assert_common_fields(data)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["owner_id"], str)
    assert isinstance(data["address"], str)
    assert data["flood_zone"] in ("VE", "AE", "X")
    assert isinstance(data["is_sfha"], bool)
    assert data["occupancy"] in ("PRIMARY_RESIDENCE", "NON_PRIMARY")
    assert isinstance(data["base_flood_elevation_ft"], (int, float))
    assert isinstance(data["has_active_mortgage"], bool)
    assert isinstance(data["loss_history_count"], int) and data["loss_history_count"] >= 0
    assert isinstance(data["is_repetitive_loss"], bool)
    assert data["compliance_status"] in ("NOT_REQUIRED", "COMPLIANT", "LAPSED")


def assert_elevation_certificate(data: dict):
    """ElevationCertificate is an immutable evidence record (PRD §2.4): only id +
    created_at; it must NOT carry updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["property_id"], str)
    assert isinstance(data["surveyor_license"], str)
    assert isinstance(data["lowest_floor_elevation_ft"], (int, float))
    assert isinstance(data["freeboard_ft"], (int, float))


def assert_policy(data: dict):
    assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["holder_id"], str)
    assert data["rating_method"] in ("RISK_RATING_2_0", "LEGACY_SUBSIDIZED")
    assert isinstance(data["building_coverage"], (int, float))
    assert isinstance(data["contents_coverage"], (int, float))
    assert data["status"] in (
        "QUOTED", "BOUND", "ACTIVE", "TRANSFERRED", "LAPSED", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data["quoted_premium"], (int, float))


def assert_claim(data: dict):
    assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["claimant_id"], str)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert isinstance(data["settlement_total"], (int, float))


def assert_proof_of_loss(data: dict):
    assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert data["review_status"] in ("PENDING", "ACCEPTED", "REJECTED")
    assert isinstance(data["days_after_loss"], int)


def assert_policy_transfer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["from_policy_id"], str)
    assert isinstance(data["new_owner_id"], str)
    assert isinstance(data["credited_amount"], (int, float))


# --- Domain invariant checkers ---

def assert_premium_conservation_on_cancel(policy: dict):
    """PRD §2.8 / §3.6: on cancellation earned_premium + refund == quoted_premium,
    and the credit balance is untouched (0)."""
    earned = policy["earned_premium"]
    quoted = policy["quoted_premium"]
    refund = quoted - earned
    assert earned + refund == quoted, "earned + refund must equal quoted_premium"
    assert policy["premium_credit_balance"] == 0, "cancel leaves credit balance at 0"


def assert_premium_conservation_on_transfer(policy: dict):
    """PRD §2.8 / §3.7: on transfer earned_premium + premium_credit_balance == quoted_premium."""
    earned = policy["earned_premium"]
    quoted = policy["quoted_premium"]
    credit = policy["premium_credit_balance"]
    assert earned + credit == quoted, (
        "earned + premium_credit_balance must equal quoted_premium"
    )
