"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CAMPAIGN_STATUSES = ["DRAFT", "LIVE", "CLOSING", "SUCCESSFUL", "FAILED", "CANCELED"]
TIER_STATUSES = ["AVAILABLE", "SOLD_OUT", "RETIRED"]
PAYMENT_STATUSES = ["PENDING_AUTH", "AUTHORIZED", "CAPTURED", "AUTH_DECLINED", "REFUNDED"]
FULFILLMENT_STATUSES = ["NOT_STARTED", "SURVEY_SENT", "SURVEY_COMPLETE", "SHIPPED"]
PLEDGE_STATUSES = ["ACTIVE", "CANCELED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be int >= 1"


def assert_creator(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["payout_currency"], str) and len(data["payout_currency"]) > 0


def assert_backer(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["lifetime_authorized_cents"], int)
    assert isinstance(data["lifetime_captured_cents"], int)
    assert isinstance(data["declined_auth_count"], int)
    assert 0 <= data["reliability_score"] <= 100, "reliability_score must be in [0,100]"


def assert_campaign(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["title"], str)
    assert data["status"] in CAMPAIGN_STATUSES, f"unexpected campaign status {data['status']!r}"
    assert data["funding_model"] in ["ALL_OR_NOTHING", "FLEXIBLE"]
    assert isinstance(data["funding_goal_cents"], int) and data["funding_goal_cents"] > 0
    assert isinstance(data["committed_amount_cents"], int)


def assert_tier(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["claimed_quantity"], int) and data["claimed_quantity"] >= 0
    assert isinstance(data["weight_grams"], int) and data["weight_grams"] >= 0
    assert data["status"] in TIER_STATUSES, f"unexpected tier status {data['status']!r}"
    assert data["limit_quantity"] is None or data["limit_quantity"] > 0


def assert_stretch_goal(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["threshold_cents"], int) and data["threshold_cents"] > 0
    assert isinstance(data["unlocked"], bool)


def assert_addon_product(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["claimed_quantity"], int) and data["claimed_quantity"] >= 0
    assert isinstance(data["weight_grams"], int) and data["weight_grams"] >= 0
    assert data["limit_quantity"] is None or data["limit_quantity"] > 0


def assert_pledge(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["pledge_amount_cents"], int) and data["pledge_amount_cents"] > 0
    assert data["destination_zone"] in ["DOMESTIC", "INTL"]
    assert isinstance(data["items_subtotal_cents"], int)
    assert isinstance(data["shipping_cents"], int)
    assert isinstance(data["committed_amount_cents"], int)
    assert data["payment_status"] in PAYMENT_STATUSES
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert data["status"] in PLEDGE_STATUSES


def assert_pledge_addon(data: dict):
    """Append-only line: ONLY id + created_at among common fields (no updated_at/version)."""
    _assert_common(data)
    assert "updated_at" not in data, "PledgeAddOn is append-only and must not carry updated_at"
    assert "version" not in data, "PledgeAddOn is append-only and must not carry version"
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["line_total_cents"], int)


def assert_authorization(data: dict):
    """Append-only event: ONLY id + created_at among common fields."""
    _assert_common(data)
    assert "updated_at" not in data, "PaymentAuthorization is append-only and must not carry updated_at"
    assert "version" not in data, "PaymentAuthorization is append-only and must not carry version"
    assert data["outcome"] in ["SUCCEEDED", "DECLINED"]


def assert_refund(data: dict):
    """Append-only event: ONLY id + created_at among common fields."""
    _assert_common(data)
    assert "updated_at" not in data, "Refund is append-only and must not carry updated_at"
    assert "version" not in data, "Refund is append-only and must not carry version"
    assert data["reason"] in ["FAILED_CAMPAIGN", "BACKER_CANCEL"]
    assert isinstance(data["amount_cents"], int)


def assert_survey(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["completed"], bool)
