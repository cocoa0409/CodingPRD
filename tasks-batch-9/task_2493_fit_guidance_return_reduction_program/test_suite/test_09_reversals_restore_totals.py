"""Undo operations that must return an aggregate to its opening value.

Neither reversal edits the row it undoes.  A voided return case is answered with a
negating ledger row per original posting, and a retracted feedback row is answered by
shrinking the item's signal pool by exactly the weight that row had added.  In both
cases the conserved quantity has to come back to zero on its own arithmetic.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    assert_every_original_is_reversed,
    assert_ledger_sums_to,
    make_merch_ops_admin_headers,
    validate_paginated,
)
from test_helpers import fixtures as fx  # noqa: E402


def _build_resolved_quality_case(api: ApiClient) -> dict:
    """A refunded quality case on a three-unit line of 2,295-cent tops with 700 cents
    of withheld shipping, so the ledger carries all six components including the
    vendor's chargeback credit."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Quality Looms", brand_code="QLTY", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="QLTY-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    fx.create_policy(
        api,
        category_code="TOPS",
        window_days=30,
        restocking_applies=True,
        non_refundable_shipping=True,
        effective_from="2026-01-01T00:00:00Z",
    )
    customer = fx.create_customer(api, email="shopper-r9a@example.com")
    line = fx.create_order_line(
        api,
        customer["id"],
        item["id"],
        size_label="M",
        quantity=3,
        unit_price_cents=2295,
        shipping_allocated_cents=700,
        delivered_at="2026-05-20T00:00:00Z",
    )
    case = fx.open_case(
        api, line["id"], customer["id"], requested_reason_code="QUALITY_DEFECT"
    )
    case = fx.classify_case(api, case["id"], "QUALITY_DEFECT")
    case = fx.resolve_case(api, case["id"], "RESELLABLE_B")
    return {
        "vendor": fx.read_vendor(api, vendor["id"]),
        "item": fx.read_item(api, item["id"]),
        "customer": fx.read_customer(api, customer["id"]),
        "order_line": line,
        "case": case,
    }


def test_voiding_writes_one_negating_row_for_every_original_posting(api):
    """PRD §3.8: "Exactly one `REVERSAL` posting is written per `ORIGINAL` posting of
    the case, each with `amount_cents` negated and `reversed_component` naming the
    component it negates — so a refunded quality case with six original rows produces
    six reversal rows, and a denied case with two original rows produces two."  The six
    originals include a negative vendor chargeback credit, so its reversal is the only
    positive row of the six, and the twelve rows together net to nothing.

    Design: Difficulty/compensating_invariant/void_returns_return_cost_ledger_and_refund_total_to_zero
    """
    built = _build_resolved_quality_case(api)

    originals = fx.read_cost_postings(api, built["case"]["id"])
    assert len(originals) == 6
    assert [row["amount_cents"] for row in originals] == [
        795,
        1054,
        275,
        826,
        179,
        -2754,
    ]

    fx.void_case(api, built["case"]["id"], void_reason="AUDIT_REVERSAL")

    postings = fx.read_cost_postings(api, built["case"]["id"])
    assert len(postings) == 12
    assert len([row for row in postings if row["posting_kind"] == "ORIGINAL"]) == 6
    assert len([row for row in postings if row["posting_kind"] == "REVERSAL"]) == 6
    assert_every_original_is_reversed(postings)
    assert_ledger_sums_to(postings, 0)


def test_the_void_keeps_the_historical_money_but_zeroes_the_case_total(api):
    """PRD §3.8: "The case's `refund_amount_cents` and `restocking_fee_cents` keep
    their historical values as a record of what was once paid, but `total_cost_cents`
    becomes 0."  The 6,185 cents that were actually paid out stay legible on the voided
    row, and the reason the auditor gave for the reversal is stored alongside them.

    Design: Difficulty/compensating_invariant/void_returns_return_cost_ledger_and_refund_total_to_zero
    """
    built = _build_resolved_quality_case(api)

    assert built["case"]["status"] == "RESOLVED_REFUNDED"
    assert built["case"]["refund_amount_cents"] == 6185
    assert built["case"]["total_cost_cents"] == 375

    case = fx.void_case(api, built["case"]["id"], void_reason="AUDIT_REVERSAL")

    assert case["status"] == "VOIDED"
    assert case["void_reason"] == "AUDIT_REVERSAL"
    assert case["refund_amount_cents"] == 6185
    assert case["restocking_fee_cents"] == 0
    assert case["total_cost_cents"] == 0


