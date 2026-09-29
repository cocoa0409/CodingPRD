"""Values sitting exactly on a contractual threshold, and their nearest neighbours."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import (
    certify_service_commencement_payload,
    create_relief_claim_payload,
    verify_service_period_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    BETA,
    CERTIFIER,
    LENDER,
    approve_milestone,
    list_deduction_events_for_period,
    list_reserve_rows,
    refresh_concession,
    request_milestone,
    set_clock,
    setup_concession_at_financial_close,
    setup_concession_in_construction,
    setup_concession_in_operations,
    setup_two_service_periods,
    submit_performance_report,
)


class TestCumulativeDrawnPctBoundary:
    def test_a_ratio_of_exactly_three_tenths_fires_the_construction_transition(self):
        """120,000,000 of 400,000,000 lands the rounded ratio exactly on the trigger.

        PRD: "If the concession is still in `FINANCIAL_CLOSE` and the ratio is at
        least thirty hundredths — the boundary is inclusive, so a ratio of exactly
        0.3000 fires — the concession advances `FINANCIAL_CLOSE → CONSTRUCTION` in the
        same request."

        Design: Difficulty/boundary_precision_check/cumulative_drawn_pct_boundary_on_disburse
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 at the boundary", 120000000)
        approve_milestone(ctx, milestone["id"], 120000000)

        disbursed = validate_success(
            api_client.disburse_drawdown_milestone(milestone["id"], LENDER)
        )

        assert disbursed["status"] == "DISBURSED"
        concession = refresh_concession(ctx)
        assert concession["cumulative_drawn_pct"] == 0.3
        assert concession["status"] == "CONSTRUCTION"
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 8000000
        assert rows[0]["resulting_balance_cents"] == 8000000
        assert concession["lifecycle_reserve_balance_cents"] == 8000000

    def test_a_ratio_that_rounds_to_two_nine_nine_eight_does_not_fire(self):
        """119,900,000 of 400,000,000 rounds to 0.2998 and leaves the state alone.

        PRD: "The comparison is made against the four-decimal-place rounded ratio,
        not the raw quotient, so a drawn total whose raw ratio is 0.29995 rounds to
        0.3000 and does fire, while one whose raw ratio is 0.29975 rounds to 0.2998
        and does not."

        Design: Difficulty/boundary_precision_check/cumulative_drawn_pct_boundary_on_disburse
        """
        ctx = setup_concession_at_financial_close(
            legal_name="Kestrel Highways Projectco", project_name="B12 Availability Scheme"
        )
        milestone = request_milestone(ctx, "M1 just below the boundary", 119900000)
        approve_milestone(ctx, milestone["id"], 119900000)

        disbursed = validate_success(
            api_client.disburse_drawdown_milestone(milestone["id"], LENDER)
        )

        assert disbursed["status"] == "DISBURSED"
        concession = refresh_concession(ctx)
        assert concession["cumulative_drawn_pct"] == 0.2998
        assert concession["status"] == "FINANCIAL_CLOSE"
        assert concession["equity_drawn_cents"] == 100000000
        assert concession["senior_debt_drawn_cents"] == 19900000
        assert concession["lifecycle_reserve_balance_cents"] == 0
        _, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 0


class TestSelfReportVarianceTolerance:
    def test_a_variance_of_exactly_five_hundredths_is_within_tolerance(self):
        """A verified 336 points against a reported 320 is exactly 0.0500.

        PRD: "If `variance_pct` is greater than five hundredths — a variance of
        exactly 0.0500 is within tolerance and triggers nothing — the system raises a
        deduction event of its own against the period."

        Design: Difficulty/boundary_precision_check/self_report_variance_tolerance_boundary_on_verify
        """
        ctx = setup_two_service_periods()
        first_period = ctx["service_period_one"]
        submit_performance_report(ctx, 100, 2, 4, service_period_id=first_period["id"])

        verified = validate_success(
            api_client.verify_service_period(
                first_period["id"], verify_service_period_payload(108, 2, 4), BETA
            )
        )

        assert verified["reporting_status"] == "VERIFIED"
        assert verified["availability_ratio"] == 0.9976
        assert verified["total_deduction_cents"] == 0
        assert verified["net_payment_cents"] == 8604167
        rows, meta = list_deduction_events_for_period(first_period["id"])
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_variance_just_past_the_tolerance_raises_a_system_deduction_on_the_delta(self):
        """A verified 340 against a reported 320 is 0.0625, and the uplift hits the delta.

        PRD: "The uplift is applied to the delta, never to the verified total: a
        report that under-declared twenty points yields twenty-five penalty points, not
        a fraction of the whole return."

        Design: Difficulty/boundary_precision_check/self_report_variance_tolerance_boundary_on_verify
        """
        ctx = setup_two_service_periods()
        second_period = ctx["service_period_two"]
        report = submit_performance_report(
            ctx, 100, 2, 4, service_period_id=second_period["id"]
        )

        verified = validate_success(
            api_client.verify_service_period(
                second_period["id"], verify_service_period_payload(110, 2, 4), BETA
            )
        )

        stored_report = validate_success(
            api_client.get_performance_report(report["id"], ALPHA)
        )
        assert stored_report["status"] == "VERIFIED"
        assert stored_report["variance_pct"] == 0.0625
        rows, meta = list_deduction_events_for_period(second_period["id"])
        assert meta["total_count"] == 1
        event = rows[0]
        assert event["deduction_type"] == "SELF_REPORT_UNDERSTATEMENT"
        assert event["issued_by_user_id"] == "SYSTEM"
        assert event["performance_report_id"] == report["id"]
        assert event["points"] == 25
        assert event["raw_amount_cents"] == 31250
        assert event["allowed_amount_cents"] == 31250
        assert verified["total_deduction_cents"] == 31250
        assert verified["net_payment_cents"] == 8572917
        concession = refresh_concession(ctx)
        assert concession["deduction_points_ytd"] == 25
        assert concession["availability_deduction_ytd_cents"] == 31250


