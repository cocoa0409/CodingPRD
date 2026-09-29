"""Derived arithmetic: reserve sizing, trailing windows, detector scores and the forecast."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_beneficial_owner,
    advance_to_underwriting,
    api_client,
    create_assessment,
    create_batch,
    create_category_rule,
    create_draft_application,
    create_forecast,
    day_start,
    evaluate_month,
    activate_program,
    ingest_activity,
    list_reserve_ledger,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    onboard_standard_merchant,
    open_program,
    OwnerSpec,
    pay_batch,
    read_merchant,
    read_reserve_account,
    record_verification,
    release_request_payload,
    run_monitoring,
    screen_owner,
    set_clock,
    submit_application,
    terminate_merchant,
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    chargeback_day_overrides,
)


def _application_in_underwriting(api, **overrides):
    """Walk a fresh application to UNDERWRITING and return its id and current version."""
    application_id = create_draft_application(api, **overrides)["id"]
    owner = add_beneficial_owner(
        api, application_id, full_name="Ola Bergman", ownership_pct=100.00
    )
    submit_application(api, application_id)
    record_verification(api, application_id)
    screen_owner(api, owner["id"])
    advanced = advance_to_underwriting(api, application_id)
    return application_id, advanced["version"]


class TestReserveSizing:
    """The exposure floor and the single conditional uplift the category table contributes."""

    def test_the_exposure_floor_lifts_a_zero_lag_assessment_to_one_average_day(self):
        """A zero-lag applicant has no in-flight goods, so one average day is the floor.

        PRD 3.4: "Whichever method ran, `exposure_estimate_cents` is the greater of the raw exposure
        and the one-average-day figure, so estimated in-flight exposure never falls below a single
        day of requested volume."

        PRD 3.4: "First compute the monthly hold: `requested_monthly_volume_cents` multiplied by
        `reserve_pct_bps`, divided by 10000, rounded half up **once** to whole cents. Then multiply
        that rounded integer by 6 cap months. `reserve_cap_cents` is the lesser of that six-month
        figure and twice `exposure_estimate_cents`."

        Design: Corner/calculations/reserve_exposure_floor_lifts_a_zero_lag_assessment_to_one_day
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id, version = _application_in_underwriting(
            api, legal_business_name="Fernbrook Tea LLC"
        )

        assessment = create_assessment(api, application_id, version, "LAG_WEIGHTED")

        assert assessment["assessment_sequence"] == 1
        assert assessment["credit_band"] == "B"
        assert assessment["base_reserve_bps"] == 500
        assert assessment["lag_uplift_bps"] == 0
        assert assessment["chargeback_uplift_bps"] == 0
        assert assessment["thin_file_uplift_bps"] == 0
        assert assessment["mcc_uplift_bps"] == 0
        assert assessment["reserve_pct_bps"] == 500
        assert assessment["exposure_estimate_cents"] == 1_000_000
        assert assessment["reserve_cap_cents"] == 2_000_000
        assert assessment["reserve_type"] == "ROLLING"

    def test_the_category_uplift_applies_only_to_a_restricted_review_rule(self):
        """Four hundred basis points of restricted-review uplift count; a prohibited rule's do not.

        PRD 3.4: "`mcc_uplift_bps` is the `reserve_uplift_bps` of the screening rule whose
        `mcc_code` equals the application's `mcc_code`, but only when that rule's `disposition` is
        `RESTRICTED_REVIEW`; when no rule matches, or the matching rule is `PROHIBITED`,
        `mcc_uplift_bps` is 0."

        Design: Corner/calculations/mcc_reserve_uplift_applies_only_to_a_restricted_review_rule
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        create_category_rule(
            api,
            "7995",
            category="INBOUND_TELEMARKETING",
            disposition="RESTRICTED_REVIEW",
            reserve_uplift_bps=400,
        )

        restricted_id, restricted_version = _application_in_underwriting(
            api, legal_business_name="Fernbrook Tea LLC", mcc_code="7995"
        )
        restricted = create_assessment(api, restricted_id, restricted_version, "LAG_WEIGHTED")
        assert restricted["mcc_uplift_bps"] == 400
        assert restricted["reserve_pct_bps"] == 900
        assert restricted["reserve_type"] == "ROLLING"
        assert restricted["reserve_cap_cents"] == 2_000_000

        prohibited_id, prohibited_version = _application_in_underwriting(
            api, legal_business_name="Larkmead Supply LLC", mcc_code="5967"
        )
        create_category_rule(
            api,
            "5967",
            category="ADULT_CONTENT",
            disposition="PROHIBITED",
            reserve_uplift_bps=700,
        )
        prohibited = create_assessment(api, prohibited_id, prohibited_version, "LAG_WEIGHTED")
        assert prohibited["mcc_uplift_bps"] == 0
        assert prohibited["reserve_pct_bps"] == 500

        plain_id, plain_version = _application_in_underwriting(
            api, legal_business_name="Ridgeline Cycles LLC"
        )
        plain = create_assessment(api, plain_id, plain_version, "LAG_WEIGHTED")
        assert plain["mcc_uplift_bps"] == 0
        assert plain["reserve_pct_bps"] == 500


class TestTrailingWindowsAndTheTwoRatioVariants:
    """The closed 30-day window, its zero-denominator answers, and the two disagreeing ratios."""

    def test_the_trailing_window_excludes_the_row_thirty_days_back(self):
        """A row 30 days before the window end is outside the closed 30-day window.

        PRD 3.6: "The window is 30 days long and closed at both ends: it starts 29 days before the
        window end and includes both boundary dates."

        PRD 3.6: "Every activity row of that merchant whose `business_date` falls inside the window
        contributes, and rows outside it are excluded even when they are the merchant's only other
        activity"

        Design: Corner/calculations/rolling_ratio_window_excludes_the_row_thirty_days_back
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-07-05T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            requested_monthly_volume_cents=300_000_000,
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        ingest_activity(
            api,
            merchant_id,
            "2026-07-05",
            txn_count=5_000,
            volume_cents=50_000_000,
            distinct_card_count=4_800,
            chargeback_count=400,
            chargeback_amount_cents=4_000_000,
            chargeback_network="VISA",
        )
        set_clock(api, day_start("2026-07-06"))
        ingest_activity(
            api,
            merchant_id,
            "2026-07-06",
            chargeback_count=5,
            chargeback_amount_cents=10_000,
            chargeback_network="VISA",
        )
        set_clock(api, day_start("2026-08-04"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-04",
            chargeback_count=5,
            chargeback_amount_cents=10_000,
            chargeback_network="VISA",
        )

        merchant = read_merchant(api, merchant_id)
        assert merchant["metrics_as_of_date"] == "2026-08-04"
        assert merchant["trailing_30d_txn_count"] == 2_000
        assert merchant["trailing_30d_volume_cents"] == 2_000_000
        assert merchant["trailing_30d_chargeback_count"] == 10
        assert merchant["trailing_30d_chargeback_amount_cents"] == 20_000
        assert merchant["rolling_chargeback_ratio_bps"] == 50
        assert merchant["amount_based_chargeback_ratio_bps"] == 100
        assert merchant["account_state"] == "ACTIVE"

        _, meta = validate_paginated(
            api.list_day_activity(merchant_id, make_risk_analyst_headers())
        )
        assert meta["total_count"] == 3

    def test_a_day_with_no_transactions_yields_zeros_and_raises_no_alert(self):
        """Every denominator is zero, so every derived figure is exactly zero.

        PRD 3.6: "The server computes `avg_ticket_cents` as `volume_cents` divided by `txn_count`
        rounded half up when `txn_count` is greater than zero, and 0 when the day had no
        transactions, and stamps `ingested_by_user_id` with the acting analyst."

        PRD 3.6: "`rolling_chargeback_ratio_bps` is the count-based measure:
        `trailing_30d_chargeback_count` multiplied by 10000, divided by `trailing_30d_txn_count`,
        rounded half up, or exactly 0 when the trailing transaction count is 0."

        Design: Corner/calculations/zero_denominator_ratios_return_zero_and_raise_no_alert
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        set_clock(api, day_start("2026-08-05"))
        row = ingest_activity(
            api,
            onboarded.merchant_id,
            "2026-08-05",
            txn_count=0,
            volume_cents=0,
            decline_count=0,
            distinct_card_count=0,
            unique_bin_count=0,
            chargeback_count=0,
            chargeback_amount_cents=0,
        )
        assert row["avg_ticket_cents"] == 0

        alerts = run_monitoring(api, "2026-08-05")
        assert alerts == []

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["rolling_chargeback_ratio_bps"] == 0
        assert merchant["amount_based_chargeback_ratio_bps"] == 0
        assert merchant["last_monitoring_run_date"] == "2026-08-05"
        assert merchant["open_alert_count"] == 0
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["funding_state"] == "NORMAL"

    def test_the_two_ratio_variants_diverge_when_the_charged_back_ticket_differs(self):
        """Fifty basis points by count and three hundred by amount, from the same window.

        PRD 3.6: "`amount_based_chargeback_ratio_bps` is the amount-based measure:
        `trailing_30d_chargeback_amount_cents` multiplied by 10000, divided by
        `trailing_30d_volume_cents`, rounded half up, or exactly 0 when the trailing volume is 0. It
        feeds loss forecasting only."

        PRD 3.13: "The probability of default in basis points is selected from the **amount-based**
        ratio variant, and only that variant: 100 basis points when
        `amount_based_chargeback_ratio_bps` is below 65; 300 when it is 65 or more but below 90; 900
        when it is 90 or more but below 180; and 2000 when it is 180 or more."

        Design: Corner/calculations/the_two_ratio_variants_reconcile_only_at_the_average_ticket
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-04"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-04",
            chargeback_count=5,
            chargeback_amount_cents=5_000,
            chargeback_network="VISA",
        )
        batch = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)
        assert batch["reserve_hold_cents"] == 50_000
        assert batch["loss_offset_from_settlement_cents"] == 5_000
        assert batch["reserve_offset_cents"] == 0
        assert batch["net_payout_cents"] == 945_000

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-05",
            txn_count=0,
            volume_cents=0,
            decline_count=0,
            distinct_card_count=0,
            unique_bin_count=0,
            chargeback_count=0,
            chargeback_amount_cents=25_000,
        )

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["total_accrued_cents"] == 50_000
        assert account["offset_to_date_cents"] == 0
        assert account["held_balance_cents"] == 50_000

        summary = validate_success(
            api.get_risk_summary(merchant_id, make_risk_analyst_headers())
        )
        assert summary["rolling_chargeback_ratio_bps"] == 50
        assert summary["amount_based_chargeback_ratio_bps"] == 300
        assert summary["gating_ratio_band"] == "NORMAL"
        assert summary["open_alert_count"] == 0
        assert summary["unpaid_settlement_exposure_cents"] == 945_000

        forecast = create_forecast(api, "2026-08-05", "EXPECTED_LOSS")
        assert forecast["merchant_count"] == 1
        assert forecast["unpaid_exposure_cents"] == 945_000
        assert forecast["gross_expected_loss_cents"] == 113_400
        assert forecast["net_expected_loss_cents"] == 63_400
        assert forecast["total_reserve_held_cents"] == 50_000
        assert forecast["coverage_gap_cents"] == 63_400
        assert forecast["reserve_adequacy_ratio_bps"] == 4_409
        assert forecast["required_additional_reserve_cents"] == 63_400
        assert forecast["projected_adequacy_ratio_bps"] == 10_000

        merchant = read_merchant(api, merchant_id)
        assert merchant["metrics_as_of_date"] == "2026-08-05"
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["funding_state"] == "NORMAL"


