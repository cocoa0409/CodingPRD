"""Derived finance: variance alerting, revised forecast, realization, quotes."""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    add_approved_entry,
    add_billed_entry,
    add_client,
    add_matter,
    add_time_entry,
    add_timekeeper,
    api_client,
    apply_approved_write_down,
    approve_entry,
    assert_matter,
    get_matter,
    make_billing_partner_headers,
    setup_active_matter,
    setup_firm,
    submit_entry,
    validate_success,
)


class TestVarianceAlertCascade:

    def test_approve_cascades_to_breach_alert(self):
        """PRD section 3.4: "Approval lands financially: the entry's
        `billable_amount_cents` is added to the matter's `actual_fees_cents`;
        the variance trio `variance_cents`, `variance_pct_bp`, and
        `variance_alert_level` is recomputed; and the matter's
        `last_activity_period_index` — the period of its most recent
        time-entry, write-down, or amendment activity, consulted by the
        closed-period guard on amendments — is set to the firm's current
        period."
        PRD section 3.5: "Otherwise a value of at least 2000 basis points —
        twenty percent over budget — raises `BREACH`; a value of at least
        1000 basis points, ten percent, raises `WARNING`; a value of at
        least 500 basis points, five percent, raises `WATCH`; anything lower
        is `NONE`."

        Design: Difficulty/transitive_cascade/time_entry_approve_cascade_to_alert_level
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        entry = add_time_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                               ctx["partner"]["id"], 125000)
        submit_entry(ctx["firm"]["id"], entry["id"], ctx["partner"]["id"])

        approve_entry(ctx["firm"]["id"], entry["id"], ctx["partner"]["id"])

        matter = get_matter(ctx["matter"]["id"])
        assert_matter(matter)
        assert matter["actual_fees_cents"] == 125000
        assert matter["variance_cents"] == 25000, (
            f"variance must be 125000 - 100000 = 25000, got "
            f"{matter['variance_cents']}")
        assert matter["variance_pct_bp"] == 2500, (
            f"round(10000 * 25000 / 100000) must be 2500 bp, got "
            f"{matter['variance_pct_bp']}")
        assert matter["variance_alert_level"] == "BREACH", (
            f"2500 bp >= 2000 bp must raise BREACH, got "
            f"{matter['variance_alert_level']}")

    def test_variance_exactly_at_breach_threshold(self):
        """PRD section 3.5: "Alerting is threshold-driven, and the
        thresholds are boundary-pinned — a value exactly on a threshold
        escalates. When `variance_pct_bp` is null, `variance_alert_level` is
        `NONE`. Otherwise a value of at least 2000 basis points — twenty
        percent over budget — raises `BREACH`; a value of at least 1000
        basis points, ten percent, raises `WARNING`; a value of at least 500
        basis points, five percent, raises `WATCH`; anything lower is
        `NONE`."

        Design: Difficulty/boundary_precision_check/variance_threshold_exact_breach_boundary
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        # Exactly 20% over budget: variance 20000 -> exactly 2000 bp.
        entry = add_time_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                               ctx["partner"]["id"], 120000)
        submit_entry(ctx["firm"]["id"], entry["id"], ctx["partner"]["id"])
        approve_entry(ctx["firm"]["id"], entry["id"], ctx["partner"]["id"])

        matter = get_matter(ctx["matter"]["id"])
        assert matter["variance_pct_bp"] == 2000, (
            f"variance must be exactly 2000 bp, got "
            f"{matter['variance_pct_bp']}")
        assert matter["variance_alert_level"] == "BREACH", (
            "a value exactly on the 2000 bp threshold must escalate to "
            f"BREACH (at-least semantics), got "
            f"{matter['variance_alert_level']}")


