"""Order pricing: pinned per-line rounding, the required-deposit rate table
with its floors, and immediate visibility of computed fields (PRD §3.4, §2.2)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_dealer_order,
    assert_order_option_line,
    book_order,
    create_model,
    create_dealer,
    create_option,
    create_show,
    make_dealer_principal_headers,
    setup_bookable_world,
    validate_paginated,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestPerLineRoundingPinned:
    """Line totals round per line first, then sum; the rejected alternative
    (sum raw, round once) is observable at the cents level."""

    def _book_two_cheap_options(self, api, n_options=2):
        model = create_model(api)
        opts = [
            create_option(
                api, model["id"], option_code=f"OP{chr(65 + i)}",
                price_cents=33333, production_hours=0,
            )
            for i in range(n_options)
        ]
        dealer = create_dealer(api)
        order = book_order(
            api, dealer, model,
            option_ids=[o["id"] for o in opts],
            deposit_paid_cents=10_000_000,
        )
        return order

    def test_invoice_per_line_rounding_two_lines(self, api):
        """PRD §3.4: "Every `line_total_cents` is its unit price times one minus
        the captured discount, rounded half up per line. The order's
        `options_total_cents` is the sum of those already-rounded line totals —
        summing raw amounts and rounding once is a rejected alternative."
        PRD §3.4: "The `surcharge_cents` is three percent of base plus options,
        rounded half up; note the base price itself is never discounted."

        Two 33333-cent options at the STANDARD 0.05 discount: per-line
        rhu(33333*0.95) = 31666 twice sums to 63332, while sum-then-round would
        give rhu(66666*0.95) = 63333.

        Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_order_pinned
        """
        order = self._book_two_cheap_options(api, n_options=2)
        assert order["options_total_cents"] == 63332, (
            f"per-line rounding must produce 63332, got {order['options_total_cents']}"
        )
        assert order["surcharge_cents"] == 76900  # rhu(2563332 * 0.03)
        assert order["invoice_total_cents"] == 2640232  # 2500000 + 63332 + 76900
        assert_dealer_order(order)

    def test_invoice_per_line_rounding_three_lines(self, api):
        """PRD §3.4: "Every `line_total_cents` is its unit price times one minus
        the captured discount, rounded half up per line. The order's
        `options_total_cents` is the sum of those already-rounded line totals —
        summing raw amounts and rounding once is a rejected alternative."

        Three 33333-cent options: per-line 31666 x 3 = 94998, while
        sum-then-round would give rhu(99999*0.95) = 94999.

        Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_order_pinned
        """
        order = self._book_two_cheap_options(api, n_options=3)
        assert order["options_total_cents"] == 94998, (
            f"per-line rounding must produce 94998, got {order['options_total_cents']}"
        )
        # subtotal 2594998; surcharge rhu(77849.94) = 77850
        assert order["surcharge_cents"] == 77850
        assert order["invoice_total_cents"] == 2672848
        assert_dealer_order(order)


class TestRequiredDeposit:
    def test_required_deposit_minimum_floor(self, api):
        """PRD §3.4: "The `required_deposit_cents` is the invoice total times
        the effective rate, rounded half up, and then raised to a 50000-cent
        minimum if below it."

        Invoice 103000 (base 100000 + rhu(3000) surcharge); 10% would be 10300,
        so the 50000-cent floor binds.

        Design: Corner/calculations/required_deposit_minimum_floor
        """
        model = create_model(
            api, model_code="MINI", base_price_cents=100000, production_hours=5
        )
        dealer = create_dealer(api)
        order = book_order(
            api, dealer, model, option_ids=[], deposit_paid_cents=50000
        )
        assert order["invoice_total_cents"] == 103000
        assert order["required_deposit_cents"] == 50000, (
            f"50000-cent floor must bind, got {order['required_deposit_cents']}"
        )
        assert_dealer_order(order)

    def test_required_deposit_min_rate_floor_on_show_event(self, api):
        """PRD §3.4: "The base rate depends on `source`: 0.10 for `RETAIL`, 0.15
        for `FLEET`, and the event's `surge_deposit_rate` for a `BOAT_SHOW`
        order. Standing shifts that rate by −0.02 for `PREFERRED`, 0.00 for
        `STANDARD`, and +0.05 for `PROBATION`; the effective rate is the sum,
        but never less than a 0.03 floor."

        A 0.01 surge rate for a STANDARD dealer sums to 0.01, below the floor:
        the effective rate is 0.03.

        Design: Corner/calculations/required_deposit_min_rate_floor_on_show_event
        """
        world = setup_bookable_world(api)
        show = create_show(
            api, start_date="2026-08-01", end_date="2026-08-15",
            surge_deposit_rate=0.01,
        )
        order = book_order(
            api, world["dealer"], world["model"],
            option_ids=[world["tower"]["id"], world["ballast"]["id"]],
            source="BOAT_SHOW", show_event_id=show["id"],
            deposit_paid_cents=92808,
        )
        assert order["invoice_total_cents"] == 3093605
        assert order["required_deposit_cents"] == 92808, (
            f"rate floor 0.03 must bind: rhu(3093605*0.03)=92808, got "
            f"{order['required_deposit_cents']}"
        )

    def test_required_deposit_preferred_standing_delta(self, api):
        """PRD §3.4: "Standing shifts that rate by −0.02 for `PREFERRED`, 0.00
        for `STANDARD`, and +0.05 for `PROBATION`; the effective rate is the
        sum, but never less than a 0.03 floor."

        RETAIL PREFERRED: 0.10 - 0.02 = 0.08 on the discounted invoice.

        Design: Corner/calculations/required_deposit_preferred_standing_delta
        """
        world = setup_bookable_world(api, standing="PREFERRED")
        order = book_order(
            api, world["dealer"], world["model"],
            option_ids=[world["tower"]["id"], world["ballast"]["id"]],
            deposit_paid_cents=245305,
        )
        # PREFERRED discount 0.10 per line: 315000 + 162000 = 477000
        assert order["options_total_cents"] == 477000
        assert order["invoice_total_cents"] == 3066310  # 2977000 + rhu(89310)
        assert order["required_deposit_cents"] == 245305, (
            f"rhu(3066310 * 0.08) = 245305, got {order['required_deposit_cents']}"
        )

    def test_required_deposit_probation_standing_delta(self, api):
        """PRD §3.4: "Standing shifts that rate by −0.02 for `PREFERRED`, 0.00
        for `STANDARD`, and +0.05 for `PROBATION`; the effective rate is the
        sum, but never less than a 0.03 floor."
        PRD §3.2: "Standing is the dealer's commercial grade and moves two
        levers at once: the discount captured on each option line (ten percent
        for `PREFERRED`, five percent for `STANDARD`, nothing for `PROBATION`)"

        RETAIL PROBATION: 0.10 + 0.05 = 0.15 on the undiscounted invoice.

        Design: Corner/calculations/required_deposit_probation_standing_delta
        """
        world = setup_bookable_world(api, standing="PROBATION")
        order = book_order(
            api, world["dealer"], world["model"],
            option_ids=[world["tower"]["id"], world["ballast"]["id"]],
            deposit_paid_cents=468135,
        )
        assert order["options_total_cents"] == 530000  # no discount
        assert order["invoice_total_cents"] == 3120900  # 3030000 + rhu(90900)
        assert order["required_deposit_cents"] == 468135, (
            f"rhu(3120900 * 0.15) = 468135, got {order['required_deposit_cents']}"
        )


class TestImmediateConsistency:
    def test_order_response_includes_computed_fields(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.4: "Pricing is computed at booking and the rounding order is
        pinned."

        The booking response itself carries invoice_total_cents,
        required_deposit_cents, options_total_cents, and production_hours.

        Design: Corner/consistency_model/immediate_consistency_order_response_includes_computed_fields
        """
        world = setup_bookable_world(api)
        order = book_order(
            api, world["dealer"], world["model"],
            option_ids=[world["tower"]["id"]],
            deposit_paid_cents=291748,
        )
        assert order["options_total_cents"] == 332500  # rhu(350000 * 0.95)
        assert order["invoice_total_cents"] == 2917475  # 2832500 + rhu(84975)
        assert order["required_deposit_cents"] == 291748
        assert order["production_hours"] == 46  # 40 base + 6 WAKE-TOWER
        assert_dealer_order(order)

    def test_order_option_line_carries_only_id_and_created_at(self, api):
        """PRD §2.4: "One entity deviates: an `OrderOptionLine` is immutable
        once written and carries only `id` and `created_at` — both `updated_at`
        and `version` are absent from it."

        Design: Corner/entities/order_option_line_immutable_no_update_endpoint
        """
        world = setup_bookable_world(api)
        order = book_order(
            api, world["dealer"], world["model"],
            option_ids=[world["tower"]["id"]],
            deposit_paid_cents=291748,
            slot_id=world["slot"]["id"],
        )
        data, _meta = validate_paginated(
            api.list_order_option_lines(ANY, params={"order_id": order["id"]})
        )
        assert len(data) == 1, "one option chosen -> one line"
        line = data[0]
        assert_order_option_line(line)
        assert line["order_id"] == order["id"]
        assert line["option_package_id"] == world["tower"]["id"]
        assert line["unit_price_cents"] == 350000, "unit price snapshots the option price"
        assert line["discount_pct_applied"] == pytest.approx(0.05)
        assert line["line_total_cents"] == 332500
