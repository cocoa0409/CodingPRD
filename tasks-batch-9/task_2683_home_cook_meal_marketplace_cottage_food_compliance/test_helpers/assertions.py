"""PRD-specific assertion helpers: envelope shape, per-entity field checks and
the domain invariants of PRD 2.12.

These raise AssertionError with the offending value in the message so a failure
identifies the field, not just the test.
"""

import math
import re
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMMISSION_RATE_TIER_1,
    COMMISSION_RATE_TIER_2,
    COMMISSION_RATE_TIER_3,
    COMMISSION_TIER_1_CEILING_CENTS,
    COMMISSION_TIER_2_CEILING_CENTS,
    DINER_SERVICE_FEE_PCT,
    SPOILAGE_RESERVE_PCT,
)

_REQ_ID = re.compile(r"^req_[A-Za-z0-9]+$")


# ---------------------------------------------------------------- arithmetic
def round_half_up(value: float) -> int:
    """PRD 2.8: a rate applied to a cent amount is rounded half up to a whole
    cent, and the rounding is applied to the exact product."""
    return int(math.floor(value + 0.5))


def ceil_meals(value: float) -> int:
    """PRD 2.8: a meal count multiplied by a rate is rounded up to the next
    whole meal, and a product of zero rounds to zero."""
    return int(math.ceil(value - 1e-9))


def expected_diner_service_fee_cents(subtotal_cents: int) -> int:
    return round_half_up(subtotal_cents * DINER_SERVICE_FEE_PCT)


def expected_commission_rate(ytd_gross_sales_cents: int) -> float:
    """PRD 3.5: boundaries are inclusive-below and exclusive-at."""
    if ytd_gross_sales_cents < COMMISSION_TIER_1_CEILING_CENTS:
        return COMMISSION_RATE_TIER_1
    if ytd_gross_sales_cents < COMMISSION_TIER_2_CEILING_CENTS:
        return COMMISSION_RATE_TIER_2
    return COMMISSION_RATE_TIER_3


def expected_commission_cents(subtotal_cents: int, rate: float) -> int:
    return round_half_up(subtotal_cents * rate)


def expected_spoilage_reserve_meals(committed_meals: int) -> int:
    return ceil_meals(committed_meals * SPOILAGE_RESERVE_PCT)


# ------------------------------------------------------------------ envelope
def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """PRD 2.2: the api_request_id is a server-generated unique identifier for
    the request that starts with `req_`."""
    meta = body["meta"]
    assert _REQ_ID.match(meta["api_request_id"]), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO 8601: {meta['api_request_timestamp']!r}"
    )


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """PRD 2.4: every resource carries a server-minted UUID `id`, a `created_at`,
    an `updated_at` and an integer `version` starting at 1."""
    assert is_valid_uuid(entity.get("id", "")), f"id must be a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be ISO 8601: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be ISO 8601: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int) and not isinstance(entity["version"], bool), (
        f"version must be an integer: {entity['version']!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert a set of field values in one call, reporting every mismatch."""
    problems: List[str] = []
    for field, want in expected.items():
        got = entity.get(field, "<absent>")
        if got != want:
            problems.append(f"{field}: expected {want!r}, got {got!r}")
    assert not problems, "; ".join(problems)


def assert_money_is_integer(entity: Dict[str, Any], *fields: str) -> None:
    """PRD 2.8: there are no floating-point currency amounts anywhere in a
    request or a response."""
    for field in fields:
        value = entity.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r} "
            f"({type(value).__name__})"
        )


