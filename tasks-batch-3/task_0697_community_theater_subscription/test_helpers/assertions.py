"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape of a resource projection returned by
the API against the field set described in the PRD. Domain invariant checkers
guard ledger / inventory non-negativity (PRD §2.8, §3.8).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_SEASON_STATES = {"PLANNING", "RENEWAL_OPEN", "ON_SALE", "CLOSED"}
_PRODUCTION_STATES = {"DRAFT", "ANNOUNCED"}
_PERFORMANCE_STATES = {"DRAFT", "SCHEDULED", "ON_SALE", "SETTLED", "CANCELLED"}
_SUBSCRIPTION_STATES = {"DRAFT", "ACTIVE", "RENEWAL_PENDING", "RENEWED", "LAPSED", "CANCELLED"}
_SUB_SEAT_STATES = {"ASSIGNED", "RENEWAL_OFFERED", "RELEASED"}
_PAYMENT_STATES = {"UNPAID", "PAID", "REFUNDED"}
_FULFILLMENT_STATES = {"HELD", "ISSUED", "COLLECTED", "EXCHANGED", "VOID"}
_DONATION_STATES = {"PLEDGED", "FULFILLED", "REFUNDED"}
_EXCHANGE_STATES = {"REQUESTED", "COMPLETED", "DENIED"}
_AUDITION_STATES = {"SCHEDULED", "AUDITIONED", "CALLBACK", "CAST", "DECLINED"}
_DONOR_LEVELS = {"NONE", "FRIEND", "PATRON", "BENEFACTOR"}
_PRICE_TIERS = {"PREMIUM", "STANDARD", "VALUE"}
_ACCESSIBILITY = {"NONE", "ASL", "AUDIO_DESCRIPTION", "OPEN_CAPTION"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at creation and is >= 1"


def assert_season(data: dict):
    _assert_common(data)
    assert data["status"] in _SEASON_STATES, f"unexpected season status {data['status']}"
    assert isinstance(data["base_subscription_fee_cents"], int)
    assert data["base_subscription_fee_cents"] >= 0
    assert 0 <= data["loyalty_renewal_discount_pct"] < 1
    assert isinstance(data["released_seat_count"], int)
    assert data["released_seat_count"] >= 0


def assert_production(data: dict):
    _assert_common(data)
    assert data["status"] in _PRODUCTION_STATES
    assert isinstance(data["accessibility_offered"], list)
    for svc in data["accessibility_offered"]:
        assert svc in {"ASL", "AUDIO_DESCRIPTION", "OPEN_CAPTION"}


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["total_seat_count"], int)
    assert data["total_seat_count"] >= 0


def assert_seat(data: dict):
    _assert_common(data)
    assert data["price_tier"] in _PRICE_TIERS
    assert data["naming_status"] in {"UNNAMED", "NAMED"}
    assert isinstance(data["is_accessible"], bool)
    assert data["seat_number"] >= 1


def assert_performance(data: dict):
    _assert_common(data)
    assert data["status"] in _PERFORMANCE_STATES
    assert 0.5 <= data["demand_multiplier"] <= 3.0
    assert_performance_inventory_invariants(data)


def assert_patron(data: dict):
    _assert_common(data)
    assert data["donor_level"] in _DONOR_LEVELS
    assert isinstance(data["lifetime_donation_cents"], int)
    assert data["lifetime_donation_cents"] >= 0
    assert isinstance(data["account_credit_cents"], int)
    assert data["account_credit_cents"] >= 0, "account_credit_cents is floored at zero (PRD §3.8)"


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in _SUBSCRIPTION_STATES
    assert isinstance(data["is_renewal"], bool)
    assert isinstance(data["seat_count"], int)
    assert isinstance(data["total_price_cents"], int)


def assert_subscription_seat(data: dict):
    _assert_common(data)
    assert data["status"] in _SUB_SEAT_STATES
    assert isinstance(data["per_seat_price_cents"], int)


def assert_ticket(data: dict):
    _assert_common(data)
    assert data["payment_status"] in _PAYMENT_STATES
    assert data["fulfillment_status"] in _FULFILLMENT_STATES
    assert data["origin"] in {"SINGLE", "SUBSCRIPTION"}
    assert data["accessibility_service"] in _ACCESSIBILITY
    assert isinstance(data["price_cents"], int)


def assert_donation(data: dict):
    _assert_common(data)
    assert data["status"] in _DONATION_STATES
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 1


def assert_exchange(data: dict):
    _assert_common(data)
    assert data["status"] in _EXCHANGE_STATES
    assert data["mode"] in {"FLEX_PASS", "PAID_EXCHANGE"}
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["price_delta_cents"], int)
    assert data["price_delta_cents"] >= 0, "price_delta_cents is floored at zero (PRD §3.7)"


def assert_audition(data: dict):
    _assert_common(data)
    assert data["status"] in _AUDITION_STATES
    assert isinstance(data["is_volunteer"], bool)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_performance_inventory_invariants(data: dict):
    """Inventory figures are derived and self-consistent (PRD §2.8)."""
    assert data["held_seat_count"] >= 0
    assert data["sold_seat_count"] >= 0
    assert data["available_seat_count"] >= 0, "available_seat_count is floored at zero (PRD §2.8)"
    assert data["gross_sales_cents"] >= 0
