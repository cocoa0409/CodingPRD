"""Formulas whose answer depends on where a boundary or an order of steps sits."""

from test_helpers import fixtures as fx


SURCHARGED_LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "periodic_interval_months": 12,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 18700,
    "component_reliance_allowed": True,
}

FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

SURCHARGE_750 = [{"fee_surcharge_basis_points": 750}]


def _priced_order_env(api, evidence_path):
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.booking_env(
        api,
        evidence_path=evidence_path,
        rule_specs=[dict(SURCHARGED_LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        accreditation_overrides=[dict(SURCHARGE_750[0])],
        plan_overrides={"plan_type": "INITIAL"},
    )
    assert env["plan"]["units_authorized"] == 4
    return env


class TestLineFeeRoundingOrder:
    """The per-sample amount is rounded once, before the sample count multiplies it."""

    def test_per_sample_amount_is_rounded_before_the_sample_count_multiplies_it(self, api):
        """PRD 3.6: "Round that per-sample amount half up to whole cents **at this
        point and only at this point**, then multiply the rounded per-sample amount by
        the order's `sample_count` as exact integer arithmetic."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_pinned_rounding_order_per_sample_before_multiplication
        """
        env = _priced_order_env(api, "FULL_PRODUCT_TEST")
        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=3,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            expedite_requested=False,
        )

        # 18700 * 1.075 * 1.00 = 20102.5 per sample, rounded half up to 20103.
        assert order["line_fee_cents"] == 60309
        assert order["line_fee_cents"] != 60308
        assert order["invoice_total_cents"] == 60309

    def test_booking_bills_the_invoice_total_and_commits_the_sample_units(self, api):
        """PRD 3.6: "And the order's `invoice_total_cents` is added to the
        laboratory's `billed_fee_cents_total` at creation — every order is billed the
        moment it is booked, which is why a `SCHEDULED` order already counts toward the
        laboratory's outstanding balance."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_pinned_rounding_order_per_sample_before_multiplication
        """
        env = _priced_order_env(api, "FULL_PRODUCT_TEST")
        fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=3,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            expedite_requested=False,
        )

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_authorized"] == 4
        assert plan["units_committed"] == 3
        assert plan["units_available"] == 1

        laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
        assert laboratory["billed_fee_cents_total"] == 60309
        assert laboratory["credited_fee_cents_total"] == 0


class TestInvoiceWaterfallOrder:
    """The expedite tier is read from the subtotal, the discount tier from the total."""

    def test_expedite_fee_is_applied_before_the_reliance_discount_tier_is_chosen(self, api):
        """PRD 3.6: "Note that the discount tier is keyed on a figure that already
        contains the expedite fee; the evaluation order above is what makes the value
        well defined despite the apparent circularity."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_pinned_evaluation_order_expedite_tier_before_reliance_discount
        """
        env = _priced_order_env(api, "COMPONENT_RELIANCE")
        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=3,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            expedite_requested=True,
        )

        # subtotal 60309 + expedite 6031 = 66340, less an 800 bp discount of 5307.
        assert order["line_fee_cents"] == 60309
        assert order["invoice_total_cents"] == 61033
        assert order["invoice_total_cents"] != 61032

    def test_both_ladders_select_their_middle_tier_for_this_subtotal(self, api):
        """PRD 3.6: "Step two determines the expedite rate: it is zero basis points
        when `expedite_requested` is false; otherwise it is 1500 basis points when the
        subtotal is at or below 50,000 cents, 1000 basis points when the subtotal is at
        or below 150,000 cents, and 600 basis points for any larger subtotal — the rate
        falls as the order grows, because expedited handling of a large job costs
        proportionally less."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_pinned_evaluation_order_expedite_tier_before_reliance_discount
        """
        env = _priced_order_env(api, "COMPONENT_RELIANCE")
        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=3,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            expedite_requested=True,
        )

        subtotal = order["line_fee_cents"]
        assert subtotal == 60309
        # 1000 bp of the subtotal, not the 1500 bp tier: 60309 is above 50,000 cents.
        total_before_discount = subtotal + 6031
        assert total_before_discount == 66340
        # 800 bp of that total, not 1200 bp: 66340 is below 120,000 cents.
        assert total_before_discount - order["invoice_total_cents"] == 5307
        laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
        assert laboratory["billed_fee_cents_total"] == 61033