# --------------------------------------------------------------- per entity
def assert_cook(cook: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(cook)
    assert_money_is_integer(
        cook,
        "ytd_gross_sales_cents",
        "ytd_cottage_revenue_cents",
        "pending_payout_cents",
        "lifetime_paid_cents",
    )
    assert_fields(cook, **expected)


def assert_cook_dimensions(
    cook: Dict[str, Any], onboarding_status: str, compliance_standing: str
) -> None:
    """PRD 2.7: a Cook's onboarding_status and compliance_standing are two
    independent status dimensions on the same row."""
    assert_fields(
        cook, onboarding_status=onboarding_status, compliance_standing=compliance_standing
    )


def assert_onboarding_document(document: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(document)
    assert_fields(document, **expected)


def assert_menu_item(menu_item: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(menu_item)
    assert_money_is_integer(menu_item, "unit_price_cents")
    assert_fields(menu_item, **expected)


def assert_production_window(window: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(window)
    assert_fields(window, **expected)


def assert_delivery_zone(zone: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(zone)
    assert_fields(zone, **expected)


def assert_pickup_hub(hub: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(hub)
    assert_fields(hub, **expected)


def assert_order(order: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(order)
    assert_money_is_integer(
        order,
        "unit_price_cents_snapshot",
        "subtotal_cents",
        "diner_service_fee_cents",
        "cold_chain_surcharge_cents",
        "total_charge_cents",
        "platform_commission_cents",
        "cook_earnings_cents",
        "refunded_cents",
        "cook_chargeback_cents",
        "commission_reversed_cents",
        "platform_absorbed_cents",
    )
    assert_fields(order, **expected)


def assert_order_dimensions(
    order: Dict[str, Any], fulfillment_status: str, payment_status: str
) -> None:
    """PRD 2.7: an Order's fulfillment_status and payment_status are two
    independent status dimensions on the same row."""
    assert_fields(order, fulfillment_status=fulfillment_status, payment_status=payment_status)


def assert_safety_incident(incident: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(incident)
    assert_fields(incident, **expected)


def assert_payout_statement(statement: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(statement)
    assert_money_is_integer(
        statement,
        "gross_sales_cents",
        "commission_cents",
        "refund_chargeback_cents",
        "safety_hold_cents",
        "net_payout_cents",
    )
    assert_fields(statement, **expected)


def assert_refund_event(refund: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(refund)
    assert_money_is_integer(
        refund,
        "refund_amount_cents",
        "cook_chargeback_cents",
        "commission_reversed_cents",
        "platform_absorbed_cents",
    )
    assert_fields(refund, **expected)


# ---------------------------------------------------------------- invariants
def assert_charge_breakdown(order: Dict[str, Any]) -> None:
    """PRD 3.5: `subtotal_cents` is that snapshot multiplied by `quantity`,
    `diner_service_fee_cents` is nine percent of `subtotal_cents` rounded half
    up, and `total_charge_cents` is the sum of subtotal, surcharge and fee."""
    assert order["subtotal_cents"] == order["unit_price_cents_snapshot"] * order["quantity"], (
        f"subtotal_cents {order['subtotal_cents']} != snapshot "
        f"{order['unit_price_cents_snapshot']} * quantity {order['quantity']}"
    )
    assert order["diner_service_fee_cents"] == expected_diner_service_fee_cents(
        order["subtotal_cents"]
    ), (
        f"diner_service_fee_cents {order['diner_service_fee_cents']} != 9% of "
        f"{order['subtotal_cents']} rounded half up"
    )
    assert order["total_charge_cents"] == (
        order["subtotal_cents"]
        + order["cold_chain_surcharge_cents"]
        + order["diner_service_fee_cents"]
    ), f"total_charge_cents does not equal subtotal + surcharge + fee: {order}"
    assert order["cook_earnings_cents"] == (
        order["subtotal_cents"] - order["platform_commission_cents"]
    ), (
        f"cook_earnings_cents {order['cook_earnings_cents']} != subtotal "
        f"{order['subtotal_cents']} - commission {order['platform_commission_cents']}"
    )


def assert_capacity_triple(
    window: Dict[str, Any], committed_meals: int, capacity_meals: Optional[int] = None
) -> None:
    """PRD 3.3: `spoilage_reserve_meals` is the committed meal count multiplied
    by a ten-percent spoilage allowance, rounded up to the next whole meal;
    `effective_capacity_meals` is the declared `capacity_meals` less that reserve."""
    declared = capacity_meals if capacity_meals is not None else window["capacity_meals"]
    reserve = expected_spoilage_reserve_meals(committed_meals)
    assert_fields(
        window,
        committed_meals=committed_meals,
        spoilage_reserve_meals=reserve,
        effective_capacity_meals=declared - reserve,
    )


def assert_refund_three_bucket_identity(refund: Dict[str, Any]) -> None:
    """PRD 2.12: every refund event satisfies the identity that its
    `refund_amount_cents` equals the sum of its `cook_chargeback_cents`, its
    `commission_reversed_cents` and its `platform_absorbed_cents`."""
    total = (
        refund["cook_chargeback_cents"]
        + refund["commission_reversed_cents"]
        + refund["platform_absorbed_cents"]
    )
    assert total == refund["refund_amount_cents"], (
        f"three-bucket split {refund['cook_chargeback_cents']} + "
        f"{refund['commission_reversed_cents']} + {refund['platform_absorbed_cents']} "
        f"= {total} != refund_amount_cents {refund['refund_amount_cents']}"
    )


def assert_net_payout_identity(statement: Dict[str, Any]) -> None:
    """PRD 3.8: `net_payout_cents` is then `gross_sales_cents` less
    `commission_cents` less `refund_chargeback_cents` less `safety_hold_cents`,
    floored at zero so that a statement never expresses a negative payout."""
    expected = max(
        0,
        statement["gross_sales_cents"]
        - statement["commission_cents"]
        - statement["refund_chargeback_cents"]
        - statement["safety_hold_cents"],
    )
    assert statement["net_payout_cents"] == expected, (
        f"net_payout_cents {statement['net_payout_cents']} != {expected}"
    )


def assert_ordered_by_created_at(rows: Iterable[Dict[str, Any]]) -> None:
    """PRD 2.3: list results are always ordered by `created_at` ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ascending: {stamps}"


def assert_version_at_least(entity: Dict[str, Any], minimum: int) -> None:
    assert entity["version"] >= minimum, (
        f"expected version >= {minimum}, got {entity['version']}"
    )
