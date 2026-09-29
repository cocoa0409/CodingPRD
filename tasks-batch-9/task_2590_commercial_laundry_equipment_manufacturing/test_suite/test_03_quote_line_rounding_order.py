"""The single rounding point on an extended quote line, and the package money
rollup that sums the already-rounded line totals of a two-line laundromat quote.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import make_distributor_headers


def _draft_environment(api):
    """A vended model with all three payment modules, an on-premises model, a
    distributor still in PENDING_TRAINING, and a five-percent package quote."""
    vended = fx.make_vended_model(api)
    on_premises = fx.make_model(api)
    distributor = fx.make_distributor(api)
    channel = {
        "distributor": distributor,
        "headers": make_distributor_headers(distributor["id"]),
    }
    quote = fx.make_quote(
        api,
        channel,
        customer_name="Sudz Express",
        laundromat_site_code="SITE-77",
        stated_credit_score=715,
        financing_program="TERM_60",
        down_payment_cents=0,
        package_discount_pct=5.00,
        freight_cents=250000,
    )
    return {
        "vended": vended,
        "on_premises": on_premises,
        "channel": channel,
        "quote": quote,
    }


def _add_line(api, env, model_id, **overrides):
    """Add one line, presenting the quote version the distributor last observed."""
    payload = f.quote_line_payload(
        model_id,
        fx.read_quote_version(api, env["quote"]["id"], env["channel"]),
        **overrides,
    )
    return validate_success(
        api.create_quote_line(env["quote"]["id"], payload, env["channel"]["headers"]),
        expected_status=201,
    )


def _add_card_line(api, env):
    """Three vended machines with a card module and a two-and-a-half percent
    line discount: the line whose extended amount carries a half-cent fraction."""
    return _add_line(
        api,
        env,
        env["vended"]["id"],
        quantity=3,
        payment_module="CARD",
        line_discount_pct=2.50,
    )


def _add_plain_line(api, env):
    """Two on-premises machines with no payment module and no line discount."""
    return _add_line(
        api,
        env,
        env["on_premises"]["id"],
        quantity=2,
        payment_module="NONE",
        line_discount_pct=0.00,
    )


class TestQuoteLineRoundingOrder:
    def test_01_line_snapshots_the_list_price_and_the_card_surcharge(self, api):
        """A card-equipped vended line freezes the catalogue price and records the per-unit module surcharge.

        PRD: "At the moment a line is created, the quoted model's `list_price_cents` is **snapshotted** into the line's `unit_price_cents`."
        Design: Difficulty/combinatorial_formula/quote_line_rounding_order_pinned_per_line_then_sum
        """
        env = _draft_environment(api)
        line = _add_card_line(api, env)

        a.assert_cents(line["unit_price_cents"], 780000)
        # A CARD module adds one hundred twenty-five dollars per unit.
        a.assert_cents(line["payment_surcharge_cents"], 12500)

    def test_02_extended_amount_is_rounded_once_at_the_very_end(self, api):
        """The discounted three-machine extension rounds a single half-cent fraction upward exactly once.

        PRD: "Rounding the discounted per-unit price first and then multiplying by the quantity is a defect: whenever the per-unit result carries a one-half-cent fraction, the two orders disagree, and the per-unit-first order is the wrong one."
        Design: Difficulty/combinatorial_formula/quote_line_rounding_order_pinned_per_line_then_sum
        """
        env = _draft_environment(api)
        line = _add_card_line(api, env)

        a.assert_cents(line["line_total_cents"], 2318063)
        # Rounding the discounted per-unit price first would have produced
        # 2318064, one cent too much.
        assert line["line_total_cents"] != 2318064

        reread = validate_success(
            api.get_quote_line(line["id"], env["channel"]["headers"]),
            expected_status=200,
        )
        a.assert_cents(reread["line_total_cents"], 2318063)

    def test_03_surcharge_sits_inside_the_quantity_multiplication(self, api):
        """A line with no payment module carries no surcharge and extends to a whole multiple of the list price.

        PRD: "The unit price and the per-unit surcharge are added together; that per-unit figure is multiplied by the `quantity`, because the surcharge is charged per machine and therefore sits inside the quantity multiplication; the product is then multiplied by one minus the `line_discount_pct` divided by one hundred; and only that final extended amount is rounded half up to a whole number of cents."
        Design: Difficulty/combinatorial_formula/quote_line_rounding_order_pinned_per_line_then_sum
        """
        env = _draft_environment(api)
        _add_card_line(api, env)
        line = _add_plain_line(api, env)

        a.assert_cents(line["payment_surcharge_cents"], 0)
        a.assert_cents(line["line_total_cents"], 2500000)

    def test_04_subtotal_sums_the_stored_already_rounded_line_totals(self, api):
        """The package subtotal adds the two stored line totals rather than re-deriving them from list prices.

        PRD: "`line_subtotal_cents` is the **sum of the stored, already-rounded** `line_total_cents` values of the surviving lines; it never recomputes a line from its unit price, so line-level rounding is never re-litigated at the package level."
        Design: Difficulty/combinatorial_formula/quote_line_rounding_order_pinned_per_line_then_sum
        """
        env = _draft_environment(api)
        _add_card_line(api, env)
        _add_plain_line(api, env)

        quote = validate_success(
            api.get_quote(env["quote"]["id"], env["channel"]["headers"]),
            expected_status=200,
        )
        assert quote["line_count"] == 2
        # 2318063 from the rounded card line plus 2500000 from the plain line.
        a.assert_cents(quote["line_subtotal_cents"], 4818063)

    def test_05_package_discount_rounds_once_and_never_touches_freight(self, api):
        """Five percent of the two-line subtotal rounds once, and freight passes through the total at cost.

        PRD: "`discount_cents` is the `line_subtotal_cents` multiplied by `package_discount_pct` divided by one hundred, rounded half up once to a whole number of cents."
        Design: Difficulty/combinatorial_formula/quote_line_rounding_order_pinned_per_line_then_sum
        """
        env = _draft_environment(api)
        _add_card_line(api, env)
        _add_plain_line(api, env)

        quote = validate_success(
            api.get_quote(env["quote"]["id"], env["channel"]["headers"]),
            expected_status=200,
        )
        a.assert_cents(quote["discount_cents"], 240903)
        a.assert_cents(quote["total_cents"], 4827160)
        a.assert_money_identity(quote)
