"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_owner(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert isinstance(data["legal_name"], str) and data["legal_name"]


def assert_guest(data: dict):
    _assert_common(data)
    assert data["status"] in ("UNSCREENED", "APPROVED", "BANNED")
    assert isinstance(data["government_id_verified"], bool)


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["vendor_type"] in ("CLEANER", "INSPECTOR", "MAINTENANCE", "GENERAL")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_property(data: dict):
    _assert_common(data)
    assert data["status"] in ("ONBOARDING", "LISTED", "UNLISTED", "OFFBOARDED")
    assert isinstance(data["base_nightly_rate_cents"], int)
    assert data["default_cancellation_policy"] in ("FLEXIBLE", "MODERATE", "STRICT")


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "REVOKED")


def assert_channel_listing(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SYNCED", "PAUSED", "DELISTED")
    assert data["channel"] in ("AIRBNB", "VRBO", "DIRECT", "BOOKING_COM")


def assert_pricing_rule(data: dict):
    _assert_common(data)
    assert data["rule_type"] in ("SEASONAL", "OCCUPANCY", "LAST_MINUTE", "MIN_STAY")
    assert isinstance(data["active"], bool)


def assert_booking(data: dict):
    _assert_common(data)
    assert data["stay_status"] in ("HOLD", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED")
    assert data["screening_status"] in ("PENDING", "APPROVED", "DECLINED")
    assert isinstance(data["nights"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["messages"], list)


def assert_turnover_task(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CLEANED", "INSPECTED", "FAILED", "CANCELLED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] in ("COMPLETED", "CANCELLED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "ASSIGNED", "IN_PROGRESS", "NEEDS_INFO", "COMPLETED", "APPROVED", "REJECTED")
    assert data["billable_to"] in ("OWNER", "GUEST", "COMPANY")
    assert isinstance(data["requires_owner_approval"], bool)


def assert_owner_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "PAID")


def assert_statement_line(data: dict):
    # Immutable ledger entry: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["line_type"] in (
        "RENTAL", "MGMT_FEE", "WORK_ORDER_CHARGE", "TAX_REMITTANCE", "CLEANING_PASS_THROUGH"
    )
    assert isinstance(data["amount_cents"], int)


def assert_review(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "PUBLISHED", "SUPPRESSED")
    assert 1 <= data["rating"] <= 5


def assert_statement_money_conservation(data: dict):
    """PRD §2.8 money-conservation invariant: gross rental minus management fee minus
    work-order owner charges equals the owner payout."""
    assert (
        data["gross_rental_cents"]
        - data["mgmt_fee_cents"]
        - data["work_order_owner_charges_cents"]
        == data["owner_payout_cents"]
    ), (
        "money-conservation invariant violated: "
        f"gross={data['gross_rental_cents']} mgmt={data['mgmt_fee_cents']} "
        f"wo={data['work_order_owner_charges_cents']} payout={data['owner_payout_cents']}"
    )
