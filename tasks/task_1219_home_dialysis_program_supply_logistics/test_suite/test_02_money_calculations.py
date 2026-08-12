"""Combinatorial money formulas: return credit (mode a), handling fee per-line
rounding (mode b), grand total discount keyed on subtotal (mode c)."""
from test_helpers import (
    validate_success, get_success_data, make_patient_headers,
    create_active_home_patient, create_draft_order,
    setup_active_patient_with_delivered_order,
    report_waste_return, verify_waste_return, get_patient,
)


class TestReturnCreditTieredOverageAndExpiry:
    """Mode (a) — nested min() over line units, delivered attribution minus
    prior returns, and remaining full-credit tier, with expiry zeroing."""

    def test_first_return_consumes_full_credit_tier(self, api):
        """PRD §3.8: "A full-credit allowance of ten units per sku per month
        applies: units previously credited for that sku and month consume the
        allowance (counted only up to ten), and the full-credit portion of this
        line is the smaller of its eligible units and the allowance remaining."

        Design: Difficulty/combinatorial_formula/return_credit_tiered_overage_and_expiry
        """
        ctx = setup_active_patient_with_delivered_order(order_qty=20,
                                                        delivered_qty=15)
        pat = ctx["patient"]["id"]
        ret = report_waste_return(
            pat, "RETURN", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 6, "expired": False}])
        credited = verify_waste_return(ret["id"], approved=True)
        assert credited["status"] == "CREDITED"
        assert credited["credit_cents"] == 1800, (
            "6 eligible, all inside the full tier: 6 * 300 = 1800")
        assert get_patient(pat)["on_hand_units"] == 9, "15 - 6 = 9"

    def test_overage_and_expired_line_credit(self, api):
        """PRD §3.8: "Whatever eligible units exceed the full-credit portion
        form the overage. The line's credit is the full-credit portion times
        the catalog `unit_credit_cents`, plus the overage times
        `unit_credit_cents` times one half, that overage product rounded half
        up to whole cents"
        PRD §3.8: "An `expired` line earns zero."

        Design: Difficulty/combinatorial_formula/return_credit_tiered_overage_and_expiry
        """
        ctx = setup_active_patient_with_delivered_order(order_qty=20,
                                                        delivered_qty=15)
        pat = ctx["patient"]["id"]
        ret1 = report_waste_return(
            pat, "RETURN", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 6, "expired": False}])
        verify_waste_return(ret1["id"], approved=True)
        # Second return: eligible min(5, 15-6)=5; full portion min(5, 10-6)=4
        # -> 1200; overage 1 -> round_half_up(1*300*0.5)=150.
        ret2 = report_waste_return(
            pat, "RETURN", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 5, "expired": False}])
        credited2 = verify_waste_return(ret2["id"], approved=True)
        assert credited2["credit_cents"] == 1350, (
            "4 full-tier units (1200) + 1 overage unit at half rate (150)")
        # Expired line earns zero even though 2 units remain attributable.
        ret3 = report_waste_return(
            pat, "RETURN", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 2, "expired": True}])
        credited3 = verify_waste_return(ret3["id"], approved=True)
        assert credited3["status"] == "CREDITED"
        assert credited3["credit_cents"] == 0, "expired lines earn zero credit"
        assert get_patient(pat)["on_hand_units"] == 2, "15 - 6 - 5 - 2 = 2"


class TestHandlingFeePerLineRounding:
    """Mode (b) — per-line round-half-up then sum; sum-then-round forbidden."""

    def test_fractional_half_cent_lines_round_per_line(self, api):
        """PRD §2.9: "First, per-line rounding precedes summation for both the
        order handling fee and the return credit: each line amount is rounded
        half up to whole cents on its own, and only the rounded line amounts
        are summed — the sum-then-round order is forbidden, because the two
        orders diverge whenever fractional half-cent line amounts pair up (two
        lines rated at 10.5 and 12.5 cents round to 11 and 13 and total 24
        per-line, versus 23 if summed first)."

        Design: Difficulty/combinatorial_formula/handling_fee_per_line_rounding_beats_sum_rounding
        """
        catalog = [
            {"sku": "DIALYSATE_2L", "name": "Dialysate 2L bag",
             "unit_price_cents": 1200, "handling_rate_cents": 10.5,
             "unit_credit_cents": 300},
            {"sku": "FILTER_CART", "name": "Filter cartridge",
             "unit_price_cents": 5000, "handling_rate_cents": 12.5,
             "unit_credit_cents": 1500},
        ]
        ctx = create_active_home_patient(catalog=catalog)
        pat = ctx["patient"]["id"]
        order = create_draft_order(
            pat, "2026-05",
            [{"sku": "DIALYSATE_2L", "quantity": 1},
             {"sku": "FILTER_CART", "quantity": 1}])
        assert order["handling_fee_cents"] == 524, (
            "500 + round_half_up(10.5)=11 + round_half_up(12.5)=13 = 524")
        assert order["subtotal_cents"] == 6200

    def test_fee_recomputed_on_line_edit(self, api):
        """PRD §3.5: "`handling_fee_cents` is a 500-cent base plus a per-line
        charge: each line's quantity multiplied by its catalog
        `handling_rate_cents`, rounded half up to whole cents per line, and
        only then summed — the per-line rounding discipline of §2.9 is pinned,
        so two lines rated 10.5 and 12.5 cents contribute 11 and 13, never a
        rounded-down 23."
        PRD §3.5: "A patient edits `lines` while the order is `DRAFT` or
        `CHANGES_REQUESTED` (from any other state, `ERR_ORDER_INVALID_STATE`);
        editing a `CHANGES_REQUESTED` order returns it to `DRAFT`, and every
        edit recomputes all money fields."

        Design: Difficulty/combinatorial_formula/handling_fee_per_line_rounding_beats_sum_rounding
        """
        catalog = [
            {"sku": "DIALYSATE_2L", "name": "Dialysate 2L bag",
             "unit_price_cents": 1200, "handling_rate_cents": 10.5,
             "unit_credit_cents": 300},
            {"sku": "FILTER_CART", "name": "Filter cartridge",
             "unit_price_cents": 5000, "handling_rate_cents": 12.5,
             "unit_credit_cents": 1500},
        ]
        ctx = create_active_home_patient(catalog=catalog)
        pat = ctx["patient"]["id"]
        order = create_draft_order(
            pat, "2026-05", [{"sku": "DIALYSATE_2L", "quantity": 1}])
        assert order["handling_fee_cents"] == 511, "500 + round_half_up(10.5)"
        edited = validate_success(api.patch_supply_order(
            order["id"],
            {"lines": [{"sku": "DIALYSATE_2L", "quantity": 1},
                       {"sku": "FILTER_CART", "quantity": 1}]},
            make_patient_headers(pat)))
        assert edited["handling_fee_cents"] == 524, (
            "edit recomputes the fee with per-line rounding")


