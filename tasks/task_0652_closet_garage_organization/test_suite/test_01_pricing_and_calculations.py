"""Pricing, lead-time, financing, deposit-floor, and unit-count calculations.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: calculations section.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    fixtures as fx, factories as f,
    make_customer_headers,
)
from test_helpers.fixtures import (
    DESIGNER, ADMIN,
    WOOD_40_UNITS, PREMIUM_WOOD_40_UNITS, MELAMINE_18_UNITS,
)


# ===========================================================================
# Rule 1 — dual-variant calculations
# ===========================================================================
class TestDualVariantPricing:
    def test_estimate_quote_total_for_wood_walk_in_west(self, api):
        """PRD §3.3: "The pre-multiplier subtotal is multiplied by this material
        multiplier and the result is rounded half up to whole cents — this rounding
        happens *after* the multiply, and the rounded figure is the value stored as
        the quote's `subtotal_cents`."
        PRD §3.3: "Finally, `total_cents` is the stored subtotal minus `discount_cents`
        plus `tax_cents`. This `total_cents` is the estimate the customer sees."

        Design: Difficulty/dual_variant_calc/quote_pricing_estimate_vs_change_order_revised
        """
        ctx = fx.setup_accepted_quote(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        quote = ctx["quote"]
        assert quote["total_cents"] == 403941, f"estimate total_cents, got {quote['total_cents']}"

    def test_change_order_revised_total_diverges_from_estimate(self, api):
        """PRD §3.7: "for a `CONFIG_REVISION`, it is the price of the revised
        configuration (computed by the same quote-pricing formula of Section 3.3,
        applied to the revised configuration's line items and unit total) minus the
        base quote's `total_cents`, and may be negative for a downgrade"
        PRD §3.7: "When the revised configuration is repriced, the original quote's
        `promo_code` is **not** carried over — pricing recomputes without a promo
        unless one is supplied again — so the same line items can yield a different
        total than the base quote."

        Design: Difficulty/dual_variant_calc/quote_pricing_estimate_vs_change_order_revised
        """
        ctx = fx.setup_accepted_quote(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        proj = ctx["project"]
        quote_a = ctx["quote"]
        # Capture deposit to enter DEPOSIT_PAID (change-order approval requires it).
        dep = fx.create_deposit(proj["id"], quote_a["id"], 141379)
        fx.capture_deposit(dep["id"], quote_a["version"])
        # Revised config C: PREMIUM_WOOD, same SHELF/DRAWER, no accessory -> 40 units.
        cfg_c, _ = fx.add_finalized_config(
            proj["id"], material_grade="PREMIUM_WOOD", line_items=PREMIUM_WOOD_40_UNITS,
        )
        co = fx.submit_change_order(proj["id"], quote_a["id"], "CONFIG_REVISION",
                                    revised_config_id=cfg_c["id"])
        co = fx.approve_change_order(co["id"])
        assert co["delta_cents"] == 100466, f"delta_cents, got {co['delta_cents']}"
        # The revised price 504407 differs from the estimate 403941.
        assert 403941 + co["delta_cents"] == 504407
        assert co["delta_cents"] != 0

    def test_balance_provisional_at_deposit_higher_than_post_financing(self, api):
        """PRD §3.8: "the balance is first computed provisionally at deposit capture,
        before any financing is funded, so at that point the financed component is zero
        and the balance reflects the accepted total less captured deposits only; once
        financing is funded, the recomputation subtracts the approved financed amount,
        yielding a lower balance for the same deposits."

        Design: Difficulty/dual_variant_calc/balance_provisional_at_deposit_vs_final_after_financing
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        dep = fx.create_deposit(proj["id"], quote["id"], 17820)
        fx.capture_deposit(dep["id"], quote["version"])
        bal_resp = api.get_project_balance(proj["id"], ADMIN)
        bal_provisional = validate_success(bal_resp)["balance_due_cents"]
        assert bal_provisional == 53460, f"provisional balance, got {bal_provisional}"
        # Finance 57024, approve, fund.
        app = fx.create_financing_application(proj["id"], quote["id"], 57024, 12, customer["id"])
        fx.submit_financing_application(app["id"], customer["id"])
        fx.financing_decide(app["id"], "APPROVE")
        fx.fund_financing_application(app["id"])
        final_resp = api.get_project_balance(proj["id"], ADMIN)
        final_bal = validate_success(final_resp)["balance_due_cents"]
        assert final_bal == 0, f"final balance floored at 0, got {final_bal}"
        assert final_bal < bal_provisional

    def test_balance_floored_at_zero_when_deposit_plus_financing_exceed_total(self, api):
        """PRD §3.8: "The result is floored at zero — if the deposits and financing
        together exceed the accepted total, the balance is reported as zero rather than
        a negative number."

        Design: Difficulty/dual_variant_calc/balance_provisional_at_deposit_vs_final_after_financing
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        dep = fx.create_deposit(proj["id"], quote["id"], 17820)
        fx.capture_deposit(dep["id"], quote["version"])
        app = fx.create_financing_application(proj["id"], quote["id"], 57024, 12, customer["id"])
        fx.submit_financing_application(app["id"], customer["id"])
        fx.financing_decide(app["id"], "APPROVE")
        fx.fund_financing_application(app["id"])
        proj_after = get_success_data(api.get_project(proj["id"], DESIGNER))
        # 71280 - 17820 - 57024 = -3564, floored to 0.
        assert proj_after["balance_due_cents"] == 0


# ===========================================================================
# Rule 2 — combinatorial formulas
# ===========================================================================
class TestCombinatorialPricing:
    def test_tiered_material_volume_promo_pricing_mode_a(self, api):
        """PRD §3.3: "a `total_units` of 1 through 19 earns a rate of 0.00 (no discount),
        20 through 49 earns 0.05, and 50 or more earns 0.10."
        PRD §3.3: "The promotional discount is computed as the stored subtotal minus the
        volume discount, multiplied by the promo rate, rounded half up to whole cents,
        and then capped so it never exceeds 200000 cents (the lesser of the rounded
        figure and the cap is used)."

        Design: Difficulty/combinatorial_formula/quote_pricing_tiered_material_volume_promo_mode_a
        """
        ctx = fx.setup_finalized_config_scenario(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        quote = fx.add_quote(ctx["project"]["id"], ctx["config"]["id"], promo_code="SPRING10")
        quote = get_success_data(api.issue_quote(quote["id"], DESIGNER))
        assert quote["subtotal_cents"] == 389200, f"subtotal, got {quote['subtotal_cents']}"
        assert quote["discount_cents"] == 56434, f"discount, got {quote['discount_cents']}"
        assert quote["tax_cents"] == 30781, f"tax, got {quote['tax_cents']}"
        assert quote["total_cents"] == 363547, f"total, got {quote['total_cents']}"

    def test_material_multiplier_applied_before_rounding_to_subtotal(self, api):
        """PRD §3.3: "The pre-multiplier subtotal is multiplied by this material
        multiplier and the result is rounded half up to whole cents — this rounding
        happens *after* the multiply, and the rounded figure is the value stored as the
        quote's `subtotal_cents`."
        PRD §3.3: "`MELAMINE` multiplies by 1.00, `LAMINATE` by 1.15, `WOOD` by 1.40, and
        `PREMIUM_WOOD` by 1.80."

        Design: Difficulty/combinatorial_formula/quote_pricing_tiered_material_volume_promo_mode_a
        """
        # Same WOOD/40-unit config without promo: pre-mult 278000 * 1.40 = 389200 stored.
        ctx = fx.setup_finalized_config_scenario(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        quote = fx.add_quote(ctx["project"]["id"], ctx["config"]["id"])
        quote = get_success_data(api.issue_quote(quote["id"], DESIGNER))
        assert quote["subtotal_cents"] == 389200, f"subtotal post-mult, got {quote['subtotal_cents']}"
        # tier2 (40 units) volume discount only, no promo: 19460.
        assert quote["discount_cents"] == 19460, f"discount, got {quote['discount_cents']}"

    def test_deposit_below_required_floor_rejected_mode_b(self, api):
        """PRD §3.5: "The deposit must be at least the **required deposit floor**, which
        is the accepted (or target) quote's `total_cents` multiplied by a room-type
        percentage, rounded half up to whole cents: the percentage is 0.30 for
        `REACH_IN_CLOSET`, 0.35 for `WALK_IN_CLOSET`, 0.25 for `GARAGE`, 0.30 for
        `PANTRY`, and 0.35 for `HOME_OFFICE`."
        PRD §3.5: "an amount below the floor is rejected with `ERR_DEPOSIT_BELOW_MINIMUM`."

        Design: Difficulty/combinatorial_formula/deposit_requirement_round_after_multiply_mode_b
        """
        ctx = fx.setup_accepted_quote(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        # required floor = round_half_up(403941 * 0.35) = 141379; 141378 is one cent below.
        resp = api.create_deposit(
            f.create_deposit_payload(ctx["project"]["id"], ctx["quote"]["id"], 141378), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM.value)

    def test_deposit_exactly_at_required_floor_accepted_mode_b(self, api):
        """PRD §3.5: "The deposit must be at least the **required deposit floor**, which is
        the accepted (or target) quote's `total_cents` multiplied by a room-type
        percentage, rounded half up to whole cents: the percentage is 0.30 for
        `REACH_IN_CLOSET`, 0.35 for `WALK_IN_CLOSET`, 0.25 for `GARAGE`, 0.30 for
        `PANTRY`, and 0.35 for `HOME_OFFICE`."
        PRD §3.5: "An `amount_cents` greater than or equal to this floor is acceptable"

        Design: Difficulty/combinatorial_formula/deposit_requirement_round_after_multiply_mode_b
        """
        ctx = fx.setup_accepted_quote(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        # exactly the floor 141379 (inclusive >=) is accepted.
        deposit = get_success_data(api.create_deposit(
            f.create_deposit_payload(ctx["project"]["id"], ctx["quote"]["id"], 141379), ADMIN
        ))
        assert deposit["status"] == "PENDING"
        assert deposit["amount_cents"] == 141379

    def test_financing_amortization_circular_dependency_mode_c(self, api):
        """PRD §3.9: "the approved amount is the smaller of the `requested_amount_cents`
        and an approval cap equal to the quote's `total_cents` multiplied by the maximum
        loan-to-value of 0.80, rounded half up to whole cents; `approved_amount_cents` is
        set to this smaller value."
        PRD §3.9: "the monthly payment is the approved amount multiplied by the monthly
        rate, divided by one minus the quantity (one plus the monthly rate) raised to the
        power of the negative term length in months, with the final figure rounded half up
        to whole cents."
        PRD §3.9: "The evaluation order is pinned: the approved amount is computed first,
        then the monthly payment from it."

        Design: Difficulty/combinatorial_formula/financing_amortization_circular_dependency_mode_c
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        app = fx.create_financing_application(proj["id"], quote["id"], 57024, 24, customer["id"])
        fx.submit_financing_application(app["id"], customer["id"])
        decided = fx.financing_decide(app["id"], "APPROVE")
        assert decided["approved_amount_cents"] == 57024, f"approved, got {decided['approved_amount_cents']}"
        assert decided["monthly_payment_cents"] == 2527, f"monthly, got {decided['monthly_payment_cents']}"
        assert decided["status"] == "APPROVED"

    def test_financing_approved_amount_drives_monthly_payment_pinned_order(self, api):
        """PRD §3.9: "the approved amount is the smaller of the `requested_amount_cents`
        and an approval cap equal to the quote's `total_cents` multiplied by the maximum
        loan-to-value of 0.80, rounded half up to whole cents; `approved_amount_cents` is
        set to this smaller value."
        PRD §3.9: "The evaluation order is pinned: the approved amount is computed first,
        then the monthly payment from it."

        Design: Difficulty/combinatorial_formula/financing_amortization_circular_dependency_mode_c
        """
        # requested 57024 == 0.80 * 71280 LTV cap exactly; term 24 -> APR 0.0599 -> 2527.
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        app = fx.create_financing_application(proj["id"], quote["id"], 57024, 24, customer["id"])
        fx.submit_financing_application(app["id"], customer["id"])
        decided = fx.financing_decide(app["id"], "APPROVE")
        # approved equals the LTV cap (0.80 * 71280 = 57024), monthly is amortized from it.
        assert decided["approved_amount_cents"] == 57024
        assert decided["monthly_payment_cents"] == 2527


# ===========================================================================
# Corner — calculations section
# ===========================================================================
class TestCalculationCorners:
    def test_config_total_units_excludes_accessory(self, api):
        """PRD §3.2: "The `total_units` figure is the sum of the `quantity` of every line
        item **except** those whose `component_type` is `ACCESSORY`: accessories are
        priced like any other item but do not count toward the unit total, which means
        they have no effect on the volume discount tier or on crew capacity consumption."

        Design: Corner/calculations/config_total_units_excludes_accessory
        """
        ctx = fx.setup_designing_project(zip_code="90001", room_type="WALK_IN_CLOSET")
        cfg, _ = fx.add_finalized_config(
            ctx["project"]["id"], material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        assert cfg["total_units"] == 40, f"total_units excludes ACCESSORY, got {cfg['total_units']}"

    def test_quote_pricing_melamine_no_discount(self, api):
        """PRD §3.3: "`MELAMINE` multiplies by 1.00, `LAMINATE` by 1.15, `WOOD` by 1.40,
        and `PREMIUM_WOOD` by 1.80."
        PRD §3.3: "`tax_cents` is that taxable base multiplied by the project region's tax
        rate, rounded half up to whole cents; the regional tax rates are 0.0725 for
        `NORTH`, 0.0650 for `SOUTH`, 0.0800 for `EAST`, and 0.0925 for `WEST`."

        Design: Corner/calculations/quote_pricing_melamine_no_discount_correct_result
        """
        ctx = fx.setup_finalized_config_scenario(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        quote = fx.add_quote(ctx["project"]["id"], ctx["config"]["id"])
        quote = get_success_data(api.issue_quote(quote["id"], DESIGNER))
        assert quote["subtotal_cents"] == 66000
        assert quote["discount_cents"] == 0
        assert quote["tax_cents"] == 5280
        assert quote["total_cents"] == 71280

    def test_lead_time_tier_plus_material_plus_region_addons(self, api):
        """PRD §3.5: "A **base lead** is selected by the configuration's `total_units`:
        14 days for 1 through 19 units, 21 days for 20 through 49 units, and 35 days for
        50 or more units. A **material addition** is selected by `material_grade`: 0 days
        for `MELAMINE`, 3 for `LAMINATE`, 7 for `WOOD`, and 14 for `PREMIUM_WOOD`. A
        **region addition** is selected by the project's `install_region`: 0 days for
        `NORTH`, 2 for `SOUTH`, 4 for `EAST`, and 6 for `WEST`. The `lead_time_days` is
        the sum of the base lead, the material addition, and the region addition."

        Design: Corner/calculations/lead_time_threshold_tier_plus_addons
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_deposit_paid(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS, deposit_amount=17820,
        )
        mo = fx.start_manufacture(ctx["manufacture_order"]["id"])
        assert mo["lead_time_days"] == 18, f"lead_time_days, got {mo['lead_time_days']}"
        assert mo["promised_ready_date"].startswith("2026-04-19"), \
            f"promised_ready_date, got {mo['promised_ready_date']}"

    def test_financing_zero_apr_term12_variant(self, api):
        """PRD §3.9: "For the 12-month term, where the APR is zero and the monthly rate
        would make that amortization formula divide by zero, the monthly payment is
        instead simply the approved amount divided by 12, rounded half up to whole cents."

        Design: Corner/calculations/financing_zero_apr_term12_variant
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        app = fx.create_financing_application(proj["id"], quote["id"], 57024, 12, customer["id"])
        fx.submit_financing_application(app["id"], customer["id"])
        decided = fx.financing_decide(app["id"], "APPROVE")
        assert decided["approved_amount_cents"] == 57024
        assert decided["monthly_payment_cents"] == 4752, f"monthly, got {decided['monthly_payment_cents']}"

    def test_financing_ltv_cap_clamps_requested(self, api):
        """PRD §3.9: "the approved amount is the smaller of the `requested_amount_cents`
        and an approval cap equal to the quote's `total_cents` multiplied by the maximum
        loan-to-value of 0.80, rounded half up to whole cents; `approved_amount_cents` is
        set to this smaller value."

        Design: Corner/calculations/financing_ltv_cap_clamps_requested
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        # request the full total 71280 (<= total so submit passes); cap 0.80*71280 = 57024.
        app = fx.create_financing_application(proj["id"], quote["id"], 71280, 36, customer["id"])
        fx.submit_financing_application(app["id"], customer["id"])
        decided = fx.financing_decide(app["id"], "APPROVE")
        assert decided["approved_amount_cents"] == 57024, f"clamped to LTV cap, got {decided['approved_amount_cents']}"
