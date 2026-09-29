"""Which inputs a calculation is allowed to see, and where its tiers switch.

A multiplier tier that is off by one enrollee, a downtime figure that swallowed a
neighbouring month, a reconciliation that averaged in data nobody had adjudicated
and a posture ladder read exclusively rather than inclusively all produce numbers
that look plausible. Each case pins the boundary or the input set exactly.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    CYCLE_MISSED,
    DEFICIENCY_GAG_CLAUSE,
    DEFICIENCY_MRF_REFRESH,
    POSTURE_DEFICIENT,
    POSTURE_FROZEN,
    RX_ASSEMBLING,
    RX_RECONCILED,
    SECTION_D6_RX_TOTALS,
    SECTION_D7_RX_REBATES,
    VENDOR_TYPE_PBM,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

TIER_CLOCK = "2027-06-15T09:00:00Z"
TOOL_LAUNCH_CLOCK = "2027-05-01T09:00:00Z"
OUTAGE_CLOCK = "2027-07-01T09:00:00Z"
RECONCILE_CLOCK = "2027-08-01T09:00:00Z"
LADDER_OPEN_CLOCK = "2027-03-01T09:00:00Z"
ESCALATION_CLOCK = "2027-05-01T09:00:00Z"
LADDER_RUN_CLOCK = "2027-05-10T09:00:00Z"

TIERS = (
    ("Tier Probe A", "PY2027-T499", 499, 1.0),
    ("Tier Probe B", "PY2027-T500", 500, 1.5),
    ("Tier Probe C", "PY2027-T4999", 4999, 1.5),
    ("Tier Probe D", "PY2027-T5000", 5000, 2.0),
)

MAY_WINDOW = {
    "window_start": "2027-05-20T00:00:00Z",
    "window_end": "2027-05-20T10:00:00Z",
    "cause": "Datacenter migration",
}
JUNE_FIRST_WINDOW = {
    "window_start": "2027-06-10T00:00:00Z",
    "window_end": "2027-06-10T03:00:00Z",
    "cause": "Rate table reload failure",
}
JUNE_TOUCHING_WINDOW = {
    "window_start": "2027-06-10T03:00:00Z",
    "window_end": "2027-06-10T04:12:00Z",
    "cause": "Continued reload failure",
}
JUNE_DISJOINT_WINDOW = {
    "window_start": "2027-06-20T01:00:00Z",
    "window_end": "2027-06-20T02:00:00Z",
    "cause": "Certificate rotation",
}

D6_FIGURES = {
    "record_count": 1200,
    "plan_paid_cents": 6_000_000,
    "member_paid_cents": 1_000_000,
    "rebate_cents": 1_500_000,
}
D7_FIGURES = {
    "record_count": 800,
    "plan_paid_cents": 2_500_000,
    "member_paid_cents": 500_000,
    "rebate_cents": 900_000,
}


def _partially_validated_submission(api: ApiClient) -> dict:
    """Two delivered packages of which only the first has been adjudicated."""
    fx.set_clock(api, RECONCILE_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    plan_year_id = setup["plan_year"]["id"]
    pbm = fx.add_contract_for_vendor_type(
        api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
    )
    fx.contract_with_secured_data_rights(api, pbm["contract"]["id"])
    submission = fx.open_rx_submission(api, plan_year_id, reference_year=2026)

    first = fx.request_package(
        api,
        submission["id"],
        pbm["vendor"]["id"],
        data_section=SECTION_D6_RX_TOTALS,
        expected_record_count=1200,
    )
    second = fx.request_package(
        api,
        submission["id"],
        pbm["vendor"]["id"],
        data_section=SECTION_D7_RX_REBATES,
        expected_record_count=800,
    )
    fx.validated_package(api, first["id"], pbm["vendor"]["id"], **D6_FIGURES)
    fx.delivered_package(api, second["id"], pbm["vendor"]["id"], **D7_FIGURES)
    return {
        "plan_year_id": plan_year_id,
        "submission_id": submission["id"],
        "unvalidated_package_id": second["id"],
    }


class TestSizeMultiplierTiers:
    """The enrolled headcount picks a multiplier before any money is priced."""

    def test_the_headcount_tiers_switch_at_five_hundred_and_five_thousand(
        self, api: ApiClient
    ) -> None:
        """499, 500, 4999 and 5000 lives read 1.0, 1.5, 1.5 and 2.0.

        PRD 3.9: "The `size_multiplier` is selected from the plan year's enrolled
        headcount: a plan with fewer than 500 `covered_lives` takes 1.0, a plan
        with at least 500 and at most 4,999 takes 1.5, and a plan with 5,000 or
        more takes 2.0."

        PRD 3.9: "The projection is derived from **live open child state, never
        from the ledger**, and it returns one object containing
        `statutory_maximum_cents`, `accrued_to_date_cents`,
        `open_deficiency_count` and the `size_multiplier` used."

        Design: Corner/calculations/size_multiplier_tier_boundaries_at_499_500_and_5000
        """
        fx.set_clock(api, TIER_CLOCK)
        observed = []
        for sponsor_name, label, covered_lives, expected_multiplier in TIERS:
            plan_year = fx.create_plan_year(
                api,
                sponsor_name=sponsor_name,
                plan_year_label=label,
                covered_lives=covered_lives,
            )
            projection = fx.read_penalty_projection(api, plan_year["id"])
            observed.append((covered_lives, projection["size_multiplier"]))
            assert projection["size_multiplier"] == expected_multiplier
            assert projection["open_deficiency_count"] == 0
            assert projection["accrued_to_date_cents"] == 0
            assert projection["statutory_maximum_cents"] == 0

        assert observed == [(499, 1.0), (500, 1.5), (4999, 1.5), (5000, 2.0)]


class TestMonthlyUptimeInputSet:
    """A month is scored from its own clipped, merged downtime and nothing else."""

    def test_a_neighbouring_month_is_clipped_out_before_the_windows_merge(
        self, api: ApiClient
    ) -> None:
        """Ten hours of May downtime contribute nothing to June's score.

        PRD 3.3: "Every recorded outage window is then clipped to that month's
        window and any window whose clipped result is empty is discarded."

        PRD 3.3: "The sorted windows are then merged: a window is merged into the
        one before it whenever its `window_start` falls at or before the running
        interval's `window_end` — so windows that overlap *and* windows that
        merely touch collapse into a single stretch of downtime."

        Design: Corner/calculations/tool_uptime_merges_touching_windows_and_clips_other_months
        """
        fx.set_clock(api, TOOL_LAUNCH_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        tool = fx.live_price_comparison_tool(
            api,
            setup["plan_year"]["id"],
            tool_name="Meridian Cost Estimator",
            covered_items_count=800,
        )

        fx.set_clock(api, OUTAGE_CLOCK)
        for window in (
            MAY_WINDOW,
            JUNE_FIRST_WINDOW,
            JUNE_TOUCHING_WINDOW,
            JUNE_DISJOINT_WINDOW,
        ):
            validate_success(
                api.append_outage_window(
                    tool["id"],
                    f.outage_window_payload(**window),
                    PLATFORM_OPERATOR_HEADERS,
                )
            )

        scored = validate_success(
            api.evaluate_price_comparison_tool(
                tool["id"],
                f.evaluation_payload(evaluation_month="2027-06"),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        # 180 and 72 minutes merge into 252; the disjoint hour stands alone.
        assert scored["last_downtime_minutes"] == 312
        assert scored["last_uptime_pct"] == 99.28
        assert scored["last_evaluated_month"] == "2027-06"
        assert scored["sla_breach_open"] is False
        assert scored["breach_onset_date"] is None

        stored = validate_success(
            api.get_price_comparison_tool(tool["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert len(stored["outage_windows"]) == 4

        plan_year = fx.read_plan_year(api, setup["plan_year"]["id"])
        assert plan_year["deficiency_points"] == 0
        assert plan_year["tool_sla_breach_count"] == 0
        assert plan_year["penalty_exposure_cents"] == 0


class TestReconciliationInputSet:
    """Only adjudicated packages are allowed to move the filing's figures."""

    def test_a_partly_adjudicated_submission_will_not_reconcile_at_all(
        self, api: ApiClient
    ) -> None:
        """It does not quietly total the validated subset either.

        PRD 2.9: "**Validated package set.** On prescription-drug reconciliation
        and filing — two operations — the submission has at least one vendor data
        package and every one of them has `status` `VALIDATED`, otherwise
        `ERR_PACKAGES_NOT_VALIDATED` (409)."

        Design: Corner/calculations/rxdc_reconciliation_totals_only_over_validated_packages
        """
        built = _partially_validated_submission(api)

        response = api.reconcile_rx_submission(
            built["submission_id"], COMPLIANCE_OFFICER_HEADERS
        )
        validate_error(
            response, ApiErrorId.PACKAGES_NOT_VALIDATED, expected_status=409
        )

        unchanged = validate_success(
            api.get_rx_submission(built["submission_id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert unchanged["status"] == RX_ASSEMBLING
        assert unchanged["gross_spend_cents"] is None
        assert unchanged["rebate_reported_cents"] is None
        assert unchanged["rebate_cap_pct"] is None
        assert unchanged["reconciled_at"] is None
        # Only the adjudicated package has been counted in.
        assert unchanged["assembled_record_count"] == 1200

    def test_adjudicating_the_second_package_totals_both_of_them(
        self, api: ApiClient
    ) -> None:
        """Ten million cents of gross spend picks the middle cap tier.

        PRD 3.6: "As a worked illustration, two validated packages contributing
        6,000,000 and 2,500,000 cents of plan-paid spend, 1,000,000 and 500,000
        cents of member-paid spend, and 1,500,000 and 900,000 cents of rebates
        yield gross spend of 10,000,000 cents, reported rebates of 2,400,000
        cents, a cap tier of 0.20, a credit of 2,000,000 cents because the capped
        figure is the smaller of the two, and net plan spend of 8,000,000 cents."

        Design: Corner/calculations/rxdc_reconciliation_totals_only_over_validated_packages
        """
        built = _partially_validated_submission(api)
        validate_error(
            api.reconcile_rx_submission(
                built["submission_id"], COMPLIANCE_OFFICER_HEADERS
            ),
            ApiErrorId.PACKAGES_NOT_VALIDATED,
        )

        validate_success(
            api.validate_package(
                built["unvalidated_package_id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        reconciled = validate_success(
            api.reconcile_rx_submission(
                built["submission_id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert reconciled["status"] == RX_RECONCILED
        assert reconciled["gross_spend_cents"] == 10_000_000
        assert reconciled["rebate_reported_cents"] == 2_400_000
        assert reconciled["rebate_cap_pct"] == 0.20
        assert reconciled["rebate_credit_cents"] == 2_000_000
        assert reconciled["net_plan_spend_cents"] == 8_000_000
        assert_instant_equals(reconciled["reconciled_at"], RECONCILE_CLOCK)

        stored = validate_success(
            api.get_rx_submission(built["submission_id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert stored["assembled_record_count"] == 2000

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["deficiency_points"] == 0
        assert plan_year["penalty_exposure_cents"] == 0


class TestPostureLadderThresholds:
    """Six points and twelve points are each reached exactly, not approached."""

    def test_six_points_is_deficient_and_twelve_is_frozen_without_a_freeze(
        self, api: ApiClient
    ) -> None:
        """One escalated contract, then two missed months, walks 6 to 12.

        PRD 2.8: "The posture ladder is then evaluated top down, and both
        thresholds are inclusive. If `freeze_flag` is true, or `deficiency_points`
        is 12 or more, the posture is `FROZEN`. Otherwise, if `deficiency_points`
        is 6 or more, the posture is `DEFICIENT`. Otherwise, if
        `deficiency_points` is at least 1, the posture is `AT_RISK`. Otherwise the
        posture is `COMPLIANT`. A plan year starts life with `deficiency_points`
        of 0 and a posture of `COMPLIANT`. Exactly 6 points is `DEFICIENT`;
        exactly 12 is `FROZEN`."

        Design: Corner/calculations/posture_thresholds_inclusive_at_six_and_twelve_points
        """
        fx.set_clock(api, LADDER_OPEN_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        pbm = fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
        )
        march = fx.open_refresh_cycle(
            api,
            plan_year_id,
            period_month="2027-03",
            period_start="2027-03-01",
            period_end="2027-03-31",
        )
        april = fx.open_refresh_cycle(
            api,
            plan_year_id,
            period_month="2027-04",
            period_start="2027-04-01",
            period_end="2027-04-30",
        )

        fx.set_clock(api, ESCALATION_CLOCK)
        fx.open_gag_review(
            api,
            pbm["contract"]["id"],
            clause_inventory_count=22,
            prohibited_clause_count=3,
            review_note="Three gag clauses on cost data.",
        )
        validate_success(
            api.escalate_gag(
                pbm["contract"]["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.escalate_gag_payload(escalation_note="Vendor refuses removal."),
            )
        )
        at_six = fx.read_plan_year(api, plan_year_id)
        assert at_six["deficiency_points"] == 6
        assert at_six["compliance_posture"] == POSTURE_DEFICIENT
        assert at_six["penalty_exposure_cents"] == 30_000

        fx.set_clock(api, LADDER_RUN_CLOCK)
        summary = validate_success(
            api.run_compliance(plan_year_id, PLATFORM_OPERATOR_HEADERS)
        )
        assert summary["posture_before"] == POSTURE_DEFICIENT
        assert summary["posture_after"] == POSTURE_FROZEN
        assert summary["cycles_missed_count"] == 2
        assert summary["accruals_posted_count"] == 2
        assert summary["deficiency_points"] == 12
        assert summary["penalty_exposure_cents"] == 830_000

        at_twelve = fx.read_plan_year(api, plan_year_id)
        assert at_twelve["compliance_posture"] == POSTURE_FROZEN
        assert at_twelve["freeze_flag"] is False
        assert at_twelve["freeze_reason"] is None

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 3
        assert [
            (entry["deficiency_type"], entry["signed_amount_cents"], entry["days_open"])
            for entry in entries
        ] == [
            (DEFICIENCY_GAG_CLAUSE, 30_000, 1),
            (DEFICIENCY_MRF_REFRESH, 700_000, 35),
            (DEFICIENCY_MRF_REFRESH, 100_000, 5),
        ]
        assert [entry["onset_date"] for entry in entries] == [
            "2027-05-01",
            "2027-04-06",
            "2027-05-06",
        ]

        assert (
            validate_success(
                api.get_refresh_cycle(march["id"], COMPLIANCE_OFFICER_HEADERS)
            )["status"]
            == CYCLE_MISSED
        )
        assert (
            validate_success(
                api.get_refresh_cycle(april["id"], COMPLIANCE_OFFICER_HEADERS)
            )["status"]
            == CYCLE_MISSED
        )
