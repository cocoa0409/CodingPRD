"""Per-line rounding before summation on a discounted renewal invoice.

A thirty-five percent discount on a 4999 plan line plus a 1299 addon line produces
two fractional products.  Rounding each line first gives 3249 + 844 = 4093; summing
the raw products and rounding once would give 4094.  The pinned order decides.
"""

import pytest

from test_helpers import (
    accept_grant,
    assert_invoice,
    assert_line_items_pinned_order,
    assert_lines_sum_to_amount,
    assert_price_conserved,
    invoice_at_cycle,
    modifications_for,
    new_core_plan,
    new_template,
    read_subscription,
    run_renewal,
    send_renewal_reminder,
    set_clock,
    setup_active_subscription,
    setup_presented_grant,
    signup_invoice,
)

DISCOUNT_TEMPLATE = {
    "offer_type": "DISCOUNT",
    "discount_pct": 0.3500,
    "discount_cycles": 2,
    "priority_rank": 30,
    "min_tenure_days": 60,
    "eligible_reason_codes": ["PRICE"],
}


def _renewal_invoice_issued_under_an_accepted_discount():
    """Signup with one addon, reminder sent inside the window, discount accepted, renewed."""
    plan = new_core_plan()
    template = new_template(**DISCOUNT_TEMPLATE)
    world = setup_active_subscription(
        clock="2026-01-10", plan=plan,
        subscriber_overrides={"acquisition_channel": "ORGANIC"},
        addons=[{"code": "MUG", "qty": 1}],
    )
    set_clock("2026-01-28")
    send_renewal_reminder(world, renewal_cycle_index=1)
    set_clock("2026-03-11")
    grant = setup_presented_grant(world, reason_code="PRICE", as_user_id="rs_1")
    accept_grant(grant["id"], world["subscriber_headers"])
    run_renewal(world["subscription"]["id"])
    world["template"] = template
    world["grant"] = grant
    return world


class TestInvoiceLineRounding:

    def test_each_line_rounds_before_the_lines_are_summed(self):
        """3249 + 844 = 4093, never the 4094 that rounding a single raw total gives.

        PRD §2.8: "When an invoice total is assembled from a plan line and addon
        lines, **each line is rounded to whole cents first, and the rounded lines are
        then summed.** Summing the raw unrounded products and rounding the total once
        is the forbidden reading."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_before_summation_under_discount
        """
        world = _renewal_invoice_issued_under_an_accepted_discount()

        renewal = invoice_at_cycle(world["subscription"]["id"], 1)
        assert_invoice(renewal)
        assert_line_items_pinned_order(renewal)
        assert_lines_sum_to_amount(renewal)

        assert renewal["cycle_index"] == 1
        assert renewal["is_renewal"] is True
        assert renewal["proration_factor"] == pytest.approx(1.0000, abs=5e-5)

        assert len(renewal["line_items"]) == 2
        # round(4999 * 1 * 0.65) and round(1299 * 1 * 0.65).
        assert renewal["line_items"][0]["line_cents"] == 3249
        assert renewal["line_items"][1]["code"] == "MUG"
        assert renewal["line_items"][1]["line_cents"] == 844
        assert renewal["amount_cents"] == 4093
        assert renewal["amount_cents"] != 4094

    def test_committed_price_recomputes_the_same_way_and_the_cogs_ignore_the_discount(self):
        """The discount reprices revenue only, and the cycle consumes one discount cycle.

        PRD §3.4: "`cogs_cents` is built the same way but **ignores the discount
        entirely**, because a discount does not make goods cheaper" and PRD §2.8:
        "The same ordering discipline applies to `committed_price_cents`, which
        rounds the plan component and each addon component separately before adding
        them."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_before_summation_under_discount
        """
        world = _renewal_invoice_issued_under_an_accepted_discount()

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["active_discount_pct"] == pytest.approx(0.3500, abs=5e-5)
        # Two discount cycles were granted; issuing the renewal consumed one.
        assert subscription["discount_remaining_cycles"] == 1
        assert subscription["committed_price_cents"] == 4093

        mods = modifications_for(subscription["id"])
        discount_mods = [m for m in mods if m["mod_type"] == "DISCOUNT_APPLY"]
        assert len(discount_mods) == 1
        # 4093 committed against a 6298 baseline.
        assert discount_mods[0]["delta_price_cents"] == -2205
        assert discount_mods[0]["state"] == "APPLIED"
        assert_price_conserved(subscription, mods)

        signup = signup_invoice(subscription["id"])
        assert signup["amount_cents"] == 6298
        assert signup["cogs_cents"] == 2620

        renewal = invoice_at_cycle(subscription["id"], 1)
        # 2100 * 1 + 520 * 1, untouched by the discount.
        assert renewal["cogs_cents"] == 2620
