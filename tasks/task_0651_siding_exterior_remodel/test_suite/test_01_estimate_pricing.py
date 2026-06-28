"""Estimate line-item pricing and totals.

Covers the per-line waste-factor branch (SIDING vs TRIM/WRAP), the combinatorial
conditional-branch calculation, and the pinned round-per-line-then-sum-then-tax
ordering.
"""
import pytest

from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success,
    bootstrap_actors, create_draft_estimate, add_line_item,
)


class TestLineExtendedWasteBranch:
    def test_siding_line_applies_waste_factor_to_extended_cents(self, api):
        """PRD §3.3: "For a `SIDING` line, the effective quantity is the `quantity`
        multiplied by one plus the estimate's `waste_factor_pct` — waste applies to
        siding only."
        PRD §3.3: "The `extended_cents` is the effective quantity multiplied by
        `unit_price_cents`, rounded half-up to a whole cent at the level of the
        individual line, before any summation."

        Design: Difficulty/dual_variant_calc/dual_variant_line_extended_siding_vs_trim
        """
        _proj, _meas, est, actors = create_draft_estimate(waste_factor_pct=0.10)
        siding = add_line_item(est["id"], actors, scope_kind="SIDING",
                               quantity=1000, unit_price_cents=1000)
        # 1000 * (1 + 0.10) * 1000c = 1,100,000c
        assert siding["extended_cents"] == 1100000, \
            f"SIDING extended should apply 0.10 waste, got {siding['extended_cents']}"

    def test_trim_line_omits_waste_factor_from_extended_cents(self, api):
        """PRD §3.3: "For a `TRIM` or `WRAP` line, the effective quantity is simply
        the `quantity`, with no waste multiplier."
        PRD §3.3: "The `extended_cents` is the effective quantity multiplied by
        `unit_price_cents`, rounded half-up to a whole cent at the level of the
        individual line, before any summation."

        Design: Difficulty/dual_variant_calc/dual_variant_line_extended_siding_vs_trim
        """
        _proj, _meas, est, actors = create_draft_estimate(waste_factor_pct=0.10)
        trim = add_line_item(est["id"], actors, scope_kind="TRIM",
                             quantity=1000, unit_price_cents=1000)
        # No waste: 1000 * 1000c = 1,000,000c
        assert trim["extended_cents"] == 1000000, \
            f"TRIM extended should NOT apply waste, got {trim['extended_cents']}"

    def test_identical_inputs_diverge_between_siding_and_trim(self, api):
        """PRD §3.3: "For a `SIDING` line, the effective quantity is the `quantity`
        multiplied by one plus the estimate's `waste_factor_pct` — waste applies to
        siding only."

        Design: Difficulty/dual_variant_calc/dual_variant_line_extended_siding_vs_trim
        """
        _proj, _meas, est, actors = create_draft_estimate(waste_factor_pct=0.10)
        siding = add_line_item(est["id"], actors, scope_kind="SIDING",
                               quantity=1000, unit_price_cents=1000)
        trim = add_line_item(est["id"], actors, scope_kind="TRIM",
                             quantity=1000, unit_price_cents=1000)
        assert siding["extended_cents"] == 1100000
        assert trim["extended_cents"] == 1000000
        assert siding["extended_cents"] != trim["extended_cents"], \
            "Same qty/unit must price differently for SIDING vs TRIM"


