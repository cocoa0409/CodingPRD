"""Dual-variant and combinatorial money calculations: estimate totals
(AERIAL vs FIELD), round-per-line-then-sum ordering, material sizing, and the
warranty refund variants (PRORATED vs SHORT_RATE).

Queue A: dual_variant_calc, combinatorial_formula.
Queue B (calculations section): aerial result is owned by the difficulty
instance; the remaining calculation corners live in later files.
"""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_estimator_payload, create_job_payload, create_estimate_payload,
    create_line_item_payload, create_warranty_payload, cancel_warranty_payload,
    setup_active_warranty, set_clock,
)

EST = TEST_USERS["estimator_headers"]
FA = TEST_USERS["field_adjuster_headers"]
PM = TEST_USERS["production_manager_headers"]

# Three identical line items used on both an AERIAL and a FIELD estimate of the
# same job. Subtotal 525400; AERIAL adds +8% => 567432; FIELD stays 525400.
DIVERGENCE_LINES = [
    {"trade": "SHINGLE", "squares": 20, "unit_price_cents": 18000, "waste_factor_pct": 0.15},
    {"trade": "UNDERLAYMENT", "squares": 20, "unit_price_cents": 4200, "waste_factor_pct": 0.10},
    {"trade": "RIDGE_VENT", "squares": 2, "unit_price_cents": 9500, "waste_factor_pct": 0},
]


def _make_estimate(api, job_id, source_kind, lines, aerial_contingency_pct=None):
    payload = create_estimate_payload(job_id=job_id, source_kind=source_kind)
    if aerial_contingency_pct is not None:
        payload["aerial_contingency_pct"] = aerial_contingency_pct
    est = get_success_data(api.create_estimate(payload, EST))
    for li in lines:
        api.add_line_item(est["id"], create_line_item_payload(**li), EST)
    return get_success_data(api.finalize_estimate(est["id"], EST))


def _fresh_job(api):
    est = get_success_data(api.create_estimator(create_estimator_payload(), EST))
    return get_success_data(api.create_job(
        create_job_payload(assigned_estimator_id=est["id"]), FA))["id"]


class TestEstimateVariantDivergence:
    def test_aerial_estimate_applies_contingency_uplift(self, api):
        """PRD §3.2: "for an `AERIAL` estimate it is the `line_subtotal_cents`
        multiplied by one plus the `aerial_contingency_pct`, rounded half-up to
        a whole cent; for a `FIELD` estimate it is exactly the
        `line_subtotal_cents` with no uplift."

        Design: Difficulty/dual_variant_calc/estimate_aerial_vs_field_diverge
        """
        job_id = _fresh_job(api)
        aerial = _make_estimate(api, job_id, "AERIAL", DIVERGENCE_LINES,
                                aerial_contingency_pct=0.08)
        assert aerial["line_subtotal_cents"] == 525400
        assert aerial["final_total_cents"] == 567432

    def test_field_estimate_has_no_contingency_and_diverges_from_aerial(self, api):
        """PRD §3.2: "for an `AERIAL` estimate it is the `line_subtotal_cents`
        multiplied by one plus the `aerial_contingency_pct`, rounded half-up to
        a whole cent; for a `FIELD` estimate it is exactly the
        `line_subtotal_cents` with no uplift."

        Design: Difficulty/dual_variant_calc/estimate_aerial_vs_field_diverge
        """
        job_id = _fresh_job(api)
        aerial = _make_estimate(api, job_id, "AERIAL", DIVERGENCE_LINES,
                                aerial_contingency_pct=0.08)
        field = _make_estimate(api, job_id, "FIELD", DIVERGENCE_LINES)
        assert field["final_total_cents"] == 525400
        assert aerial["final_total_cents"] - field["final_total_cents"] == 42032


