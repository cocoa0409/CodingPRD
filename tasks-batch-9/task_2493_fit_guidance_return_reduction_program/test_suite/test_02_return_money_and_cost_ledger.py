"""Closing a return: the fee, the refund, and the per-component cost ledger.

Two arithmetic orderings decide these numbers and neither is a matter of taste.
Each cost component is rounded to whole cents on its own before the components are
summed, and the restocking tier is read off the order line's gross rather than off
the refund the fee itself produces.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    assert_gross_line_consistent,
    assert_ledger_sums_to,
    assert_posting_components,
    assert_postings_in_declared_order,
    expected_refund_cents,
    expected_restocking_fee_cents,
    expected_return_cost_components,
    make_returns_auditor_headers,
    resolve_return_case_payload,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402


def _build_fractional_cost_case(api: ApiClient) -> dict:
    """A coded change-of-mind case on a three-unit line of 2,295-cent tops with
    700 cents of allocated shipping, so the gross is 6,885 and three of the five
    cost components land on a fraction of a cent."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api,
        name="Rounding Garments",
        brand_code="RNDG",
        correction_budget_cents=10000,
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="RNDG-TEE-01",
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
    customer = fx.create_customer(api, email="shopper-r2a@example.com")
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
        api, line["id"], customer["id"], requested_reason_code="CHANGE_OF_MIND"
    )
    case = fx.classify_case(api, case["id"], "CHANGE_OF_MIND")
    return {
        "vendor": vendor,
        "item": item,
        "customer": customer,
        "order_line": line,
        "case": case,
    }


def test_five_cost_components_are_each_rounded_before_they_are_summed(api):
    """PRD §2.6: "each cost component is rounded to whole cents on its own, and the
    already-rounded components are then summed."  Refurb lands on 275.4, markdown
    on 826.2 and the payment fee on 159.384; rounding each on its own totals 2,489,
    whereas summing the exact fractions to 2,489.984 and rounding once at the end
    would report 2,490.

    Design: Difficulty/combinatorial_formula/return_cost_rounded_per_component_then_summed
    """
    built = _build_fractional_cost_case(api)

    assert_gross_line_consistent(built["order_line"])
    assert built["order_line"]["gross_line_cents"] == 6885

    case = validate_success(
        api.resolve_return_case(
            built["case"]["id"],
            resolve_return_case_payload("RESELLABLE_B"),
            make_returns_auditor_headers("auditor-2"),
        )
    )

    assert case["status"] == "RESOLVED_REFUNDED"
    assert case["restocking_fee_cents"] == 689
    assert case["refund_amount_cents"] == 5496
    assert case["total_cost_cents"] == 2489


def test_the_ledger_writes_one_row_per_component_in_the_declared_order(api):
    """PRD §3.8: "One `ORIGINAL` posting row is written per component in exactly
    the order just given, including components whose amount works out to 0."  A
    change-of-mind close carries no vendor chargeback, so exactly five original
    rows are written and their amounts sum to the case's stored total cost.

    Design: Difficulty/combinatorial_formula/return_cost_rounded_per_component_then_summed
    """
    built = _build_fractional_cost_case(api)
    fx.resolve_case(api, built["case"]["id"], "RESELLABLE_B")

    postings = fx.read_cost_postings(api, built["case"]["id"])

    assert len(postings) == 5
    assert all(row["posting_kind"] == "ORIGINAL" for row in postings)
    assert all(row["reversed_component"] is None for row in postings)
    assert_postings_in_declared_order(postings)
    assert_posting_components(
        postings,
        {
            "FREIGHT_INBOUND": 795,
            "PROCESSING_LABOR": 434,
            "REFURB_REPACK": 275,
            "MARKDOWN_LOSS": 826,
            "PAYMENT_FEE_UNRECOVERED": 159,
        },
    )
    assert_posting_components(
        postings,
        expected_return_cost_components("TOPS", "CHANGE_OF_MIND", "RESELLABLE_B", 6885, 5496),
    )
    assert_ledger_sums_to(postings, 2489)


def test_the_rounded_total_is_what_the_item_accrual_and_shopper_standing_carry(api):
    """PRD §2.10: "the item-level accrual `return_cost_accrued_cents` is simply the
    sum of `amount_cents` across every posting — original and reversal alike —
    attached to any return case of that item."  The accrual therefore inherits the
    per-component rounding exactly, while the same close leaves the shopper one
    change-of-mind strike short of restricted standing.

    Design: Difficulty/combinatorial_formula/return_cost_rounded_per_component_then_summed
    """
    built = _build_fractional_cost_case(api)
    fx.resolve_case(api, built["case"]["id"], "RESELLABLE_B")

    item = fx.read_item(api, built["item"]["id"])
    assert item["return_cost_accrued_cents"] == 2489
    assert item["fit_return_count"] == 0
    assert item["total_return_count"] == 1
    assert item["fit_watch_state"] == "NORMAL"

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["change_of_mind_count"] == 1
    assert customer["abuse_strike_count"] == 1
    assert customer["abuse_status"] == "WATCH"
    assert customer["policy_class"] == "STANDARD_WINDOW"
    assert customer["refunded_total_cents"] == 5496


