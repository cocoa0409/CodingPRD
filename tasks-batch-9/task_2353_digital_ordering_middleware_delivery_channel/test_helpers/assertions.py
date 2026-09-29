"""Entity assertions and domain invariant checkers.

The per-entity helpers check the shape the PRD promises: the four
system-managed properties on first-class resources, the two-property shape of
append-only journal entries, and the enum vocabularies. The invariant helpers
check the identities the PRD states must hold for the whole life of a record.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BPS_DENOMINATOR,
    HANDOFF_GRACE_SECONDS,
    PENALTY_BAND_1_CENTS,
    PENALTY_BAND_2_CENTS,
    PENALTY_BAND_2_UPPER_SECONDS,
    PENALTY_BAND_3_CENTS,
    PENALTY_BAND_3_UPPER_SECONDS,
    PENALTY_BAND_4_CENTS,
    TIER_2_THRESHOLD_CENTS,
    TIER_3_THRESHOLD_CENTS,
    TIER_DISCOUNT_BPS,
    TIER_REBATE_BPS,
)

THROTTLE_STATES = ["NORMAL", "THROTTLED", "PAUSED"]
CHANNEL_TYPES = ["MARKETPLACE", "DIRECT", "AGGREGATOR"]
ROUNDING_MODES = ["CENT", "NICKEL"]
SETTLEMENT_MODES = ["GROSS_MODE", "NET_MODE"]
EIGHTY_SIX_POLICIES = ["HONOR_86", "IGNORE_86"]
THROTTLE_POLICIES = ["SUPPRESS_ON_THROTTLE", "IGNORE_THROTTLE"]
ADJUSTMENT_REVIEW_MODES = ["CHANNEL_REVIEW", "AUTO_ACCEPT"]
MENU_VERSION_STATES = ["DRAFT", "PUBLISHED", "EXHAUSTED", "SUPERSEDED"]
AVAILABILITY_STATES = ["AVAILABLE", "SUPPRESSED", "EIGHTY_SIXED", "THROTTLE_SUPPRESSED"]
EVENT_TYPES = ["EIGHTY_SIX", "RESTORE"]
FULFILLMENT_MODES = ["PICKUP", "DELIVERY"]
INJECTION_STATUSES = ["PENDING", "INJECTION_HELD", "ACCEPTED", "TABLET_FALLBACK", "FAILED"]
FULFILLMENT_STATUSES = ["PREPARING", "READY", "HANDED_OFF", "DELIVERED", "CANCELLED"]
SETTLEMENT_STATUSES = ["SETTLEABLE", "STATEMENT_ASSIGNED", "SETTLED"]
POS_RESULT_CODES = ["OK", "TIMEOUT", "PRINTER_DOWN", "MENU_MISMATCH"]
ATTEMPT_OUTCOMES = ["ACCEPTED", "REJECTED"]
NETWORK_TYPES = ["MARKETPLACE", "COURIER"]
ASSIGNMENT_STATES = ["OFFERED", "ACCEPTED", "DECLINED", "WITHDRAWN", "HANDED_OFF", "DELIVERED"]
ADJUSTMENT_TYPES = ["REFUND", "FEE_CREDIT"]
ADJUSTMENT_STATES = ["DRAFT", "CHANNEL_REVIEW", "REVISION_REQUESTED", "ACCEPTED", "REVERSED"]
STATEMENT_STATES = ["OPEN", "RECONCILED", "DISPUTED", "SETTLED"]
STATEMENT_TIERS = ["TIER_1", "TIER_2", "TIER_3"]


# --------------------------------------------------------------------------- #
# Shared property shapes
# --------------------------------------------------------------------------- #
def assert_common_fields(data: dict, label: str = "resource"):
    """A first-class resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict, label: str = "journal entry"):
    """An append-only journal entry carries only id and created_at — the
    `updated_at` and `version` keys are absent from its representation."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    assert "updated_at" not in data, f"{label} must not expose updated_at at all, got {data.get('updated_at')!r}"
    assert "version" not in data, f"{label} must not expose version at all, got {data.get('version')!r}"


# --------------------------------------------------------------------------- #
# First-class resources
# --------------------------------------------------------------------------- #
def assert_store(data: dict):
    assert_common_fields(data, "Store")
    assert isinstance(data["brand_code"], str) and data["brand_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert -720 <= data["timezone_offset_minutes"] <= 840
    assert 1 <= data["base_prep_minutes"] <= 60
    assert data["prep_capacity_per_bucket"] >= 1
    assert 1 <= data["pos_retry_limit"] <= 5
    assert data["tablet_backlog_threshold"] >= 1
    assert data["throttle_state"] in THROTTLE_STATES, f"unexpected throttle_state {data['throttle_state']!r}"
    assert data["open_order_count"] >= 0
    assert data["reserved_prep_slots"] >= 0
    assert data["tablet_backlog_count"] >= 0
    if data.get("last_published_at") is not None:
        assert is_iso8601_timestamp(data["last_published_at"])


def assert_channel(data: dict):
    assert_common_fields(data, "Channel")
    assert isinstance(data["code"], str) and data["code"]
    assert data["channel_type"] in CHANNEL_TYPES
    assert 0 <= data["markup_bps"] <= 5000
    assert data["rounding_mode"] in ROUNDING_MODES
    assert data["service_fee_cents"] >= 0
    assert 0 <= data["commission_bps"] <= 5000
    assert data["settlement_mode"] in SETTLEMENT_MODES
    assert data["eighty_six_policy"] in EIGHTY_SIX_POLICIES
    assert data["throttle_policy"] in THROTTLE_POLICIES
    assert data["adjustment_review_mode"] in ADJUSTMENT_REVIEW_MODES
    assert isinstance(data["accepts_delivery"], bool)
    assert data["listing_count"] >= 0


def assert_menu_version(data: dict):
    assert_common_fields(data, "MenuVersion")
    assert isinstance(data["brand_code"], str) and data["brand_code"]
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert data["state"] in MENU_VERSION_STATES
    assert data["item_count"] >= 0
    assert data["published_store_count"] >= 0
    if data.get("published_at") is not None:
        assert is_iso8601_timestamp(data["published_at"])
    if data.get("superseded_at") is not None:
        assert is_iso8601_timestamp(data["superseded_at"])


def assert_menu_item(data: dict):
    assert_common_fields(data, "MenuItem")
    assert is_valid_uuid(data["menu_version_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["base_price_cents"] > 0
    assert 0 <= data["tax_bps"] <= 2000
    assert isinstance(data["is_delivery_eligible"], bool)


def assert_channel_listing(data: dict):
    assert_common_fields(data, "ChannelListing")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["menu_item_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["base_price_cents"] > 0
    assert data["price_cents"] >= 0
    assert isinstance(data["suppressed"], bool)
    assert isinstance(data["eighty_sixed"], bool)
    assert data["availability_state"] in AVAILABILITY_STATES
    assert_listing_availability_ladder(data)


def assert_order(data: dict):
    assert_common_fields(data, "Order")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["channel_id"])
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert data["fulfillment_mode"] in FULFILLMENT_MODES
    assert data["injection_status"] in INJECTION_STATUSES
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert 0 <= data["bucket_index"] <= 95, f"bucket_index must be one of 96 daily buckets, got {data['bucket_index']}"
    assert is_iso8601_timestamp(data["promised_ready_at"])
    assert data["injection_attempt_count"] >= 0
    assert data["refunded_total_cents"] >= 0
    assert_order_money_identity(data)


def assert_courier_network(data: dict):
    assert_common_fields(data, "CourierNetwork")
    assert isinstance(data["code"], str) and data["code"]
    assert data["network_type"] in NETWORK_TYPES
    assert 1 <= data["priority_rank"] <= 99
    assert data["per_delivery_fee_cents"] >= 0
    assert 60 <= data["handoff_sla_seconds"] <= 7200
    assert 0 <= data["dispatch_buffer_seconds"] <= 3600
    assert 1 <= data["max_concurrent_assignments"] <= 20
    assert isinstance(data["is_active"], bool)
    assert data["open_assignment_count"] >= 0
    assert data["penalty_accrued_cents"] >= 0


def assert_delivery_assignment(data: dict):
    assert_common_fields(data, "DeliveryAssignment")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["courier_network_id"])
    assert data["state"] in ASSIGNMENT_STATES
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["occupancy_until"])
    assert isinstance(data["sla_breached"], bool)
    assert data["handoff_penalty_cents"] >= 0
    assert data["delivery_fee_cents"] >= 0
    for optional_instant in ("accepted_at", "handoff_deadline_at", "handoff_at", "delivered_at"):
        if data.get(optional_instant) is not None:
            assert is_iso8601_timestamp(data[optional_instant]), f"{optional_instant} must be ISO 8601"
    if data.get("handoff_lateness_seconds") is not None:
        assert data["handoff_lateness_seconds"] >= 0, "handoff_lateness_seconds is floored at zero"


def assert_adjustment(data: dict):
    assert_common_fields(data, "Adjustment")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["channel_id"])
    assert data["adjustment_type"] in ADJUSTMENT_TYPES
    assert data["amount_cents"] > 0, "amount_cents is strictly greater than zero"
    assert isinstance(data["reason_code"], str) and data["reason_code"]
    assert data["commission_relief_cents"] >= 0
    assert data["state"] in ADJUSTMENT_STATES
    assert data["revision_round"] >= 0
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]
    for optional_instant in ("accepted_at", "reversed_at"):
        if data.get(optional_instant) is not None:
            assert is_iso8601_timestamp(data[optional_instant])


def assert_remittance_statement(data: dict):
    assert_common_fields(data, "RemittanceStatement")
    assert is_valid_uuid(data["channel_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["state"] in STATEMENT_STATES
    assert data["tier"] in STATEMENT_TIERS
    assert data["order_count"] >= 0
    assert data["gross_sales_cents"] >= 0
    assert data["adjustment_total_cents"] >= 0
    assert data["tier_base_cents"] >= 0, "tier_base_cents is floored at zero"
    assert data["commission_cents"] >= 0
    assert data["rebate_cents"] >= 0
    assert data["open_adjustment_count"] >= 0
    if data.get("settled_at") is not None:
        assert is_iso8601_timestamp(data["settled_at"])
    assert_statement_tier_selection(data)


# --------------------------------------------------------------------------- #
# Append-only journal entries
# --------------------------------------------------------------------------- #
def assert_store_hour_window(data: dict):
    assert_append_only_fields(data, "StoreHourWindow")
    assert is_valid_uuid(data["store_id"])
    assert 0 <= data["day_of_week"] <= 6
    assert 0 <= data["opens_at_minute"] <= 1439
    assert 1 <= data["closes_at_minute"] <= 1440
    assert data["closes_at_minute"] > data["opens_at_minute"]
    assert data["window_minutes"] == data["closes_at_minute"] - data["opens_at_minute"], (
        "window_minutes is closes_at_minute minus opens_at_minute"
    )


def assert_availability_event(data: dict):
    assert_append_only_fields(data, "AvailabilityEvent")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["menu_item_id"])
    assert data["event_type"] in EVENT_TYPES
    assert is_iso8601_timestamp(data["effective_at"])
    assert data["propagated_listing_count"] >= 0
    assert data["skipped_listing_count"] >= 0
    assert data["held_order_count"] >= 0


def assert_order_line(data: dict):
    assert_append_only_fields(data, "OrderLine")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert 1 <= data["quantity"] <= 50
    assert data["base_price_cents"] > 0
    assert data["unit_price_cents"] >= 0
    assert 0 <= data["tax_bps"] <= 2000
    assert data["line_subtotal_cents"] == data["unit_price_cents"] * data["quantity"], (
        "line_subtotal_cents is unit_price_cents multiplied by quantity"
    )
    assert data["line_tax_cents"] == round_half_up(data["line_subtotal_cents"] * data["tax_bps"], BPS_DENOMINATOR), (
        "line_tax_cents is the line subtotal times tax_bps over 10,000, rounded half up once per line"
    )


def assert_pos_injection_attempt(data: dict):
    assert_append_only_fields(data, "PosInjectionAttempt")
    assert is_valid_uuid(data["order_id"])
    assert data["attempt_number"] >= 1, "attempt_number is 1-based within the order"
    assert is_iso8601_timestamp(data["attempted_at"])
    assert data["outcome"] in ATTEMPT_OUTCOMES, f"outcome must be ACCEPTED or REJECTED, got {data['outcome']!r}"


# --------------------------------------------------------------------------- #
# Instants
# --------------------------------------------------------------------------- #
def parse_instant(value: str) -> datetime:
    """Parse an emitted UTC instant. Fractional digits are optional on input."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: str, expected: str, label: str = "instant"):
    """Compare two instants by the moment they name, not by their spelling."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} expected {expected}, got {actual}"
    )


def minutes_between(earlier: str, later: str) -> float:
    """Whole and fractional minutes from the first instant to the second."""
    return (parse_instant(later) - parse_instant(earlier)).total_seconds() / 60.0


def seconds_between(earlier: str, later: str) -> float:
    return (parse_instant(later) - parse_instant(earlier)).total_seconds()


# --------------------------------------------------------------------------- #
# Domain invariants
# --------------------------------------------------------------------------- #
def round_half_up(numerator: int, denominator: int) -> int:
    """Exact rational division rounded half up to a whole cent."""
    return (2 * numerator + denominator) // (2 * denominator)


def assert_order_money_identity(order: dict):
    """`channel_collected_cents` always equals the sum of `brand_net_cents`,
    `commission_cents`, `service_fee_cents` and `refunded_total_cents`."""
    left = order["channel_collected_cents"]
    right = (
        order["brand_net_cents"]
        + order["commission_cents"]
        + order["service_fee_cents"]
        + order["refunded_total_cents"]
    )
    assert left == right, (
        "money identity broken: channel_collected_cents "
        f"{left} != brand_net_cents {order['brand_net_cents']} + commission_cents "
        f"{order['commission_cents']} + service_fee_cents {order['service_fee_cents']} "
        f"+ refunded_total_cents {order['refunded_total_cents']} = {right}"
    )


def assert_listing_availability_ladder(listing: dict):
    """Suppression outranks an 86, and an 86 outranks throttle suppression."""
    if listing["suppressed"]:
        assert listing["availability_state"] == "SUPPRESSED", (
            f"a suppressed listing reads SUPPRESSED, got {listing['availability_state']!r}"
        )
    elif listing["eighty_sixed"]:
        assert listing["availability_state"] == "EIGHTY_SIXED", (
            f"an unsuppressed 86-ed listing reads EIGHTY_SIXED, got {listing['availability_state']!r}"
        )


def assert_statement_tier_selection(statement: dict):
    """TIER_1 below 50,000 cents, TIER_2 from 50,000 up to 200,000, TIER_3 above."""
    base = statement["tier_base_cents"]
    if base < TIER_2_THRESHOLD_CENTS:
        expected = "TIER_1"
    elif base < TIER_3_THRESHOLD_CENTS:
        expected = "TIER_2"
    else:
        expected = "TIER_3"
    assert statement["tier"] == expected, (
        f"tier_base_cents {base} selects {expected}, got {statement['tier']!r}"
    )


def assert_statement_pipeline(statement: dict, commission_bps: int, settlement_mode: str):
    """Recompute the settlement pipeline from the statement's own aggregates."""
    tier_base = max(0, statement["gross_sales_cents"] - statement["adjustment_total_cents"])
    assert statement["tier_base_cents"] == tier_base, (
        f"tier_base_cents is gross_sales_cents minus adjustment_total_cents floored at zero: "
        f"expected {tier_base}, got {statement['tier_base_cents']}"
    )
    assert_statement_tier_selection(statement)
    tier = statement["tier"]
    effective_bps = max(0, commission_bps - TIER_DISCOUNT_BPS[tier])
    commission = round_half_up(tier_base * effective_bps, BPS_DENOMINATOR)
    rebate = round_half_up(tier_base * TIER_REBATE_BPS[tier], BPS_DENOMINATOR)
    assert statement["commission_cents"] == commission, (
        f"commission_cents expected {commission}, got {statement['commission_cents']}"
    )
    assert statement["rebate_cents"] == rebate, (
        f"rebate_cents expected {rebate}, got {statement['rebate_cents']}"
    )
    if settlement_mode == "GROSS_MODE":
        expected_net = tier_base + rebate
    else:
        expected_net = tier_base - commission + rebate
    assert statement["net_payable_cents"] == expected_net, (
        f"net_payable_cents under {settlement_mode} expected {expected_net}, "
        f"got {statement['net_payable_cents']}"
    )


