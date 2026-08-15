"""Accruals, matter forecasts, and the advisory staffing ratio (PRD §3.3, §3.5, §3.7)."""
import pytest

from test_helpers import (
    clean_line,
    create_accrual,
    create_approved_rate_card,
    create_engaged_matter,
    get_forecast,
    get_matter,
    ops_headers,
    put_forecast,
    register_and_qualify_timekeeper,
    set_clock,
    setup_billing_ready,
    setup_department_with_firm,
    submit_invoice,
    validate_success,
)


class TestForecastEvaluationOrder:
    """billed_to_date -> wip -> variance is the pinned evaluation order."""

    def _setup_partial_match(self, api):
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        matter_id = ctx["matter"]["id"]
        put_forecast(dept_id, matter_id, 10_000_000)
        # Move the logical clock into September so the 2026-09 accrual period is
        # not in the future (PRD §3.7 rejects future accrual periods).
        set_clock("2026-09-15T00:00:00Z")
        create_accrual(dept_id, matter_id, firm_id, 2026, 8, 2_000_000)
        create_accrual(dept_id, matter_id, firm_id, 2026, 9, 3_000_000)
        # Accrual creation mutates the matter's spend counters, which bumps its
        # version (PRD §2.4): re-read before the OCC-guarded invoice submission.
        current_v = get_matter(dept_id, matter_id)["version"]
        # Invoice covering [2026-08-01, 2026-09-01) matches only the 2026-08 accrual.
        submit_invoice(
            dept_id, matter_id, firm_id, current_v,
            [clean_line(ctx["timekeeper"]["id"], "L110", 15.00, 100_000)],
            invoice_number="INV-F-1",
        )
        return ctx

    def test_forecast_wip_and_variance_after_partial_match(self, api):
        """PRD §3.7: "First, `billed_to_date_cents` is read from the matter as already maintained by the invoice side effects of §3.5. Second, `wip_estimate_cents` is computed as the sum of `amount_cents` over the matter's accruals whose `matched_invoice_id` is still null. Third, `variance_cents` is the lifecycle estimate minus the sum of billed-to-date and work-in-progress; a negative variance signals a projected overrun."

        Design: Difficulty/combinatorial_formula/forecast_evaluation_order_breaks_circle
        """
        ctx = self._setup_partial_match(api)
        fc = get_forecast(ctx["dept"]["id"], ctx["matter"]["id"])
        assert fc["wip_estimate_cents"] == 3_000_000, (
            f"only the unmatched 2026-09 accrual feeds wip, got {fc['wip_estimate_cents']}"
        )
        # variance = 10000000 - (1500000 billed + 3000000 wip)
        assert fc["variance_cents"] == 5_500_000, (
            f"variance must be lifecycle - (billed + wip) = 5500000, got {fc['variance_cents']}"
        )

    def test_matter_spend_counters_after_partial_match(self, api):
        """PRD §3.5: "Landing on `APPROVED` or `PARTIALLY_APPROVED` books spend — the matter's `billed_to_date_cents` increases by the invoice's `approved_total_cents` — and consumes accruals: every unmatched accrual whose period month falls on or after `billing_period_start` and before `billing_period_end` has its `matched_invoice_id` set to this invoice, and the matter's `accrual_outstanding_cents` decreases by each matched accrual's `amount_cents`."
        PRD §3.7: "Creation adds the accrual's `amount_cents` to the matter's `accrual_outstanding_cents` and triggers recomputation of the forecast's work-in-progress figure."

        Design: Difficulty/combinatorial_formula/forecast_evaluation_order_breaks_circle
        """
        ctx = self._setup_partial_match(api)
        matter = get_matter(ctx["dept"]["id"], ctx["matter"]["id"])
        assert matter["billed_to_date_cents"] == 1_500_000, (
            f"the approved invoice books 1500000, got {matter['billed_to_date_cents']}"
        )
        assert matter["accrual_outstanding_cents"] == 3_000_000, (
            f"5000000 accrued minus the matched 2000000, got {matter['accrual_outstanding_cents']}"
        )


