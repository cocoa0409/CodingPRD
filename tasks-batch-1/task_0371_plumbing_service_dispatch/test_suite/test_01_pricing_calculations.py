"""Provisional estimate pricing and final-invoice divergence.

Covers the per-line rounding discipline, the discount-before-trip-waiver order,
the membership-discount cap, the emergency surcharge, and the provisional-versus-
final divergence that arises when actual consumed parts differ from the estimate.

All money is integer cents; the provisional pricing rules are PRD §3.3 and the
final-invoice rules are PRD §3.6.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    create_flat_rate_item, create_part, create_membership_plan,
    setup_presented_estimate, setup_completed_job,
    add_part_line, present_estimate, approve_estimate,
    start_work, complete_job,
    api_client, TEST_USERS,
)

OM = TEST_USERS["office_manager_headers"]

# After-hours windows start at hour >= 18 UTC (PRD §3.2); normal-hours start before 18.
AFTER_HOURS_START = "2026-06-15T18:00:00.000Z"
AFTER_HOURS_END = "2026-06-15T20:00:00.000Z"
AFTER_HOURS_ETA = "2026-06-15T18:15:00.000Z"
NORMAL_START = "2026-06-16T10:00:00.000Z"
NORMAL_END = "2026-06-16T12:00:00.000Z"
NORMAL_ETA = "2026-06-16T10:15:00.000Z"


class TestProvisionalVersusFinalDivergence:
    def test_provisional_estimate_and_final_invoice_totals_diverge(self, api):
        """PRD §3.6: "Because actual consumption may be fewer units than the
        estimate projected, `final_parts_cents` — and therefore `final_total_cents`
        — can diverge from the provisional estimate whenever consumed units differ
        from estimated units."
        PRD §3.6: "The `final_parts_cents` is computed from actual consumption: for
        each distinct consumed part, the part's `list_price_cents` is multiplied by
        the units actually consumed and rounded half-up, and those per-part figures
        are summed."

        Design: Difficulty/dual_variant_calc/provisional_estimate_vs_final_invoice_total_diverge
        """
        # After-hours job: three FLAT_RATE labor lines + one PART line projected at 3,
        # but only 2 units actually consumed at completion.
        plan = create_membership_plan(tier_code="NONE", name="No Plan",
                                      labor_discount_pct=0, waives_trip_fee=False,
                                      annual_fee_cents=0)
        fr_a = create_flat_rate_item(code="DV-A", category="LEAK",
                                     base_price_cents=10067, skill_required=2)
        fr_b = create_flat_rate_item(code="DV-B", category="LEAK",
                                     base_price_cents=5067, skill_required=2)
        fr_c = create_flat_rate_item(code="DV-C", category="LEAK",
                                     base_price_cents=3067, skill_required=1)
        part = create_part(sku="DV-P", name="Valve", list_price_cents=1999)

        scenario = setup_completed_job(
            flat_rate_lines=[{"item": fr_a, "quantity": 1},
                             {"item": fr_b, "quantity": 1},
                             {"item": fr_c, "quantity": 1}],
            part_lines=[{"part": part, "quantity": 3}],
            consumed_parts=[{"part_id": part["id"], "units": 2}],
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "LEAK", "priority": "STANDARD"},
            window_start=AFTER_HOURS_START, window_end=AFTER_HOURS_END,
            eta=AFTER_HOURS_ETA)

        estimate = get_success_data(
            api.get_estimate(scenario["estimate"]["id"], OM))
        assert estimate["estimate_total_cents"] == 42200, \
            f"provisional total expected 42200, got {estimate['estimate_total_cents']}"

        inv_data, _meta = self._list(api.list_job_invoices(scenario["job"]["id"], OM))
        assert len(inv_data) == 1, "completion must create exactly one invoice"
        invoice = inv_data[0]
        assert invoice["final_parts_cents"] == 3998, \
            f"final_parts_cents expected 3998 (1999*2), got {invoice['final_parts_cents']}"
        assert invoice["final_total_cents"] == 40201, \
            f"final_total_cents expected 40201, got {invoice['final_total_cents']}"
        assert estimate["estimate_total_cents"] != invoice["final_total_cents"], \
            "estimate total and invoice total must diverge when consumed != estimated"

    @staticmethod
    def _list(response):
        body = response.json()
        return body.get("data", []), body.get("meta", {})


class TestPerLineRoundingOrder:
    def test_labor_subtotal_rounds_per_line_not_on_sum(self, api):
        """PRD §2.8: "Rounding is pinned at the per-line level and at the discount:
        each estimate line's unit price and line total are rounded as they are
        computed, and the line totals are then summed without any further rounding
        of the sum."
        PRD §3.3: "the after-hours multiplier is 1.5 when the job's `after_hours` is
        true and 1.0 otherwise."

        Design: Difficulty/combinatorial_formula/estimate_per_line_rounding_order_pinned_mode_b
        """
        # After-hours unit prices end in half-cents: 10067*1.5=15100.5 -> 15101,
        # 5067*1.5=7600.5 -> 7601, 3067*1.5=4600.5 -> 4601. Per-line sum = 27303.
        # Summing the raw .5 values then rounding once gives 27302 — the wrong order.
        fr_a = create_flat_rate_item(code="RB-A", category="DRAIN",
                                     base_price_cents=10067, skill_required=2)
        fr_b = create_flat_rate_item(code="RB-B", category="DRAIN",
                                     base_price_cents=5067, skill_required=2)
        fr_c = create_flat_rate_item(code="RB-C", category="DRAIN",
                                     base_price_cents=3067, skill_required=1)

        scenario = setup_presented_estimate(
            flat_rate_lines=[{"item": fr_a, "quantity": 1},
                             {"item": fr_b, "quantity": 1},
                             {"item": fr_c, "quantity": 1}],
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "DRAIN", "priority": "STANDARD"},
            window_start=AFTER_HOURS_START, window_end=AFTER_HOURS_END,
            eta=AFTER_HOURS_ETA)

        estimate = scenario["estimate"]
        assert estimate["labor_subtotal_cents"] == 27303, \
            f"per-line rounding must yield 27303, got {estimate['labor_subtotal_cents']}"
        assert estimate["labor_subtotal_cents"] != 27302, \
            "27302 would mean the sum was rounded once instead of per line"


class TestTripFeeWaiverOrder:
    def test_trip_fee_waiver_keyed_on_post_discount_labor(self, api):
        """PRD §3.3: "The labor-after-discount figure is the labor subtotal minus
        this discount. The trip fee is then decided: the fee is waived — set to 0 —
        when the customer's plan has `waives_trip_fee` true, or when the labor-after-
        discount figure is at least the trip-waive threshold of 50000 cents; otherwise
        the trip fee is the base trip fee of 8900 cents."

        Design: Difficulty/combinatorial_formula/trip_fee_waiver_keyed_on_post_discount_labor_mode_c
        """
        # SILVER (0.10, waives_trip_fee=false), raw labor 52000 > 50000 threshold,
        # but discount applies FIRST (5200), labor_after=46800 (<50000) so trip IS charged.
        plan = create_membership_plan(tier_code="SILVER", name="Silver",
                                      labor_discount_pct=0.10, waives_trip_fee=False,
                                      annual_fee_cents=12000)
        fr = create_flat_rate_item(code="TW-1", category="WATER_HEATER",
                                   base_price_cents=52000, skill_required=2)

        scenario = setup_presented_estimate(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            customer_overrides={"membership_plan_id": plan["id"],
                                "credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "WATER_HEATER", "priority": "STANDARD"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)

        estimate = scenario["estimate"]
        assert estimate["discount_cents"] == 5200, \
            f"discount expected 5200 (round(52000*0.10)), got {estimate['discount_cents']}"
        assert estimate["trip_fee_cents"] == 8900, \
            f"trip fee must be charged (labor_after 46800 < 50000), got {estimate['trip_fee_cents']}"
        assert estimate["estimate_total_cents"] == 55700, \
            f"total expected 55700, got {estimate['estimate_total_cents']}"


class TestCalculationCorners:
    def test_emergency_surcharge_applied_for_emergency_priority(self, api):
        """PRD §3.3: "The emergency surcharge is 12000 cents when the job's
        `priority` is `EMERGENCY`, and 0 otherwise."

        Design: Corner/calculations/emergency_surcharge_applied_for_emergency_priority
        """
        fr = create_flat_rate_item(code="EM-1", category="LEAK",
                                   base_price_cents=30000, skill_required=1)
        scenario = setup_presented_estimate(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "LEAK", "priority": "EMERGENCY"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)

        estimate = scenario["estimate"]
        assert estimate["emergency_surcharge_cents"] == 12000, \
            f"emergency surcharge expected 12000, got {estimate['emergency_surcharge_cents']}"
        assert estimate["trip_fee_cents"] == 8900, \
            "labor_after 30000 < 50000 so trip fee 8900 is charged"
        assert estimate["estimate_total_cents"] == 50900, \
            f"total expected 30000+8900+12000=50900, got {estimate['estimate_total_cents']}"

    def test_membership_discount_capped_at_max(self, api):
        """PRD §3.3: "the discount is the labor subtotal multiplied by the customer's
        plan `labor_discount_pct` (0 when the customer has no plan or is tier `NONE`),
        rounded half-up, and then capped so that it never exceeds 15000 cents."

        Design: Corner/calculations/membership_discount_capped_at_max
        """
        plan = create_membership_plan(tier_code="GOLD", name="Gold",
                                      labor_discount_pct=0.20, waives_trip_fee=True,
                                      annual_fee_cents=24000)
        fr = create_flat_rate_item(code="CAP-1", category="REPIPE",
                                   base_price_cents=100000, skill_required=2)
        scenario = setup_presented_estimate(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            customer_overrides={"membership_plan_id": plan["id"],
                                "credit_limit_cents": 1000000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "REPIPE", "priority": "STANDARD"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)

        estimate = scenario["estimate"]
        assert estimate["discount_cents"] == 15000, \
            f"discount of 20000 must cap at 15000, got {estimate['discount_cents']}"
        assert estimate["trip_fee_cents"] == 0, \
            "GOLD waives_trip_fee -> trip fee 0"
        assert estimate["estimate_total_cents"] == 85000, \
            f"total expected 100000-15000=85000, got {estimate['estimate_total_cents']}"