class TestGrandTotalDiscountKeyedOnSubtotal:
    """Mode (c) — 5% discount keyed on subtotal (never post-discount total)."""

    def test_discount_at_below_above_threshold(self, api):
        """PRD §3.5: "`discount_cents` is five percent of the subtotal rounded
        half up when the subtotal reaches twenty thousand cents, and zero
        otherwise; eligibility is keyed on `subtotal_cents` and never on the
        post-discount total, so an order sitting exactly at the threshold
        receives its discount."

        Design: Difficulty/combinatorial_formula/grand_total_discount_keyed_on_subtotal_not_total
        """
        catalog = [
            {"sku": "DIALYSATE_2L", "name": "Dialysate 2L bag",
             "unit_price_cents": 1200, "handling_rate_cents": 10.5,
             "unit_credit_cents": 300},
            {"sku": "TUBING_SET", "name": "Tubing set",
             "unit_price_cents": 3400, "handling_rate_cents": 25,
             "unit_credit_cents": 800},
            {"sku": "CONCENTRATE_5L", "name": "Concentrate 5L",
             "unit_price_cents": 4000, "handling_rate_cents": 20,
             "unit_credit_cents": 1000},
        ]
        ctx = create_active_home_patient(catalog=catalog)
        pat = ctx["patient"]["id"]
        # Below threshold: 5 x 3400 = 17000 -> no discount; fee 500 + 5*25=625.
        ord_a = create_draft_order(pat, "2026-05",
                                   [{"sku": "TUBING_SET", "quantity": 5}])
        assert ord_a["discount_cents"] == 0
        assert ord_a["grand_total_cents"] == 17625
        # Exactly at threshold: 5 x 4000 = 20000 -> discount 1000; fee 600.
        ord_b = create_draft_order(pat, "2026-05",
                                   [{"sku": "CONCENTRATE_5L", "quantity": 5}])
        assert ord_b["discount_cents"] == 1000
        assert ord_b["grand_total_cents"] == 19600, (
            "20000 - 1000 + 600; the >= threshold fires at exactly 20000")
        # Above threshold: 17 x 1200 = 20400 -> discount 1020; fee
        # 500 + round_half_up(17*10.5)=179 -> 679.
        ord_c = create_draft_order(pat, "2026-05",
                                   [{"sku": "DIALYSATE_2L", "quantity": 17}])
        assert ord_c["discount_cents"] == 1020
        assert ord_c["grand_total_cents"] == 20059

    def test_discount_eligibility_uses_subtotal_not_grand_total(self, api):
        """PRD §2.9: "Second, the order grand total follows a fixed evaluation
        order — exact subtotal first, then the volume discount keyed on that
        subtotal (never on the post-discount total), then the grand total — as
        specified in §3.5."

        Design: Difficulty/combinatorial_formula/grand_total_discount_keyed_on_subtotal_not_total
        """
        catalog = [
            {"sku": "TUBING_SET", "name": "Tubing set",
             "unit_price_cents": 3400, "handling_rate_cents": 25,
             "unit_credit_cents": 800},
        ]
        ctx = create_active_home_patient(catalog=catalog)
        pat = ctx["patient"]["id"]
        # 6 x 3400 = 20400 subtotal; discount 1020; fee 500 + 6*25 = 650;
        # grand 20030. If the discount were keyed on the post-discount total
        # (19380 < 20000), no discount would apply — the observed 1020 proves
        # the subtotal key.
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "TUBING_SET", "quantity": 6}])
        assert order["subtotal_cents"] == 20400
        assert order["discount_cents"] == 1020, (
            "keyed on subtotal 20400, not the post-discount figure")
        assert order["grand_total_cents"] == 20400 - 1020 + 650