class TestVarianceNetAfterWriteDown:

    def test_variance_uses_net_after_write_down(self):
        """PRD section 3.5: "Its `actual_fees_cents` is the sum of
        `billable_amount_cents` over entries in `APPROVED`, `BILLED`, or
        `WRITTEN_DOWN`, with one caveat: a `WRITTEN_DOWN` entry contributes
        its post-write-down remainder — its original amount minus its
        allocated write-down share — rather than its original amount."
        PRD section 3.5: "Two readings of variance exist: the gross reading,
        used for early-warning alerting, counts `WRITTEN_DOWN` entries at
        their original `billable_amount_cents`; the net reading, used for
        reporting and realization, counts their post-write-down remainder."

        Design: Difficulty/dual_variant_calc/matter_variance_gross_vs_net_divergence
        """
        ctx = setup_active_matter(
            with_second_partner=True,
            phases=[{"task_code": "L110", "budget": 100000}])
        e1 = add_billed_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                              ctx["partner"]["id"], 40000,
                              ctx["partner"]["id"])
        add_billed_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                         ctx["partner"]["id"], 30000, ctx["partner"]["id"])

        apply_approved_write_down(ctx["firm"]["id"], ctx["matter"]["id"],
                                  [e1["id"]], 10000, ctx["partner"]["id"],
                                  ctx["partner2"]["id"])

        matter = get_matter(ctx["matter"]["id"])
        # Net reading: 70000 - 10000 write-down = 60000 actual.
        assert matter["actual_fees_cents"] == 60000, (
            f"post-write-down actual must be 60000, got "
            f"{matter['actual_fees_cents']}")
        assert matter["write_down_total_cents"] == 10000
        resp = api_client.get_matter_variance(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        snapshot = validate_success(resp, 200)
        assert snapshot["variance_cents"] == -40000, (
            f"net variance must be 60000 - 100000 = -40000, got "
            f"{snapshot['variance_cents']}; the gross reading would be "
            f"-30000, so the two variants diverge by the write-down amount")

    def test_realization_switches_reading_after_write_down(self):
        """PRD section 3.5: "When the matter has no applied write-downs —
        `write_down_total_cents` is zero — the collected reading applies,
        and `realization_rate_bp` is exactly 10000, one hundred percent,
        regardless of outstanding accruals. Once at least one write-down has
        been applied, the billing reading applies: `realization_rate_bp` is
        ten thousand times `actual_fees_cents`, divided by the sum of
        `actual_fees_cents` and `write_down_total_cents`, rounded half-up to
        the nearest basis point."

        Design: Difficulty/dual_variant_calc/realization_rate_billing_vs_collected_selection
        """
        ctx = setup_active_matter(
            with_second_partner=True,
            phases=[{"task_code": "L110", "budget": 100000}])
        e1 = add_billed_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                              ctx["partner"]["id"], 40000,
                              ctx["partner"]["id"])

        pre = get_matter(ctx["matter"]["id"])
        assert pre["realization_rate_bp"] == 10000, (
            "with zero applied write-downs the collected reading must be "
            f"exactly 10000 bp, got {pre['realization_rate_bp']}")

        apply_approved_write_down(ctx["firm"]["id"], ctx["matter"]["id"],
                                  [e1["id"]], 10000, ctx["partner"]["id"],
                                  ctx["partner2"]["id"])

        post = get_matter(ctx["matter"]["id"])
        assert post["write_down_total_cents"] == 10000
        assert post["actual_fees_cents"] == 30000
        # Billing reading: round(10000 * 30000 / (30000 + 10000)) = 7500.
        assert post["realization_rate_bp"] == 7500, (
            f"billing reading must be round(10000 * 30000 / 40000) = 7500 "
            f"bp, got {post['realization_rate_bp']}")