def test_the_items_accrual_and_return_counters_come_back_to_zero(api):
    """PRD §3.8: "On the item, `return_cost_accrued_cents`, `fit_return_count`,
    `expectation_return_count`, `total_return_count`, both rates,
    `chronic_return_score_bp`, and `fit_watch_state` are all recomputed, so a void can
    walk an item out of `CHRONIC`."  The item accrued the case's 375-cent net cost and
    counted the return; after the void the twelve ledger rows sum to nothing and the
    counters read as though the return had never closed.

    Design: Difficulty/compensating_invariant/void_returns_return_cost_ledger_and_refund_total_to_zero
    """
    built = _build_resolved_quality_case(api)

    assert built["item"]["return_cost_accrued_cents"] == 375
    assert built["item"]["total_return_count"] == 1

    fx.void_case(api, built["case"]["id"], void_reason="AUDIT_REVERSAL")

    item = fx.read_item(api, built["item"]["id"])
    assert item["return_cost_accrued_cents"] == 0
    assert item["total_return_count"] == 0
    assert item["chronic_return_score_bp"] == 0
    assert item["fit_watch_state"] == "NORMAL"


def test_the_shopper_is_owed_nothing_and_the_line_can_be_returned_again(api):
    """PRD §3.8: "The order line returns to `DELIVERED`, leaving it eligible to be
    returned again."  The refund is unwound on the shopper as well: the lifetime
    refunded total drops by exactly the 6,185 cents this case paid, and the case stops
    counting toward their standing altogether.

    Design: Difficulty/compensating_invariant/void_returns_return_cost_ledger_and_refund_total_to_zero
    """
    built = _build_resolved_quality_case(api)

    assert built["customer"]["refunded_total_cents"] == 6185
    assert built["customer"]["return_case_count"] == 1

    fx.void_case(api, built["case"]["id"], void_reason="AUDIT_REVERSAL")

    order_line = fx.read_order_line(api, built["order_line"]["id"])
    assert order_line["status"] == "DELIVERED"

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["refunded_total_cents"] == 0
    assert customer["return_case_count"] == 0
    assert customer["abuse_status"] == "CLEAR"


def test_the_voided_quality_case_gives_the_vendor_its_reliability_back(api):
    """PRD §3.8: "On the vendor, a quality-family case being voided decrements
    `quality_chargeback_count`, after which `reliability_score_bp` and vendor `status`
    are re-derived."  The resolution had cost the brand 500 basis points of reliability;
    the void returns the count to zero and the score to a perfect 10,000.

    Design: Difficulty/compensating_invariant/void_returns_return_cost_ledger_and_refund_total_to_zero
    """
    built = _build_resolved_quality_case(api)

    assert built["vendor"]["quality_chargeback_count"] == 1
    assert built["vendor"]["reliability_score_bp"] == 9500

    fx.void_case(api, built["case"]["id"], void_reason="AUDIT_REVERSAL")

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["quality_chargeback_count"] == 0
    assert vendor["reliability_score_bp"] == 10000
    assert vendor["status"] == "ACTIVE"