def expected_handoff_penalty_cents(lateness_seconds: int) -> int:
    """The four-band penalty ladder, every band closed at its upper bound."""
    if lateness_seconds <= HANDOFF_GRACE_SECONDS:
        return PENALTY_BAND_1_CENTS
    if lateness_seconds <= PENALTY_BAND_2_UPPER_SECONDS:
        return PENALTY_BAND_2_CENTS
    if lateness_seconds <= PENALTY_BAND_3_UPPER_SECONDS:
        return PENALTY_BAND_3_CENTS
    return PENALTY_BAND_4_CENTS


def assert_handoff_penalty(assignment: dict):
    """Penalty and breach flag agree with the lateness the assignment reports."""
    lateness = assignment["handoff_lateness_seconds"]
    assert assignment["handoff_penalty_cents"] == expected_handoff_penalty_cents(lateness), (
        f"lateness {lateness}s expected penalty {expected_handoff_penalty_cents(lateness)}, "
        f"got {assignment['handoff_penalty_cents']}"
    )
    assert assignment["sla_breached"] is (lateness > HANDOFF_GRACE_SECONDS), (
        f"sla_breached must be true only when lateness is strictly greater than 300s, "
        f"got lateness {lateness} with sla_breached {assignment['sla_breached']}"
    )