class TestCombinatorialLineExtended:
    def test_siding_conditional_branch_extended_value(self, api):
        """PRD §3.3: "For a `SIDING` line, the effective quantity is the `quantity`
        multiplied by one plus the estimate's `waste_factor_pct` — waste applies to
        siding only."
        PRD §3.3: "The `extended_cents` is the effective quantity multiplied by
        `unit_price_cents`, rounded half-up to a whole cent at the level of the
        individual line, before any summation."

        Design: Difficulty/combinatorial_formula/combinatorial_line_extended_conditional_branch
        """
        _proj, _meas, est, actors = create_draft_estimate(waste_factor_pct=0.10)
        line = add_line_item(est["id"], actors, scope_kind="SIDING",
                             quantity=1800, unit_price_cents=500)
        # 1800 * 1.10 * 500c = 990,000c
        assert line["extended_cents"] == 990000, \
            f"Expected 990000, got {line['extended_cents']}"

    def test_wrap_branch_omits_waste_multiplier(self, api):
        """PRD §3.3: "For a `TRIM` or `WRAP` line, the effective quantity is simply
        the `quantity`, with no waste multiplier."
        PRD §3.3: "The `extended_cents` is the effective quantity multiplied by
        `unit_price_cents`, rounded half-up to a whole cent at the level of the
        individual line, before any summation."

        Design: Difficulty/combinatorial_formula/combinatorial_line_extended_conditional_branch
        """
        _proj, _meas, est, actors = create_draft_estimate(waste_factor_pct=0.10)
        line = add_line_item(est["id"], actors, scope_kind="WRAP",
                             quantity=1800, unit_price_cents=80)
        # No waste: 1800 * 80c = 144,000c
        assert line["extended_cents"] == 144000, \
            f"Expected 144000, got {line['extended_cents']}"


class TestEstimateTotalRoundingOrder:
    def test_subtotal_tax_total_round_per_line_then_sum_then_tax(self, api):
        """PRD §3.3: "Sales tax is then computed on that already-per-line-rounded
        subtotal: the `tax_cents` is the subtotal multiplied by the sales tax rate of
        8.25 percent (0.0825), rounded half-up to a whole cent."
        PRD §3.3: "The `estimate_total_cents` is the `line_subtotal_cents` plus the
        `tax_cents`."

        Design: Difficulty/combinatorial_formula/combinatorial_estimate_total_round_per_line_then_sum_then_tax
        """
        _proj, _meas, est, actors = create_draft_estimate(waste_factor_pct=0.10)
        add_line_item(est["id"], actors, scope_kind="SIDING", quantity=1800, unit_price_cents=500)
        add_line_item(est["id"], actors, scope_kind="TRIM", quantity=300, unit_price_cents=300)
        add_line_item(est["id"], actors, scope_kind="WRAP", quantity=1800, unit_price_cents=80)
        fetched = validate_success(_ac.get_estimate(est["id"], actors["est_h"]))
        # subtotal = 990000 + 90000 + 144000 = 1224000; tax = round(1224000*0.0825) = 100980
        assert fetched["line_subtotal_cents"] == 1224000, \
            f"subtotal expected 1224000, got {fetched['line_subtotal_cents']}"
        assert fetched["tax_cents"] == 100980, \
            f"tax expected 100980, got {fetched['tax_cents']}"
        assert fetched["estimate_total_cents"] == 1324980, \
            f"total expected 1324980, got {fetched['estimate_total_cents']}"

    def test_tax_computed_on_rounded_subtotal_not_raw_float(self, api):
        """PRD §3.3: "This evaluation order is mandatory — round each line first, sum
        the rounded lines into the subtotal, then apply tax to that subtotal — and
        produces the canonical total; a raw float sum taxed once at the end is
        incorrect."

        Design: Difficulty/combinatorial_formula/combinatorial_estimate_total_round_per_line_then_sum_then_tax
        """
        _proj, _meas, est, actors = create_draft_estimate(waste_factor_pct=0.10)
        add_line_item(est["id"], actors, scope_kind="SIDING", quantity=1800, unit_price_cents=500)
        add_line_item(est["id"], actors, scope_kind="TRIM", quantity=300, unit_price_cents=300)
        add_line_item(est["id"], actors, scope_kind="WRAP", quantity=1800, unit_price_cents=80)
        fetched = validate_success(_ac.get_estimate(est["id"], actors["est_h"]))
        assert fetched["tax_cents"] == 100980
        assert fetched["estimate_total_cents"] == fetched["line_subtotal_cents"] + fetched["tax_cents"]