def test_forecast_put_creates_then_updates(api, legal_ops_headers):
    """PRD §3.7: "Each matter carries a one-to-one forecast. A `LegalOpsReviewer` creates-or-replaces it by setting `lifecycle_estimate_cents`, the department's estimate of total matter spend"
    PRD §3.7: "Third, `variance_cents` is the lifecycle estimate minus the sum of billed-to-date and work-in-progress; a negative variance signals a projected overrun."

    Design: Corner/endpoints/forecast_put_creates_then_updates
    """
    ctx = setup_billing_ready()
    dept_id, matter_id = ctx["dept"]["id"], ctx["matter"]["id"]

    first = validate_success(
        api.put_forecast(dept_id, matter_id, {"lifecycle_estimate_cents": 1_000_000}, legal_ops_headers)
    )
    # No billed spend and no unmatched accruals: variance equals the estimate.
    assert first["variance_cents"] == 1_000_000, (
        f"variance = estimate - (0 + 0), got {first['variance_cents']}"
    )
    second = validate_success(
        api.put_forecast(dept_id, matter_id, {"lifecycle_estimate_cents": 2_000_000}, legal_ops_headers)
    )
    assert second["lifecycle_estimate_cents"] == 2_000_000, (
        f"the 1:1 forecast updates in place, got {second['lifecycle_estimate_cents']}"
    )
    assert second["variance_cents"] == 2_000_000
    assert second["matter_id"] == matter_id