class TestWarrantyRefundVariants:
    # Premium 120000, term 120mo, 18 months elapsed (start 2026-01-01, cancel
    # clock 2027-07-01). remaining=102 => PRORATED 102000, SHORT_RATE 91800.
    def test_short_rate_refund_applies_ten_percent_penalty(self, api):
        """PRD §3.10: "On a `SHORT_RATE` basis the `refund_cents` is the
        prorated figure multiplied by 0.90, rounded half-up to a whole cent — a
        10 percent short-rate penalty against the proration."

        Design: Difficulty/dual_variant_calc/warranty_prorated_vs_short_rate_diverge
        """
        job_id, war, _ = setup_active_warranty(
            premium_cents=120_000, term_months=120, start_clock="2026-01-01T00:00:00Z")
        set_clock("2027-07-01T00:00:00Z")  # 18 months elapsed
        data = validate_success(api.cancel_warranty(
            war["id"], cancel_warranty_payload(cancel_basis="SHORT_RATE"), PM))
        assert data["status"] == "CANCELLED"
        assert data["refund_cents"] == 91800

    def test_prorated_refund_is_full_unearned_proration(self, api):
        """PRD §3.10: "On a `PRORATED` basis the `refund_cents` is exactly that
        prorated figure — the full unearned proration."

        Design: Difficulty/dual_variant_calc/warranty_prorated_vs_short_rate_diverge
        """
        job_id, war, _ = setup_active_warranty(
            premium_cents=120_000, term_months=120, start_clock="2026-01-01T00:00:00Z")
        set_clock("2027-07-01T00:00:00Z")  # 18 months elapsed
        data = validate_success(api.cancel_warranty(
            war["id"], cancel_warranty_payload(cancel_basis="PRORATED"), PM))
        assert data["status"] == "CANCELLED"
        assert data["refund_cents"] == 102000


class TestCombinatorialRounding:
    def test_round_per_line_then_sum_order_is_observable(self, api):
        """PRD §3.2: "The order is pinned — each line is rounded first, and only
        then are the rounded lines summed (round-per-line-then-sum, never
        sum-then-round); the distinction is observable when fractional cents
        straddle a rounding boundary."

        Design: Difficulty/combinatorial_formula/estimate_round_per_line_then_sum_order
        """
        job_id = _fresh_job(api)
        # 10 / 10.25 / 10.5 squares, waste 0.10, unit 1850.
        # Per-line rounded: 20350 + 20859 + 21368 = 62577 (sum-then-round=62576).
        lines = [
            {"trade": "SHINGLE", "squares": 10, "unit_price_cents": 1850, "waste_factor_pct": 0.10},
            {"trade": "UNDERLAYMENT", "squares": 10.25, "unit_price_cents": 1850, "waste_factor_pct": 0.10},
            {"trade": "DECKING", "squares": 10.5, "unit_price_cents": 1850, "waste_factor_pct": 0.10},
        ]
        est = _make_estimate(api, job_id, "FIELD", lines)
        assert est["line_subtotal_cents"] == 62577
        assert est["final_total_cents"] == 62577

    def test_field_subtotal_equals_final_with_no_uplift(self, api):
        """PRD §3.2: "for a `FIELD` estimate it is exactly the
        `line_subtotal_cents` with no uplift."

        Design: Difficulty/combinatorial_formula/estimate_round_per_line_then_sum_order
        """
        job_id = _fresh_job(api)
        lines = [
            {"trade": "SHINGLE", "squares": 10, "unit_price_cents": 1850, "waste_factor_pct": 0.10},
            {"trade": "UNDERLAYMENT", "squares": 10.25, "unit_price_cents": 1850, "waste_factor_pct": 0.10},
            {"trade": "DECKING", "squares": 10.5, "unit_price_cents": 1850, "waste_factor_pct": 0.10},
        ]
        est = _make_estimate(api, job_id, "FIELD", lines)
        assert est["final_total_cents"] == est["line_subtotal_cents"] == 62577