class TestReliefNotificationWindowBoundary:
    def test_exactly_twenty_days_after_the_event_began_is_still_in_time(self):
        """A claim for a window opening on 1 February, notified on 21 February.

        PRD: "Notification is time-limited."

        Design: Difficulty/boundary_precision_check/relief_notification_window_boundary_on_claim_creation
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-02-21T00:00:00Z")

        response = api_client.create_relief_claim(
            ctx["concession_id"],
            create_relief_claim_payload(
                "RELIEF_EVENT", "2027-02-01", "2027-02-10", 10, 400000
            ),
            ctx["cnr_headers"],
        )

        claim = validate_success(response, 201)
        assert claim["status"] == "NOTIFIED"
        assert claim["notified_at"].startswith("2027-02-21T00:00:00")
        assert claim["granted_relief_days"] == 0

    def test_twenty_one_days_after_the_event_began_is_out_of_time(self):
        """The same shape of claim, notified one day later, is refused as late.

        PRD: "Exactly twenty days after the event began is still in time;
        twenty-one days is `ERR_RELIEF_NOTIFICATION_LATE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/relief_notification_window_boundary_on_claim_creation
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-02-21T00:00:00Z")
        validate_success(
            api_client.create_relief_claim(
                ctx["concession_id"],
                create_relief_claim_payload(
                    "RELIEF_EVENT", "2027-02-01", "2027-02-10", 10, 400000
                ),
                ctx["cnr_headers"],
            ),
            201,
        )
        set_clock("2027-04-22T00:00:00Z")

        response = api_client.create_relief_claim(
            ctx["concession_id"],
            create_relief_claim_payload(
                "RELIEF_EVENT", "2027-04-01", "2027-04-10", 10, 400000
            ),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_RELIEF_NOTIFICATION_LATE", 422)
        body = api_client.list_relief_claims(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 1


class TestLiquidatedDamagesMoneyCap:
    def test_twenty_late_days_land_exactly_on_the_liquidated_damages_cap(self):
        """20 days at 250,000 cents is 5,000,000 cents, which is the cap itself.

        PRD: "Multiply the net late days by the contractual `ld_daily_rate_cents`
        and then take the lower of that product and `ld_cap_cents`."

        Design: Difficulty/boundary_precision_check/liquidated_damages_cap_boundary_on_service_commencement
        """
        ctx = setup_concession_in_construction()
        set_clock("2027-01-22T00:00:00Z")

        response = api_client.certify_service_commencement(
            ctx["concession_id"],
            certify_service_commencement_payload("2027-01-21"),
            CERTIFIER,
        )

        concession = validate_success(response)
        assert concession["ld_accrued_cents"] == 5000000
        assert concession["status"] == "OPERATIONS"
        assert concession["monthly_unitary_charge_cents"] == 8604167

    def test_twenty_one_late_days_are_clamped_to_the_money_cap_not_the_day_count(self):
        """21 days would accrue 5,250,000 cents, so exactly the cap accrues instead.

        PRD: "The ceiling applies to the money, never to the day count: twenty-one
        net late days at the contract rate may well exceed the cap, in which case
        exactly the cap accrues, but the day count itself is not capped first."

        Design: Difficulty/boundary_precision_check/liquidated_damages_cap_boundary_on_service_commencement
        """
        ctx = setup_concession_in_construction(project_name="B12 Availability Scheme")
        set_clock("2027-01-22T00:00:00Z")

        response = api_client.certify_service_commencement(
            ctx["concession_id"],
            certify_service_commencement_payload("2027-01-22"),
            CERTIFIER,
        )

        concession = validate_success(response)
        assert concession["ld_accrued_cents"] == 5000000
        assert concession["status"] == "OPERATIONS"
        body = api_client.list_relief_claims(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 0