def test_accrual_matched_by_invoice_in_period(api, legal_ops_headers):
    """PRD §3.5: "Landing on `APPROVED` or `PARTIALLY_APPROVED` books spend — the matter's `billed_to_date_cents` increases by the invoice's `approved_total_cents` — and consumes accruals: every unmatched accrual whose period month falls on or after `billing_period_start` and before `billing_period_end` has its `matched_invoice_id` set to this invoice, and the matter's `accrual_outstanding_cents` decreases by each matched accrual's `amount_cents`."

    Design: Corner/calculations/accrual_matched_by_invoice_in_period
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    matter_id = ctx["matter"]["id"]
    accrual = create_accrual(dept_id, matter_id, firm_id, 2026, 8, 500_000)
    assert get_matter(dept_id, matter_id)["accrual_outstanding_cents"] == 500_000

    # Accrual creation bumped the matter's version (PRD §2.4): re-read it for
    # the OCC-guarded invoice submission.
    current_v = get_matter(dept_id, matter_id)["version"]
    invoice = submit_invoice(
        dept_id, matter_id, firm_id, current_v,
        [clean_line(ctx["timekeeper"]["id"], "L110", 5.00, 100_000)],
        invoice_number="INV-AC",
    )
    acc_after = validate_success(api.get_accrual(dept_id, matter_id, accrual["id"], legal_ops_headers))
    assert acc_after["matched_invoice_id"] is not None, "the in-period accrual must be matched"
    assert acc_after["matched_invoice_id"] == invoice["id"], (
        f"the accrual binds to this invoice, got {acc_after['matched_invoice_id']}"
    )
    matter = get_matter(dept_id, matter_id)
    assert matter["accrual_outstanding_cents"] == 0, (
        f"the matched accrual leaves outstanding, got {matter['accrual_outstanding_cents']}"
    )


class TestStaffingRatioBases:
    """The advisory staffing read exposes billed-hours and headcount bases that
    deliberately disagree on identical underlying data."""

    def _setup_mixed_staffing(self, api):
        dept, firm = setup_department_with_firm(partner_ratio_min_pct=10, partner_ratio_max_pct=90)
        tk_p = register_and_qualify_timekeeper(dept["id"], firm["id"], "Partner1", "PARTNER")
        tk_a1 = register_and_qualify_timekeeper(dept["id"], firm["id"], "Assoc1", "ASSOCIATE")
        tk_a2 = register_and_qualify_timekeeper(dept["id"], firm["id"], "Assoc2", "ASSOCIATE")
        tk_a3 = register_and_qualify_timekeeper(dept["id"], firm["id"], "Assoc3", "ASSOCIATE")
        create_approved_rate_card(
            dept["id"], firm["id"],
            [(tk_p["id"], 100_000), (tk_a1["id"], 50_000), (tk_a2["id"], 50_000), (tk_a3["id"], 50_000)],
            effective_year=2026,
        )
        matter = create_engaged_matter(dept["id"], firm["id"], title="Matter S", budget_cents=100_000_000)
        # Billed partner share: 50 / (50 + 10) * 100 = 83.3333 at 4-decimal precision.
        # Headcount partner share: 1 / 4 = 25%.
        submit_invoice(
            dept["id"], matter["id"], firm["id"], matter["version"],
            [clean_line(tk_p["id"], "L110", 50.00, 100_000, narrative="Strategy L110"),
             clean_line(tk_a1["id"], "L120", 10.00, 50_000, narrative="Research L120")],
            invoice_number="INV-S-001",
        )
        return dept, matter

    def test_staffing_ratio_billed_hours_basis_value(self, api, legal_ops_headers):
        """PRD §3.3: "By default — `basis` equal to `BILLED_HOURS` — it answers on the billed-hours basis described in §3.5"
        PRD §3.5: "The staffing-ratio rule evaluates the matter on the billed-hours basis: partner hours are the summed `hours` of lines billed by `PARTNER` timekeepers in the approved-equivalent statuses `APPROVED`, `ADJUSTED_APPROVED`, or `REINSTATED` across all non-`VOID` invoices of the matter; total hours are the same sum over all classes in those statuses; the ratio is null when total hours are zero, and otherwise the partner share times one hundred, computed at four-decimal precision."

        Design: Difficulty/dual_variant_calc/staffing_ratio_billed_vs_headcount_basis
        """
        dept, matter = self._setup_mixed_staffing(api)
        data = validate_success(api.get_staffing_ratio(dept["id"], matter["id"], legal_ops_headers))
        assert data["basis"] == "BILLED_HOURS"
        assert data["partner_share_pct"] == pytest.approx(83.3333, abs=1e-4), (
            f"50/60 * 100 at 4-decimal precision, got {data['partner_share_pct']}"
        )

    def test_staffing_ratio_headcount_basis_value(self, api, legal_ops_headers):
        """PRD §3.3: "passing `basis` as `HEADCOUNT` switches to the headcount-weighted basis — the share of `PARTNER` timekeepers among the firm's `QUALIFIED` timekeepers, ignoring actual billing entirely. The two bases deliberately produce different percentages for identical underlying data."

        Design: Difficulty/dual_variant_calc/staffing_ratio_billed_vs_headcount_basis
        """
        dept, matter = self._setup_mixed_staffing(api)
        billed = validate_success(api.get_staffing_ratio(dept["id"], matter["id"], legal_ops_headers))
        headcount = validate_success(
            api.get_staffing_ratio(dept["id"], matter["id"], legal_ops_headers, params={"basis": "HEADCOUNT"})
        )
        assert headcount["basis"] == "HEADCOUNT"
        assert headcount["partner_share_pct"] == pytest.approx(25.00, abs=1e-4), (
            f"1 partner among 4 QUALIFIED timekeepers, got {headcount['partner_share_pct']}"
        )
        assert headcount["partner_share_pct"] != pytest.approx(billed["partner_share_pct"]), (
            "the two bases must disagree on identical underlying data"
        )


def test_staffing_ratio_at_exact_min_compliant(api, legal_ops_headers):
    """PRD §3.5: "A ratio strictly below `partner_ratio_min_pct` or strictly above `partner_ratio_max_pct` is a violation — exactly at either boundary is compliant — and offending lines are rejected with reason `STAFFING_RATIO`."
    PRD §3.3: "The response carries the computed `partner_share_pct`, the `basis` used, and a `compliant` flag reflecting the department's band."

    Design: Corner/calculations/staffing_ratio_at_exact_min_compliant
    """
    dept, firm = setup_department_with_firm(partner_ratio_min_pct=10, partner_ratio_max_pct=90)
    tk_p = register_and_qualify_timekeeper(dept["id"], firm["id"], "P", "PARTNER")
    tk_a = register_and_qualify_timekeeper(dept["id"], firm["id"], "A", "ASSOCIATE")
    create_approved_rate_card(
        dept["id"], firm["id"], [(tk_p["id"], 100_000), (tk_a["id"], 50_000)], effective_year=2026,
    )
    matter = create_engaged_matter(dept["id"], firm["id"], title="M", budget_cents=100_000_000)
    # 10 / (10 + 90) * 100 = 10.0000 — exactly at the inclusive lower boundary.
    submit_invoice(
        dept["id"], matter["id"], firm["id"], matter["version"],
        [clean_line(tk_p["id"], "L110", 10.00, 100_000),
         clean_line(tk_a["id"], "L120", 90.00, 50_000)],
        invoice_number="INV-SR",
    )
    data = validate_success(api.get_staffing_ratio(dept["id"], matter["id"], legal_ops_headers))
    assert data["partner_share_pct"] == pytest.approx(10.0000, abs=1e-4), (
        f"partner share must be exactly 10.0000, got {data['partner_share_pct']}"
    )
    assert data["compliant"] is True, "exactly at the min boundary is compliant"