class TestDetectorArithmetic:
    """The fixed denominator in the velocity baseline, and the merchants the sweep never reads."""

    def test_the_velocity_baseline_divides_by_thirty_not_by_the_rows_observed(self):
        """One prior day of a million cents makes the baseline 33333, not a million.

        PRD 3.7: "From the baseline come two averages, both of which divide by a fixed denominator
        rather than by the number of rows observed: `baseline_avg_daily_volume_cents` is the summed
        baseline `volume_cents` divided by the constant 30, rounded half up"

        PRD 3.7: "`observed_metric_bps` is the day's `volume_cents` multiplied by 10000, divided by
        `baseline_avg_daily_volume_cents`, rounded half up - the day expressed as basis points of a
        normal day. `severity_score` is the lesser of 100 and the quantity 20 plus
        `observed_metric_bps` divided by 1000 truncated down to a whole number."

        Design: Corner/calculations/velocity_baseline_divides_by_thirty_not_by_observed_rows
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, merchant_id, "2026-08-04")
        set_clock(api, day_start("2026-08-05"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-05",
            txn_count=100,
            volume_cents=100_000,
            decline_count=5,
            distinct_card_count=95,
            unique_bin_count=40,
        )

        alerts = run_monitoring(api, "2026-08-05")
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["alert_type"] == "VELOCITY_SPIKE"
        assert alert["observed_metric_bps"] == 30_000
        assert alert["severity_score"] == 50
        assert alert["state"] == "OPEN"
        assert alert["recurrence_count"] == 1

        merchant = read_merchant(api, merchant_id)
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["funding_state"] == "NORMAL"
        assert merchant["rolling_chargeback_ratio_bps"] == 0

    def test_a_terminated_merchant_is_never_evaluated_by_the_sweep(self):
        """The sweep returns one alert for the live merchant and never touches the closed one.

        PRD 3.7: "The sweep evaluates every `Merchant` whose `account_state` is `ACTIVE` or
        `RESTRICTED`, in `created_at` ascending order; `TERMINATED` merchants are never evaluated and
        never receive alerts."

        Design: Corner/calculations/terminated_merchants_are_excluded_from_every_monitoring_run
        """
        api = api_client
        closed = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Larkmead Supply LLC",
            owners=[OwnerSpec(full_name="Ola Bergman")],
        )
        live = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(
            api, closed.merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 7)
        )
        ingest_activity(
            api, live.merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 7)
        )
        terminate_merchant(api, closed.merchant_id, "SUSPECTED_LAUNDERING")

        alerts = run_monitoring(api, "2026-08-05")
        assert len(alerts) == 1
        assert alerts[0]["merchant_id"] == live.merchant_id

        skipped = read_merchant(api, closed.merchant_id)
        assert skipped["account_state"] == "TERMINATED"
        assert skipped["open_alert_count"] == 0
        assert skipped["last_monitoring_run_date"] is None
        assert skipped["rolling_chargeback_ratio_bps"] == 70

        _, meta = validate_paginated(
            api.list_monitoring_alerts(closed.merchant_id, make_risk_analyst_headers())
        )
        assert meta["total_count"] == 0


class TestSettlementAndReserveArithmetic:
    """Period membership for day lines, and a hold that has not yet matured."""

    def test_activity_outside_the_settled_period_never_contributes(self):
        """Each single-day batch counts one line and holds only its own day's percentage.

        PRD 3.9: "The batch's line items are the merchant's activity rows whose `business_date` lies
        inside the inclusive period, taken in `business_date` ascending order; `day_line_count` is
        their number. Activity outside the period never contributes, even if it has never been
        settled."

        Design: Corner/calculations/settlement_lines_outside_the_period_never_contribute
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, merchant_id, "2026-08-04")
        set_clock(api, day_start("2026-08-05"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-05",
            txn_count=2_000,
            volume_cents=2_000_000,
            distinct_card_count=1_900,
        )

        first = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)
        second = create_batch(api, merchant_id, "2026-08-05", "2026-08-05", 2_000_000)

        assert first["day_line_count"] == 1
        assert first["reserve_hold_cents"] == 50_000
        assert first["net_payout_cents"] == 950_000
        assert first["scheduled_payout_date"] == "2026-08-05"
        assert second["day_line_count"] == 1
        assert second["reserve_hold_cents"] == 100_000
        assert second["net_payout_cents"] == 1_900_000
        assert second["scheduled_payout_date"] == "2026-08-06"

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["total_accrued_cents"] == 150_000
        assert account["held_balance_cents"] == 150_000

        merchant = read_merchant(api, merchant_id)
        assert merchant["pending_payout_cents"] == 2_850_000

    def test_a_release_before_maturity_finds_no_releasable_balance(self):
        """The August hold is nowhere near the 90-day cutoff, so nothing can be released.

        PRD 3.10: "the releasable balance must be greater than 0, or the request is rejected with
        `ERR_NO_RELEASABLE_BALANCE`; and the requested `amount_cents` must be no greater than the
        releasable balance, or `ERR_RELEASE_AMOUNT_EXCEEDS_RELEASABLE`."

        Design: Corner/calculations/release_request_before_maturity_has_zero_releasable_balance
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, onboarded.merchant_id, "2026-08-04")
        create_batch(api, onboarded.merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        set_clock(api, day_start("2026-08-05"))
        account = read_reserve_account(api, onboarded.reserve_account_id)
        response = api.create_release_request(
            onboarded.reserve_account_id,
            release_request_payload(50_000, "2026-08-01", "2026-08-04", account["version"]),
            make_portfolio_controller_headers(),
        )

        validate_error(response, "ERR_NO_RELEASABLE_BALANCE", 409)

        after = read_reserve_account(api, onboarded.reserve_account_id)
        assert after["state"] == "ACCRUING"
        assert after["held_balance_cents"] == 50_000
        assert after["released_to_date_cents"] == 0
        assert after["last_release_tranche_end_date"] is None
        assert after["release_lag_days"] == 90
        assert len(list_reserve_ledger(api, onboarded.reserve_account_id)) == 1
        assert read_merchant(api, onboarded.merchant_id)["reserve_balance_cents"] == 50_000


class TestRemediationAndForecastArithmetic:
    """Thirty-day monitoring blocks, and the two exclusions the forecast applies."""

    def test_remediation_months_are_fixed_thirty_day_blocks(self):
        """Month one ends 2026-09-04 and month two starts the next day, ignoring the calendar.

        PRD 3.11: "Months are fixed 30-day blocks measured from `window_start_date`, never calendar
        months: month one starts at `window_start_date`, and in general a month starts `month_index`
        less one, multiplied by 30, days after `window_start_date` and ends 30 days times
        `month_index`, less one day, after `window_start_date`, inclusive of both ends."

        PRD 3.11: "The program **fails** when the observed ratio is 180 basis points or more, or
        when the month is non-compliant and `months_elapsed` after this month has reached
        `monitoring_month_count` plus 2 grace months without the program having passed."

        Design: Corner/calculations/remediation_months_are_fixed_thirty_day_blocks_not_calendar_months
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 9))
        run_monitoring(api, "2026-08-05")

        program = open_program(
            api,
            merchant_id,
            "2026-08-06",
            "2026-11-04",
            USER_ANALYST_01,
            target_ratio_bps=100,
            monitoring_month_count=3,
        )
        activate_program(api, program["id"], USER_COMMITTEE_01)

        set_clock(api, day_start("2026-09-04"))
        ingest_activity(
            api,
            merchant_id,
            "2026-09-04",
            chargeback_count=8,
            chargeback_amount_cents=8_000,
            chargeback_network="VISA",
        )
        first = evaluate_month(api, program["id"], 1)
        assert first["last_observed_ratio_bps"] == 80
        assert first["months_elapsed"] == 1
        assert first["consecutive_compliant_months"] == 1
        assert first["state"] == "ACTIVE"

        set_clock(api, day_start("2026-09-05"))
        ingest_activity(
            api,
            merchant_id,
            "2026-09-05",
            chargeback_count=20,
            chargeback_amount_cents=20_000,
            chargeback_network="VISA",
        )
        second = evaluate_month(api, program["id"], 2)
        assert second["last_observed_ratio_bps"] == 200
        assert second["months_elapsed"] == 2
        assert second["consecutive_compliant_months"] == 0
        assert second["state"] == "FAILED"
        assert second["network_program_tier"] == "STANDARD"

        merchant = read_merchant(api, merchant_id)
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["funding_state"] == "DELAYED"
        assert merchant["funding_hold_reason_code"] is None

    def test_the_forecast_excludes_paid_batches_and_terminated_merchants(self):
        """One live merchant, one unpaid batch, and a closed merchant's reserve left out.

        PRD 3.13: "The input set is every `Merchant` whose `account_state` is `ACTIVE` or
        `RESTRICTED`, taken in `created_at` ascending order; `TERMINATED` merchants are excluded even
        when they still hold reserve."

        PRD 3.13: "That merchant's unpaid exposure is the sum of `net_payout_cents` over its
        settlement batches whose `payout_state` is `SCHEDULED`, `DELAYED` or `HELD`; paid and
        reversed batches are excluded."

        Design: Corner/calculations/forecast_excludes_paid_batches_and_terminated_merchants
        """
        api = api_client
        live = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        closed = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Larkmead Supply LLC",
            owners=[OwnerSpec(full_name="Ola Bergman")],
        )

        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, live.merchant_id, "2026-08-04")
        paid = create_batch(api, live.merchant_id, "2026-08-04", "2026-08-04", 1_000_000)
        ingest_activity(api, closed.merchant_id, "2026-08-04")
        create_batch(api, closed.merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, live.merchant_id, "2026-08-05")
        create_batch(api, live.merchant_id, "2026-08-05", "2026-08-05", 1_000_000)
        assert pay_batch(api, paid["id"])["payout_state"] == "PAID"
        terminate_merchant(api, closed.merchant_id, "SUSPECTED_LAUNDERING")

        forecast = create_forecast(api, "2026-08-05", "EXPECTED_LOSS")

        assert forecast["method"] == "EXPECTED_LOSS"
        assert forecast["merchant_count"] == 1
        assert forecast["unpaid_exposure_cents"] == 950_000
        assert forecast["gross_expected_loss_cents"] == 5_700
        assert forecast["net_expected_loss_cents"] == 0
        assert forecast["total_reserve_held_cents"] == 100_000
        assert forecast["coverage_gap_cents"] == 0
        assert forecast["reserve_adequacy_ratio_bps"] == 175_439
        assert forecast["required_additional_reserve_cents"] == 0
        assert forecast["projected_adequacy_ratio_bps"] == 175_439

        assert read_reserve_account(api, live.reserve_account_id)["held_balance_cents"] == 100_000
        assert validate_success(
            api.get_reserve_account(closed.reserve_account_id, make_risk_analyst_headers())
        )["state"] == "CLOSED"
