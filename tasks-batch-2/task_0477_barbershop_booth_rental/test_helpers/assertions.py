"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields per PRD §2.5: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_shop(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["gross_service_revenue_cents"], int)
    assert isinstance(data["gross_product_revenue_cents"], int)


def assert_barber(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["comp_model"] in ("BOOTH_RENT", "COMMISSION")
    assert data["license_status"] in ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED")
    assert isinstance(data["unsettled_revenue_cents"], int)


def assert_chair(data: dict):
    _assert_common(data)
    assert data["status"] == "AVAILABLE"


def assert_shift(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_service(data: dict):
    _assert_common(data)
    assert data["status"] in ("LISTED", "DELISTED")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["duration_minutes"], int)


def assert_addon(data: dict):
    _assert_common(data)
    assert data["status"] in ("LISTED", "DELISTED")
    assert isinstance(data["price_cents"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert data["status"] in ("LISTED", "DELISTED")
    assert isinstance(data["stock_qty"], int)
    assert data["stock_qty"] >= 0, "stock_qty may never be negative"


def assert_membership(data: dict):
    _assert_common(data)
    assert data["status"] in ("OFFERED", "RETIRED")


def assert_customer(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["membership_status"] in ("NONE", "ACTIVE")
    assert isinstance(data["punch_count"], int)
    assert isinstance(data["reward_credits"], int)
    assert isinstance(data["no_show_strikes"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "BOOKED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED",
    )


def assert_queue_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ("WAITING", "SERVING", "DONE", "ABANDONED")


def assert_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PAID", "VOIDED")
    assert isinstance(data["service_net_cents"], int)
    assert isinstance(data["product_net_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_due_cents"], int)


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] == "FINALIZED"
    assert data["comp_model"] in ("BOOTH_RENT", "COMMISSION")


def assert_settlement_conserves_money(data: dict):
    """Forward split conserves gross: payout + shop take == tips + svc + prod."""
    lhs = data["barber_payout_cents"] + data["shop_commission_cents"]
    rhs = (
        data["tip_total_cents"]
        + data["service_revenue_cents"]
        + data["product_revenue_cents"]
    )
    assert lhs == rhs, f"money split not conserved: {lhs} != {rhs}"