def _weighted_gap_env(api):
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.booking_env(
        api,
        evidence_path="FULL_PRODUCT_TEST",
        rule_specs=[
            {
                "hazard_class": "LEAD_CONTENT",
                "severity_weight": 8,
                "limit_value": 100,
                "limit_unit": "PPM",
                "base_method_fee_cents": 10000,
            },
            {
                "hazard_class": "PHTHALATES",
                "severity_weight": 1,
                "limit_value": 1000,
                "limit_unit": "PPM",
                "base_method_fee_cents": 10000,
            },
        ],
        category=dict(FLAT_CATEGORY),
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
    )
    lead_rule, phthalate_rule = env["rules"]
    assert env["product"]["required_rule_ids"] == [lead_rule["id"], phthalate_rule["id"]]

    orders = {}
    for key, rule in (("lead", lead_rule), ("phthalate", phthalate_rule)):
        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            rule["id"],
            sample_count=1,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
        )
        fx.start_order(api, order["id"], env["laboratory"]["id"])
        orders[key] = order
    fx.report(api, orders["phthalate"]["id"], env["laboratory"]["id"], 400)
    env["orders_by_rule"] = orders
    env["lead_rule"] = lead_rule
    return env


class TestGapScoreClampNesting:
    """The percentage rounds first, the penalties add, and only then the clamp bites."""

    def test_uncovered_percentage_rounds_half_up_before_any_penalty(self, api):
        """PRD 3.3: "The base figure is 100 whenever the total weight is 0, and
        otherwise 100 multiplied by the uncovered weight, divided by the total weight,
        rounded half up to a whole number."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_nested_min_max_clamp_after_penalties_on_gap_score
        """
        env = _weighted_gap_env(api)
        summary = fx.get_summary(api, env["product"]["id"])

        # uncovered weight 8 of total weight 9 is 88.888..., which rounds to 89.
        assert summary["risk_weighted_gap_score"] == 89
        assert summary["risk_weighted_gap_score"] != 88
        assert summary["uncovered_rule_ids"] == [env["lead_rule"]["id"]]
        assert summary["compliance_posture"] == "RESTRICTED"

    def test_penalties_accumulate_past_one_hundred_and_are_clamped_once_afterwards(self, api):
        """PRD 3.3: "The final `risk_weighted_gap_score` is the base plus both
        penalties, clamped once into the range 0 through 100 — the clamp is applied
        after the penalties, never before."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_nested_min_max_clamp_after_penalties_on_gap_score
        """
        env = _weighted_gap_env(api)

        fx.record_material_change(
            api,
            env["product"]["id"],
            subject_type="PRODUCT",
            change_kind="DESIGN_GEOMETRY_CHANGE",
            description="Seat shell geometry revised, so the plan must be resampled.",
        )
        after_resample = fx.get_summary(api, env["product"]["id"])
        assert after_resample["risk_weighted_gap_score"] == 99
        assert after_resample["resample_due_plan_count"] == 1
        assert after_resample["compliance_posture"] == "RESTRICTED"

        fx.report(api, env["orders_by_rule"]["lead"]["id"], env["laboratory"]["id"], 250)
        after_case = fx.get_summary(api, env["product"]["id"])
        assert after_case["risk_weighted_gap_score"] == 100
        assert after_case["risk_weighted_gap_score"] != 114
        assert after_case["open_case_count"] == 1
        assert after_case["compliance_posture"] == "SUSPENDED"