def _build_item_with_two_feedback_rows(api: ApiClient) -> dict:
    """A listed item carrying two active feedback rows: one from a shopper who owns a
    delivered unit of it and one from a shopper who does not."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Signal Sewing", brand_code="SGNL", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="SGNL-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    buyer = fx.create_customer(api, email="buyer-c1@example.com")
    browser = fx.create_customer(api, email="browser-c2@example.com")
    fx.create_order_line(
        api,
        buyer["id"],
        item["id"],
        size_label="M",
        quantity=1,
        unit_price_cents=2295,
        shipping_allocated_cents=0,
        delivered_at="2026-05-20T00:00:00Z",
    )
    buyer_feedback = fx.post_feedback(
        api,
        item["id"],
        buyer["id"],
        purchased_size_label="M",
        fit_verdict="TRUE_TO_SIZE",
    )
    browser_feedback = fx.post_feedback(
        api,
        item["id"],
        browser["id"],
        purchased_size_label="M",
        fit_verdict="TOO_LARGE",
    )
    return {
        "item": fx.read_item(api, item["id"]),
        "buyer": buyer,
        "browser": browser,
        "buyer_feedback": buyer_feedback,
        "browser_feedback": browser_feedback,
    }


def test_a_verified_purchasers_verdict_enters_the_pool_at_double_weight(api):
    """PRD §3.5: "`signal_weight` is 200 when the reviewer actually owns the item —
    that is, when the reviewer has an order line on this item whose `status` is
    `DELIVERED`, `RETURN_IN_PROGRESS`, `RETURNED`, or `KEPT` — and 100 otherwise, so
    verified purchasers count double."  The buyer's row weighs 200 and the browser's
    100, so the item's pool opens at 300 across two contributions, and the two verdicts
    are translated into opposite offsets.

    Design: Difficulty/compensating_invariant/feedback_retraction_restores_item_fit_signal_pool
    """
    built = _build_item_with_two_feedback_rows(api)

    assert built["buyer_feedback"]["signal_weight"] == 200
    assert built["buyer_feedback"]["verdict_offset_centi"] == 0
    assert built["browser_feedback"]["signal_weight"] == 100
    assert built["browser_feedback"]["verdict_offset_centi"] == -100

    assert built["item"]["fit_signal_weight_total"] == 300
    assert built["item"]["active_fit_feedback_count"] == 2


def test_each_retraction_drains_exactly_the_weight_that_row_contributed(api):
    """PRD §3.5: "The supplied `retract_reason` of `AUTHOR_WITHDRAWN` or
    `MODERATION_REMOVED` is stored, the row moves `ACTIVE → RETRACTED`, and the item's
    pool shrinks by exactly the amounts it grew by: `fit_signal_weight_total` decreases
    by this row's `signal_weight` and `active_fit_feedback_count` decreases by 1."
    Retracting the double-weighted row first takes the pool from 300 to 100 rather than
    to 200, and retracting the remaining row empties it exactly.

    Design: Difficulty/compensating_invariant/feedback_retraction_restores_item_fit_signal_pool
    """
    built = _build_item_with_two_feedback_rows(api)

    first = fx.retract_feedback(
        api,
        built["buyer_feedback"]["id"],
        built["buyer"]["id"],
        retract_reason="AUTHOR_WITHDRAWN",
    )
    assert first["status"] == "RETRACTED"
    assert first["retract_reason"] == "AUTHOR_WITHDRAWN"

    midway = fx.read_item(api, built["item"]["id"])
    assert midway["fit_signal_weight_total"] == 100
    assert midway["active_fit_feedback_count"] == 1

    second = fx.retract_feedback(
        api,
        built["browser_feedback"]["id"],
        built["browser"]["id"],
        retract_reason="AUTHOR_WITHDRAWN",
    )
    assert second["status"] == "RETRACTED"

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_signal_weight_total"] == 0
    assert item["active_fit_feedback_count"] == 0


def test_a_retracted_row_leaves_no_active_signal_behind_on_the_item(api):
    """PRD §3.5: "A retracted row contributes nothing to any recommendation signal pool
    from that moment on."  Both rows survive as retracted records, so the item's active
    pool is empty while the rows themselves are still readable.

    Design: Difficulty/compensating_invariant/feedback_retraction_restores_item_fit_signal_pool
    """
    built = _build_item_with_two_feedback_rows(api)

    fx.retract_feedback(
        api,
        built["buyer_feedback"]["id"],
        built["buyer"]["id"],
        retract_reason="AUTHOR_WITHDRAWN",
    )
    fx.retract_feedback(
        api,
        built["browser_feedback"]["id"],
        built["browser"]["id"],
        retract_reason="MODERATION_REMOVED",
    )

    active_rows, _ = validate_paginated(
        api.list_fit_feedback(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "status": "ACTIVE"},
        )
    )
    assert active_rows == []

    all_rows, _ = validate_paginated(
        api.list_fit_feedback(
            make_merch_ops_admin_headers(), {"item_id": built["item"]["id"]}
        )
    )
    assert len(all_rows) == 2
    assert {row["status"] for row in all_rows} == {"RETRACTED"}
    assert {row["retract_reason"] for row in all_rows} == {
        "AUTHOR_WITHDRAWN",
        "MODERATION_REMOVED",
    }