def _build_tier_boundary_case(api: ApiClient) -> dict:
    """A coded change-of-mind case whose gross is exactly 5,000 cents — the first
    amount inside the middle restocking tier — with no allocated shipping, so the
    refund is the gross less the fee and nothing else."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Tier Threads", brand_code="TIER", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="TIER-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2500,
        )["id"],
    )
    fx.create_policy(
        api,
        category_code="TOPS",
        window_days=30,
        restocking_applies=True,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    customer = fx.create_customer(api, email="shopper-r2b@example.com")
    line = fx.create_order_line(
        api,
        customer["id"],
        item["id"],
        size_label="M",
        quantity=2,
        unit_price_cents=2500,
        shipping_allocated_cents=0,
        delivered_at="2026-05-20T00:00:00Z",
    )
    case = fx.open_case(
        api, line["id"], customer["id"], requested_reason_code="CHANGE_OF_MIND"
    )
    case = fx.classify_case(api, case["id"], "CHANGE_OF_MIND")
    return {
        "item": item,
        "customer": customer,
        "order_line": line,
        "case": case,
    }


def test_the_restocking_tier_is_read_off_the_gross_and_never_off_the_refund(api):
    """PRD §3.8: "The restocking-fee tier is keyed on the order line's
    `gross_line_cents` and never on the refund, which is what keeps the pair well
    defined in a single pass: a gross below 5,000 cents carries a tier of 0 basis
    points, a gross from 5,000 cents up to but not including 20,000 cents carries
    1,000 basis points, and a gross of 20,000 cents or more carries 1,500 basis
    points."  A gross of exactly 5,000 sits inside the 1,000-basis-point tier and
    yields a fee of 500 against a refund of 4,500; keying the tier on that 4,500
    refund instead would fall into the 0-basis-point tier and report a fee of 0 with
    a refund of 5,000.

    Design: Difficulty/combinatorial_formula/restocking_tier_keyed_on_gross_line_not_refund
    """
    built = _build_tier_boundary_case(api)

    assert built["order_line"]["gross_line_cents"] == 5000

    case = validate_success(
        api.resolve_return_case(
            built["case"]["id"],
            resolve_return_case_payload("RESELLABLE_A"),
            make_returns_auditor_headers("auditor-2"),
        )
    )

    assert case["status"] == "RESOLVED_REFUNDED"
    assert case["restocking_fee_cents"] == 500
    assert case["refund_amount_cents"] == 4500
    assert case["restocking_fee_cents"] == expected_restocking_fee_cents(
        5000, "CHANGE_OF_MIND", True
    )
    assert case["refund_amount_cents"] == expected_refund_cents(5000, 0, 500, False)


def test_the_payment_fee_follows_the_refund_the_fee_left_behind(api):
    """PRD §3.8: "`PAYMENT_FEE_UNRECOVERED` is 290 basis points of the **refund** —
    not the gross — divided by 10,000 and rounded half up."  On a 4,500-cent refund
    that share is exactly 130.5 and rounds up to 131, while refurb and markdown stay
    keyed on the 5,000-cent gross at 75 and 0, so the total cost is 1,435.

    Design: Difficulty/combinatorial_formula/restocking_tier_keyed_on_gross_line_not_refund
    """
    built = _build_tier_boundary_case(api)
    case = fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")

    assert case["total_cost_cents"] == 1435

    postings = fx.read_cost_postings(api, built["case"]["id"])
    assert len(postings) == 5
    assert_posting_components(
        postings,
        {
            "FREIGHT_INBOUND": 795,
            "PROCESSING_LABOR": 434,
            "REFURB_REPACK": 75,
            "MARKDOWN_LOSS": 0,
            "PAYMENT_FEE_UNRECOVERED": 131,
        },
    )
    assert_ledger_sums_to(postings, 1435)


def test_the_gross_keyed_fee_is_the_amount_withheld_from_the_shopper(api):
    """PRD §3.8: "`refund_amount_cents` is then the gross less the restocking fee
    less the withheld shipping, floored at 0 so it can never go negative."  With a
    policy that refunds shipping the only deduction is the gross-keyed fee, so the
    shopper's lifetime refunded total lands on 4,500 while the item accrues the
    1,435 the ledger recorded.

    Design: Difficulty/combinatorial_formula/restocking_tier_keyed_on_gross_line_not_refund
    """
    built = _build_tier_boundary_case(api)
    fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["refunded_total_cents"] == 4500
    assert customer["change_of_mind_count"] == 1

    item = fx.read_item(api, built["item"]["id"])
    assert item["return_cost_accrued_cents"] == 1435

    order_line = fx.read_order_line(api, built["order_line"]["id"])
    assert order_line["status"] == "RETURNED"