class TestForecastAndSnapshot:

    def test_variance_pct_null_when_no_budget(self):
        """PRD section 3.5: "The signed `variance_cents` is
        `actual_fees_cents` minus `budget_total_cents`. When
        `budget_total_cents` is zero, `variance_pct_bp` is null; otherwise
        it is ten thousand times `variance_cents`, divided by
        `budget_total_cents`, rounded half-up to the nearest basis point."
        PRD section 3.5: "When `variance_pct_bp` is null,
        `variance_alert_level` is `NONE`."

        Design: Corner/calculations/variance_pct_bp_null_when_budget_zero
        """
        firm = setup_firm()
        tk = add_timekeeper(firm["id"])
        client = add_client(firm["id"])
        matter = add_matter(firm["id"], client["id"], tk["id"],
                            litigation_stage="INTAKE")

        fetched = get_matter(matter["id"])
        assert fetched["budget_total_cents"] == 0
        assert fetched["variance_pct_bp"] is None, (
            "variance_pct_bp must be null when budget_total_cents is zero, "
            f"got {fetched['variance_pct_bp']}")
        assert fetched["variance_alert_level"] == "NONE"

    def test_forecast_is_actual_plus_etc(self):
        """PRD section 3.5: "`revised_forecast_cents`, the estimate at
        completion, is the matter's `actual_fees_cents` plus the sum of
        `etc_cents` across its phases in `ACTIVE` or `AMENDED`."

        Design: Corner/calculations/revised_forecast_includes_actual_plus_etc
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000,
                     "etc_cents": 20000}])
        add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                           ctx["partner"]["id"], 50000, ctx["partner"]["id"])

        matter = get_matter(ctx["matter"]["id"])
        assert matter["revised_forecast_cents"] == 70000, (
            f"forecast must be 50000 actual + 20000 etc = 70000, got "
            f"{matter['revised_forecast_cents']}")

    def test_variance_snapshot_returns_computed_fields(self):
        """PRD section 3.5: "A dedicated variance snapshot capability
        returns the matter's `variance_cents`, `variance_pct_bp`,
        `variance_alert_level`, `revised_forecast_cents`, and
        `realization_rate_bp` on demand."
        PRD section 3.5: "When the matter has no applied write-downs —
        `write_down_total_cents` is zero — the collected reading applies,
        and `realization_rate_bp` is exactly 10000, one hundred percent,
        regardless of outstanding accruals."

        Design: Corner/endpoints/variance_endpoint_computed_read
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                           ctx["partner"]["id"], 50000, ctx["partner"]["id"])

        resp = api_client.get_matter_variance(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        snapshot = validate_success(resp, 200)
        assert snapshot["variance_cents"] == -50000
        assert snapshot["variance_pct_bp"] == -5000, (
            f"round(10000 * -50000 / 100000) must be -5000 bp, got "
            f"{snapshot['variance_pct_bp']}")
        assert snapshot["variance_alert_level"] == "NONE", (
            "negative variance is below every threshold and must be NONE")
        assert snapshot["revised_forecast_cents"] == 50000
        assert snapshot["realization_rate_bp"] == 10000

    def test_etc_patch_refreshes_forecast(self):
        """PRD section 3.3: "Finally, the pricing office maintains
        forward-looking estimates directly on the phase: updating
        `etc_cents` on an active phase budget — a capability shared by
        `PricingAnalyst` and `BillingPartner` — immediately refreshes the
        matter's `revised_forecast_cents` per the forecast rule in §3.5."

        Design: Corner/endpoints/phase_budget_etc_patch_recomputes_forecast
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000,
                     "etc_cents": 10000}])
        phase = ctx["phases"]["L110"]

        resp = api_client.update_phase_budget_etc(
            phase["id"], {"etc_cents": 30000}, ANALYST)
        updated = validate_success(resp, 200)
        assert updated["etc_cents"] == 30000

        matter = get_matter(ctx["matter"]["id"])
        assert matter["revised_forecast_cents"] == 30000, (
            f"forecast must be 0 actual + 30000 etc = 30000, got "
            f"{matter['revised_forecast_cents']}")

    def test_flat_fee_quote_replaces_phase_sum(self):
        """PRD section 3.5: "The total, returned as `total_quote_cents`
        alongside the `phase_quotes` array, is then determined by type:
        under `FLAT_FEE` the total is exactly `flat_fee_cents`, replacing
        the phase sum entirely; under `SUCCESS_FEE` the summed phase quotes
        are multiplied by one plus `success_fee_uplift_pct_bp`
        ten-thousandths, with the product rounded half-up to a whole cent;
        under `CAPPED_FEE` and `COLLAR` the total is the sum of the rounded
        phase quotes, the collar itself being resolved only at year-end (see
        §3.9)."

        Design: Corner/endpoints/quote_endpoint_flat_fee_returns_flat_amount
        """
        ctx = setup_active_matter(
            arrangement_overrides={"flat_fee_cents": 75000},
            phases=[{"task_code": "L110", "budget": 60000},
                    {"task_code": "L210", "budget": 40000}])

        resp = api_client.get_matter_quote(
            ctx["firm"]["id"], ctx["matter"]["id"], ANALYST,
            params={"arrangement_type": "FLAT_FEE"})
        quote = validate_success(resp, 200)
        assert quote["total_quote_cents"] == 75000, (
            f"FLAT_FEE total must be exactly flat_fee_cents (75000), "
            f"replacing the 100000 phase sum; got "
            f"{quote['total_quote_cents']}")

    def test_derived_fields_reconcile_per_approval(self):
        """PRD section 2.10: "When a time entry is approved, a write-down is
        applied, a budget amendment is approved, or a phase budget is
        activated or voided, the matter's derived aggregates —
        `budget_total_cents`, `actual_fees_cents`, `write_down_total_cents`,
        `variance_cents`, `variance_pct_bp`, `variance_alert_level`,
        `revised_forecast_cents`, and `realization_rate_bp` — are recomputed
        as part of the same operation."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_after_time_entry_approve
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        e1 = add_time_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                            ctx["partner"]["id"], 30000)
        e2 = add_time_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                            ctx["partner"]["id"], 25000,
                            entry_date="2026-08-06")
        submit_entry(ctx["firm"]["id"], e1["id"], ctx["partner"]["id"])
        submit_entry(ctx["firm"]["id"], e2["id"], ctx["partner"]["id"])

        approve_entry(ctx["firm"]["id"], e1["id"], ctx["partner"]["id"])
        matter = get_matter(ctx["matter"]["id"])
        assert matter["actual_fees_cents"] == 30000
        assert matter["variance_cents"] == -70000, (
            f"after first approval variance must be 30000 - 100000, got "
            f"{matter['variance_cents']}")

        approve_entry(ctx["firm"]["id"], e2["id"], ctx["partner"]["id"])
        matter = get_matter(ctx["matter"]["id"])
        assert matter["actual_fees_cents"] == 55000
        assert matter["variance_cents"] == -45000, (
            f"after second approval variance must be 55000 - 100000, got "
            f"{matter['variance_cents']}")