def assert_store_counters(store: dict, open_order_count=None, reserved_prep_slots=None,
                          tablet_backlog_count=None):
    """Check the store's maintained derived counters."""
    if open_order_count is not None:
        assert store["open_order_count"] == open_order_count, (
            f"open_order_count expected {open_order_count}, got {store['open_order_count']}"
        )
    if reserved_prep_slots is not None:
        assert store["reserved_prep_slots"] == reserved_prep_slots, (
            f"reserved_prep_slots expected {reserved_prep_slots}, got {store['reserved_prep_slots']}"
        )
    if tablet_backlog_count is not None:
        assert store["tablet_backlog_count"] == tablet_backlog_count, (
            f"tablet_backlog_count expected {tablet_backlog_count}, got {store['tablet_backlog_count']}"
        )


def assert_quote_shape(quote: dict, expected_variant: str = None):
    """A quote reports its inputs and its promise."""
    for field in (
        "store_id", "channel_id", "variant", "load_count", "prep_minutes",
        "travel_minutes", "total_minutes", "bucket_index", "bucket_load", "quoted_ready_at",
    ):
        assert field in quote, f"quote must report {field}"
    assert quote["total_minutes"] == quote["prep_minutes"] + quote["travel_minutes"], (
        "total_minutes is the sum of prep_minutes and travel_minutes"
    )
    assert is_iso8601_timestamp(quote["quoted_ready_at"])
    if expected_variant is not None:
        assert quote["variant"] == expected_variant, (
            f"quote variant expected {expected_variant}, got {quote['variant']!r}"
        )


def assert_preview_shape(preview: dict):
    """The preview reports both settlement-mode outcomes side by side."""
    for field in (
        "statement_id", "settlement_mode", "gross_sales_cents", "adjustment_total_cents",
        "tier_base_cents", "tier", "effective_commission_bps", "commission_cents",
        "rebate_cents", "net_payable_cents", "gross_mode_net_payable_cents",
        "net_mode_net_payable_cents",
    ):
        assert field in preview, f"settlement preview must report {field}"
    assert preview["gross_mode_net_payable_cents"] == preview["tier_base_cents"] + preview["rebate_cents"]
    assert preview["net_mode_net_payable_cents"] == (
        preview["tier_base_cents"] - preview["commission_cents"] + preview["rebate_cents"]
    )
