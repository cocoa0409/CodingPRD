"""Immediate readability of the derived fields the write cascades move.

Every counter asserted here is read exactly once, in the first response that
follows the write that moved it, so a stale or lazily recomputed value cannot
pass by being correct on a second read.
"""

from test_helpers.assertions import (
    assert_cents,
    assert_instant_equals,
    assert_liters,
    assert_order_dimensions,
)
from test_helpers.constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_SALES_TAX_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
    CLOCK_DEFAULT_CANONICAL,
    STATE_RULE_TX,
)
from test_helpers.fixtures import build_landscape

TX_LIMIT_LITERS = STATE_RULE_TX["per_consumer_limit_liters"]
LITERS_TOLERANCE = 0.0005


def _assert_per_state(summary, state_code, rolling, limit):
    """The accumulated liters, the per-consumer limit and the headroom between."""
    entry = summary["per_state"][state_code]
    values = [
        value
        for value in entry.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    for expected in (rolling, limit, limit - rolling):
        assert any(abs(value - expected) <= LITERS_TOLERANCE for value in values), (
            f"per_state.{state_code} must report {expected:.3f}; got {values}"
        )


def test_every_derived_field_is_readable_in_the_first_response_after_the_write(api):
    """Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. (PRD 2.2)

    Because that entry now exists, the consumer's `rolling_liters_by_state`, `rolling_liters_settled_by_state`, `risk_score_screening`, `risk_score_audit` and `screening_tier` are all recomputed and `Consumer.version` increments by 1. The winery's `excise_accrued_cents` grows by the order's `excise_tax_cents` — that counter is the running sum of `excise_tax_cents` across every order of the winery that has reached `CLEARED` at least once — and `Winery.version` increments by 1. (PRD 3.6)

    That second move has a consequence outside logistics: because the order has left `LABELED`, its liters now qualify as settled, so `rolling_liters_settled_by_state` grows, `risk_score_screening` and `screening_tier` are recomputed, and `Consumer.version` increments by 1. (PRD 3.7)

    Because the order became `RETURNED`, a ledger entry with `event_type` `RETURN_CREDIT` is appended carrying `liters` equal to negative `total_liters`, `order_id` set, `shipment_id` set to this shipment, and `occurred_at` at the logical clock; the order's `excise_reversed_cents` is set to its `excise_tax_cents` and its `sales_tax_reversed_cents` to its `sales_tax_cents`; and the winery's `excise_reversed_cents` grows by the order's `excise_tax_cents`. (PRD 3.7)

    Note what a return does **not** do: it leaves the order's `compliance_status` at `CLEARED`. (PRD 3.7)

    When an outcome has to be undone — a package comes back, a cleared order is re-screened into rejection — the system does not erase the original ledger entry or zero the original money field. It appends an offsetting ledger entry with the opposite sign, and it records the reversal in a dedicated field (`Order.excise_reversed_cents`, `Order.sales_tax_reversed_cents`, `Winery.excise_reversed_cents`) so that gross and net figures are both recoverable. (PRD 2.10)

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_first_response_after_the_write_that_moved_it
    """
    scape = build_landscape(api)
    opening_winery = scape.read_winery()
    assert_cents(opening_winery["excise_accrued_cents"], 0, "excise_accrued_cents")
    assert_cents(opening_winery["excise_reversed_cents"], 0, "excise_reversed_cents")
    opening_consumer = scape.read_consumer()
    assert opening_consumer["return_credit_count"] == 0
    assert opening_consumer["risk_score_screening"] == 0
    assert opening_consumer["screening_tier"] == "STANDARD"

    order = scape.create_order()

    # The screening response itself is the first read of the clearance cascade.
    cleared = scape.screen(order["id"])
    assert_order_dimensions(cleared, "CLEARED", "UNFULFILLED")
    assert_instant_equals(cleared["cleared_at"], CLOCK_DEFAULT_CANONICAL)
    assert cleared["rejection_error_id"] is None
    assert_cents(
        cleared["excise_tax_cents"], CANONICAL_ORDER_EXCISE_CENTS, "excise_tax_cents"
    )
    assert_cents(
        cleared["sales_tax_cents"], CANONICAL_ORDER_SALES_TAX_CENTS, "sales_tax_cents"
    )
    assert_cents(cleared["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(cleared["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents")

    accrued = scape.read_winery()
    assert_cents(
        accrued["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )
    assert_cents(accrued["excise_reversed_cents"], 0, "excise_reversed_cents")

    # The cleared order consumes headroom but has not settled, so utilisation is 0.
    after_clearance = scape.volume_summary(state_code="TX")
    assert_instant_equals(after_clearance["as_of"], CLOCK_DEFAULT_CANONICAL)
    _assert_per_state(
        after_clearance, "TX", CANONICAL_ORDER_TOTAL_LITERS, TX_LIMIT_LITERS
    )
    assert after_clearance["risk_score_screening"] == 0
    assert after_clearance["screening_tier"] == "STANDARD"
    assert after_clearance["return_credit_count"] == 0

    shipment = scape.label(order["id"])
    assert shipment["status"] == "LABEL_CREATED"

    picked_up = scape.pickup(shipment["id"])
    assert picked_up["status"] == "IN_TRANSIT"

    # 4.500 settled liters against 27.000: floor(30 * 4.5 / 27) = 5 points.
    after_pickup = scape.volume_summary(state_code="TX")
    assert after_pickup["risk_score_screening"] == 5
    assert after_pickup["screening_tier"] == "STANDARD"
    _assert_per_state(after_pickup, "TX", CANONICAL_ORDER_TOTAL_LITERS, TX_LIMIT_LITERS)

    sent_back = scape.return_to_sender(shipment["id"])
    assert sent_back["status"] == "RETURNED"
    assert_instant_equals(sent_back["returned_at"], CLOCK_DEFAULT_CANONICAL)

    returned_order = scape.read_order(order["id"])
    assert_order_dimensions(returned_order, "CLEARED", "RETURNED")
    assert_instant_equals(returned_order["returned_at"], CLOCK_DEFAULT_CANONICAL)
    # The gross figures are never rewritten; the reversal lands in its own fields.
    assert_cents(
        returned_order["excise_tax_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_tax_cents",
    )
    assert_cents(
        returned_order["sales_tax_cents"],
        CANONICAL_ORDER_SALES_TAX_CENTS,
        "sales_tax_cents",
    )
    assert_cents(
        returned_order["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )
    assert_cents(
        returned_order["sales_tax_reversed_cents"],
        CANONICAL_ORDER_SALES_TAX_CENTS,
        "sales_tax_reversed_cents",
    )

    reversed_winery = scape.read_winery()
    assert_cents(
        reversed_winery["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )
    assert_cents(
        reversed_winery["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )

    # The credit nets the rolling total back to zero, leaving one return credit.
    after_return = scape.volume_summary(state_code="TX")
    _assert_per_state(after_return, "TX", 0.000, TX_LIMIT_LITERS)
    assert after_return["return_credit_count"] == 1
    assert after_return["risk_score_screening"] == 10
    assert after_return["screening_tier"] == "STANDARD"

    credit = scape.ledger_rows(order_id=order["id"])[-1]
    assert credit["event_type"] == "RETURN_CREDIT"
    assert_liters(credit["liters"], -CANONICAL_ORDER_TOTAL_LITERS)
    assert credit["shipment_id"] == shipment["id"]
