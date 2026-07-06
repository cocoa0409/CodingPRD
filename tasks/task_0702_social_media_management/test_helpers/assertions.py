"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

VALID_CLIENT_STATUS = {"ONBOARDING", "ACTIVE", "SUSPENDED", "CHURNED"}
VALID_PACKAGE_STATUS = {"DRAFT", "ACTIVE", "SUPERSEDED"}
VALID_CHANNEL_STATUS = {"PENDING", "CONNECTED", "LIVE", "DISCONNECTED"}
VALID_CONTENT_STATUS = {
    "DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED",
    "SCHEDULED", "PUBLISHED", "ARCHIVED",
}
VALID_TARGET_STATE = {"PENDING", "PUBLISHED", "FAILED", "SKIPPED"}
VALID_SLOT_STATUS = {"RESERVED", "FIRED", "RELEASED"}
VALID_BOOST_STATUS = {"DRAFT", "RESERVED", "RUNNING", "COMPLETED", "CANCELLED"}
VALID_CONVERSATION_STATUS = {"OPEN", "ASSIGNED", "RESOLVED", "ESCALATED"}
VALID_COLLAB_STATUS = {"PROPOSED", "COUNTERED", "ACCEPTED", "DELIVERED", "CLOSED", "CANCELLED"}
VALID_ASSET_STATUS = {"SUBMITTED", "RIGHTS_CLEARED", "REJECTED"}
VALID_LEDGER_TYPE = {"RETAINER_CHARGE", "BOOST_RESERVE", "BOOST_RELEASE", "BOOST_SPEND"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # Lightweight records carry no updated_at and no version.
    assert "updated_at" not in data, "lightweight record must not carry updated_at"
    assert "version" not in data, "lightweight record must not carry version"


def assert_client(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_CLIENT_STATUS, f"bad client status {data['status']}"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for f in (
        "retainer_fee_cents", "boost_budget_limit_cents", "boost_reserved_cents",
        "boost_spent_cents", "boost_available_cents", "monthly_post_quota",
        "posts_published_this_cycle", "current_cycle_index",
    ):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["boost_available_cents"] >= 0, "boost_available_cents never below zero"


def assert_client_budget_conservation(data: dict):
    """While the budget is non-negative, the limit equals reserved + spent + available."""
    if data["boost_available_cents"] > 0:
        assert data["boost_budget_limit_cents"] == (
            data["boost_reserved_cents"] + data["boost_spent_cents"] + data["boost_available_cents"]
        ), "budget conservation invariant violated"
    assert data["boost_available_cents"] >= 0


def assert_retainer_package(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_PACKAGE_STATUS
    assert data["tier"] in {"STARTER", "GROWTH", "SCALE"}


def assert_channel(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_CHANNEL_STATUS
    assert data["platform"] in {"FACEBOOK", "INSTAGRAM", "X", "LINKEDIN", "TIKTOK"}
    assert isinstance(data["min_publish_gap_minutes"], int)


def assert_content_item(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_CONTENT_STATUS
    assert isinstance(data["revision_round"], int)


def assert_content_target(data: dict):
    _assert_common(data)
    assert data["publish_state"] in VALID_TARGET_STATE


def assert_schedule_slot(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_SLOT_STATUS


def assert_boost_campaign(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_BOOST_STATUS
    for f in ("reserved_budget_cents", "spent_budget_cents", "days_elapsed", "current_day_spent_cents"):
        assert isinstance(data[f], int)


def assert_conversation(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_CONVERSATION_STATUS
    assert data["kind"] in {"DM", "COMMENT"}


def assert_influencer_collab(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_COLLAB_STATUS
    assert isinstance(data["negotiation_round"], int)
    assert isinstance(data["approved_asset_count"], int)


def assert_ugc_asset(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_ASSET_STATUS


def assert_engagement_message(data: dict):
    _assert_lightweight(data)
    assert data["direction"] in {"INBOUND", "OUTBOUND"}


def assert_analytics_snapshot(data: dict):
    _assert_lightweight(data)


def assert_ledger_entry(data: dict):
    _assert_lightweight(data)
    assert data["entry_type"] in VALID_LEDGER_TYPE
