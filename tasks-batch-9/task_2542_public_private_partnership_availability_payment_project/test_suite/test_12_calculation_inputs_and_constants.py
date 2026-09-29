"""Declared formulas: their weight vectors, their input sets and their constants."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import (
    create_deduction_event_payload,
    create_drawdown_milestone_payload,
    create_refinancing_event_payload,
    verify_service_period_payload,
    withdraw_deduction_event_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    BETA,
    GAMMA,
    add_relief_claim,
    add_service_period,
    approve_milestone,
    determine_relief_claim,
    disburse_milestone,
    issue_deduction_event,
    list_deduction_events_for_period,
    list_reserve_rows,
    refresh_concession,
    refresh_service_period,
    reject_milestone,
    request_milestone,
    set_clock,
    setup_concession_at_financial_close,
    setup_concession_in_operations,
    setup_pending_service_period,
    setup_self_reported_period,
    setup_verified_period,
    submit_performance_report,
    verify_period,
)


class TestVerifiedRatioAndPointWeights:
    def test_a_thirty_one_day_period_prices_one_hundred_lost_minutes_to_four_decimals(self):
        """44,640 scheduled minutes give 1 - 100/44640 = 0.9978 at four decimal places.

        PRD: "The verified minutes are recorded as `unavailable_minutes_verified`,
        and from them the period's `availability_ratio` is derived: the total
        minutes in the period are its `days_in_period` multiplied by the 1,440
        minutes in a day, and the ratio is one minus the share of those minutes
        that were unavailable, rounded half up to four decimal places."

        Design: Corner/calculations/verified_availability_ratio_and_deduction_points_from_known_inputs
        """
        ctx = setup_self_reported_period()
        report_id = ctx["performance_report"]["id"]
        assert ctx["performance_report"]["reported_points"] == 320

        period = validate_success(
            api_client.verify_service_period(
                ctx["service_period_id"], verify_service_period_payload(100, 2, 4), BETA
            )
        )

        assert period["availability_ratio"] == 0.9978
        assert period["unavailable_minutes_verified"] == 100
        assert period["days_in_period"] == 31
        # deduction_points_total sums the points of the period's deduction events,
        # and no event exists yet, so the 320 verified points do not land here.
        assert period["deduction_points_total"] == 0
        assert period["net_payment_cents"] == 8604167
        report = validate_success(api_client.get_performance_report(report_id, ALPHA))
        assert report["status"] == "VERIFIED"
        assert report["variance_pct"] == 0
        assert refresh_concession(ctx)["deduction_points_ytd"] == 0


class TestReliefCreditInputSet:
    def test_only_the_granted_compensation_event_claim_credits_the_period(self):
        """Three granted claims share one window; one of them buys money.

        PRD: "Claims of type `RELIEF_EVENT` or `CHANGE_IN_LAW` are excluded from
        this input set, as are claims still in `NOTIFIED` or already `REJECTED`."

        Design: Corner/calculations/relief_credit_counts_only_granted_compensation_event_claims
        """
        ctx = setup_pending_service_period()
        set_clock("2027-03-01T00:00:00Z")
        granted = {}
        for claim_type in ("RELIEF_EVENT", "COMPENSATION_EVENT", "CHANGE_IN_LAW"):
            claim = add_relief_claim(
                ctx, claim_type, "2027-03-01", "2027-03-04", 4, 400000
            )
            granted[claim_type] = determine_relief_claim(
                ctx,
                claim["id"],
                "GRANT",
                ALPHA,
                granted_relief_days=4,
                granted_cost_cents=400000,
            )
        set_clock("2027-04-02T00:00:00Z")
        submit_performance_report(ctx, 200, 0, 0)

        period = validate_success(
            api_client.verify_service_period(
                ctx["service_period_id"], verify_service_period_payload(200, 0, 0), BETA
            )
        )

        assert period["relief_credit_cents"] == 1110215
        assert period["total_deduction_cents"] == 0
        assert period["reporting_status"] == "VERIFIED"
        assert period["net_payment_cents"] == 8604167
        body = api_client.list_relief_claims(
            ALPHA, params={"concession_id": ctx["concession_id"], "status": "GRANTED"}
        ).json()
        assert body["meta"]["total_count"] == 3
        assert granted["RELIEF_EVENT"]["granted_relief_days"] == 4
        assert granted["CHANGE_IN_LAW"]["granted_relief_days"] == 4


class TestDrawnTotalsInputSet:
    def test_four_milestones_in_four_states_move_only_the_disbursed_one(self):
        """Approved splits are computed but undrawn, so the ratio stays at 0.2000.

        PRD: "Milestones in `REQUESTED`, `APPROVED` or `REJECTED` contribute
        nothing to any of these figures; only `DISBURSED` does."

        Design: Corner/calculations/drawn_totals_count_only_disbursed_milestones
        """
        ctx = setup_concession_at_financial_close()
        first = request_milestone(ctx, "M-A Earthworks", 80000000)
        approve_milestone(ctx, first["id"], 80000000)
        disburse_milestone(ctx, first["id"])
        refresh_concession(ctx)
        second = request_milestone(ctx, "M-B Structures", 60000000)
        approved = approve_milestone(ctx, second["id"], 60000000)
        refresh_concession(ctx)
        third = request_milestone(ctx, "M-C Landscaping", 30000000)
        rejected = reject_milestone(ctx, third["id"], "scope not yet delivered")
        refresh_concession(ctx)

        fourth = validate_success(
            api_client.create_drawdown_milestone(
                ctx["concession_id"],
                create_drawdown_milestone_payload(
                    "M-D Fit Out", 10000000, ctx["concession"]["version"]
                ),
                ctx["cnr_headers"],
            ),
            201,
        )

        assert fourth["status"] == "REQUESTED"
        assert fourth["equity_portion_cents"] is None
        assert fourth["debt_portion_cents"] is None
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 80000000
        assert concession["senior_debt_drawn_cents"] == 0
        assert concession["cumulative_drawn_pct"] == 0.2
        assert concession["status"] == "FINANCIAL_CLOSE"
        assert concession["lifecycle_reserve_balance_cents"] == 0
        assert approved["status"] == "APPROVED"
        assert approved["equity_portion_cents"] == 20000000
        assert approved["debt_portion_cents"] == 40000000
        assert rejected["status"] == "REJECTED"
        assert rejected["equity_portion_cents"] is None
        _, reserve_meta = list_reserve_rows(ctx["concession_id"])
        assert reserve_meta["total_count"] == 0


class TestDeductionPointValueConstant:
    def test_four_hundred_points_convert_at_twelve_dollars_fifty_a_point(self):
        """The 400-point event is far under the cap, so both variants read 500000.

        PRD: "Its `raw_amount_cents` is its point count multiplied by the
        contractual point value of 1,250 cents — twelve dollars fifty a point — as
        exact integer arithmetic with no rounding."

        Design: Corner/calculations/deduction_amount_uses_the_declared_cents_per_point_constant
        """
        ctx = setup_verified_period()

        event = validate_success(
            api_client.create_deduction_event(
                ctx["service_period_id"],
                create_deduction_event_payload("UNAVAILABILITY", 400),
                GAMMA,
            ),
            201,
        )

        assert event["points"] == 400
        assert event["raw_amount_cents"] == 500000
        assert event["allowed_amount_cents"] == 500000
        assert event["pro_rata_amount_cents"] == 500000
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 500000
        assert period["net_payment_cents"] == 8104167
        assert period["deduction_cap_cents"] == 1720833
        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 500000
        assert concession["deduction_points_ytd"] == 400


class TestPersistentBreachThreshold:
    def test_the_flag_is_false_at_four_hundred_and_ninety_nine_and_true_at_five_hundred(self):
        """The flag is recomputed on every append, and 500 points is inclusive.

        PRD: "The concession's `deduction_points_ytd` is the sum of `points` over
        every deduction event of every one of its periods whose status is `ISSUED`
        or `DISPUTED`, and `persistent_breach_flag` is true exactly when that total
        is at least 500 points — the boundary is inclusive, so exactly 500 points
        does set the flag while 499 does not."

        Design: Corner/calculations/persistent_breach_flag_flips_only_when_the_points_reach_five_hundred
        """
        ctx = setup_pending_service_period()
        submit_performance_report(ctx, 0, 0, 0)
        verify_period(ctx, 0, 0, 0)
        issue_deduction_event(ctx, 300, "PERFORMANCE_FAILURE")
        at_three_hundred = refresh_concession(ctx)
        issue_deduction_event(ctx, 199, "PERFORMANCE_FAILURE")
        at_four_hundred_and_ninety_nine = refresh_concession(ctx)

        event = validate_success(
            api_client.create_deduction_event(
                ctx["service_period_id"],
                create_deduction_event_payload("PERFORMANCE_FAILURE", 1),
                GAMMA,
            ),
            201,
        )

        assert at_three_hundred["deduction_points_ytd"] == 300
        assert at_three_hundred["persistent_breach_flag"] is False
        assert at_four_hundred_and_ninety_nine["deduction_points_ytd"] == 499
        assert at_four_hundred_and_ninety_nine["persistent_breach_flag"] is False
        concession = refresh_concession(ctx)
        assert concession["deduction_points_ytd"] == 500
        assert concession["persistent_breach_flag"] is True
        assert concession["availability_deduction_ytd_cents"] == 625000
        assert event["points"] == 1
        assert event["raw_amount_cents"] == 1250
        assert event["allowed_amount_cents"] == 1250
        assert event["sequence_no"] == 3
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 625000
        assert period["net_payment_cents"] == 7979167
        assert period["deduction_points_total"] == 500
        assert period["availability_ratio"] == 1.0


class TestAnnualDeductionCapBoundary:
    def test_landing_exactly_on_the_annual_cap_is_allowed_and_one_point_more_is_not(self):
        """Two periods reach 10,000,000 of deductions; the next point is refused.

        PRD: "The comparison is strict: if the projection is greater than the
        annual cap the write is refused with `ERR_ANNUAL_DEDUCTION_CAP_EXCEEDED`
        (HTTP 422), and landing exactly on the cap is permitted."

        Design: Corner/calculations/annual_deduction_cap_admits_the_exact_cap_and_rejects_one_point_more
        """
        ctx = setup_concession_in_operations(deduction_cap_pct=1.0)
        first = add_service_period(ctx, 1, "2027-03-01", "2027-04-01")
        second = add_service_period(ctx, 2, "2027-04-01", "2027-05-01")
        set_clock("2027-05-02T00:00:00Z")
        for period in (first, second):
            submit_performance_report(ctx, 0, 0, 0, service_period_id=period["id"])
            verify_period(ctx, 0, 0, 0, service_period_id=period["id"])
        big = issue_deduction_event(ctx, 6000, "UNAVAILABILITY", service_period_id=first["id"])
        issue_deduction_event(ctx, 2000, "UNAVAILABILITY", service_period_id=second["id"])
        at_the_cap = refresh_concession(ctx)

        response = api_client.create_deduction_event(
            second["id"], create_deduction_event_payload("PERFORMANCE_FAILURE", 1), GAMMA
        )

        validate_error(response, "ERR_ANNUAL_DEDUCTION_CAP_EXCEEDED", 422)
        assert big["allowed_amount_cents"] == 7500000
        assert at_the_cap["availability_deduction_ytd_cents"] == 10000000
        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 10000000
        assert concession["deduction_points_ytd"] == 8000
        assert concession["persistent_breach_flag"] is True
        period_two = validate_success(api_client.get_service_period(second["id"], ALPHA))
        assert period_two["total_deduction_cents"] == 2500000
        assert period_two["net_payment_cents"] == 6104167
        period_one = validate_success(api_client.get_service_period(first["id"], ALPHA))
        assert period_one["total_deduction_cents"] == 7500000
        assert period_one["net_payment_cents"] == 1104167
        _, event_meta = list_deduction_events_for_period(second["id"])
        assert event_meta["total_count"] == 1


class TestRefinancingTierBoundary:
    def test_one_cent_over_the_first_ceiling_reprices_the_whole_gain_at_fifty_per_cent(self):
        """A gain of 50000001 pays 25000001 where 50000000 pays only 15000000.

        PRD: "The tiering is **average-rate, not marginal**: exactly one rate is
        selected by the band the whole gain falls into, and that single rate is then
        applied to the *entire* gain rather than slicing the gain across bands."

        Design: Corner/calculations/one_cent_of_extra_gain_reprices_the_entire_refinancing_share
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-02-01T00:00:00Z")
        on_the_ceiling = validate_success(
            api_client.create_refinancing_event(
                ctx["concession_id"],
                create_refinancing_event_payload(
                    "2027-02-01", 250000000, 199000000, 1000000
                ),
                ctx["cnr_headers"],
            ),
            201,
        )

        over_the_ceiling = validate_success(
            api_client.create_refinancing_event(
                ctx["concession_id"],
                create_refinancing_event_payload(
                    "2027-02-01", 250000001, 199000000, 1000000
                ),
                ctx["cnr_headers"],
            ),
            201,
        )

        assert on_the_ceiling["gross_gain_cents"] == 50000000
        assert on_the_ceiling["tier_pct_applied"] == 0.3
        assert on_the_ceiling["authority_share_cents"] == 15000000
        assert on_the_ceiling["concessionaire_share_cents"] == 35000000
        assert over_the_ceiling["gross_gain_cents"] == 50000001
        assert over_the_ceiling["tier_pct_applied"] == 0.5
        assert over_the_ceiling["authority_share_cents"] == 25000001
        assert over_the_ceiling["concessionaire_share_cents"] == 25000000
        assert (
            over_the_ceiling["authority_share_cents"]
            + over_the_ceiling["concessionaire_share_cents"]
            == 50000001
        )
        assert over_the_ceiling["status"] == "PROPOSED"
        # The sweep is sized and appended at consent, so a PROPOSED row carries 0.
        assert over_the_ceiling["reserve_sweep_cents"] == 0
        assert refresh_concession(ctx)["lifecycle_reserve_balance_cents"] == 8000000
        unchanged = validate_success(
            api_client.get_refinancing_event(on_the_ceiling["id"], ALPHA)
        )
        assert unchanged["gross_gain_cents"] == 50000000
        assert unchanged["tier_pct_applied"] == 0.3


class TestReliefWindowClipping:
    def test_a_straddling_window_credits_only_the_days_inside_the_half_open_period(self):
        """Eight granted days overlap the period by four, so 1110215 is credited.

        PRD: "For each granted compensation-event claim of the concession, take the
        distinct calendar days that lie both inside the claim's closed window and
        inside the period's half-open interval — days on or after `period_start` and
        strictly before `period_end`."

        Design: Corner/calculations/a_relief_window_is_clipped_to_the_half_open_period_before_it_is_credited
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-02-25T00:00:00Z")
        claim = add_relief_claim(
            ctx, "COMPENSATION_EVENT", "2027-02-25", "2027-03-04", 8, 500000
        )
        determined = determine_relief_claim(
            ctx,
            claim["id"],
            "GRANT",
            ALPHA,
            granted_relief_days=8,
            granted_cost_cents=500000,
        )
        add_service_period(ctx, 1, "2027-03-01", "2027-04-01")
        set_clock("2027-04-02T00:00:00Z")
        submit_performance_report(ctx, 0, 0, 0)

        period = validate_success(
            api_client.verify_service_period(
                ctx["service_period_id"], verify_service_period_payload(0, 0, 0), BETA
            )
        )

        assert determined["status"] == "GRANTED"
        assert determined["granted_relief_days"] == 8
        assert period["days_in_period"] == 31
        assert period["relief_credit_cents"] == 1110215
        assert period["total_deduction_cents"] == 0
        assert period["net_payment_cents"] == 8604167
        assert period["reporting_status"] == "VERIFIED"
        assert period["payment_status"] == "UNBILLED"


class TestWithdrawalReplaysTheSurvivors:
    def test_withdrawing_the_middle_event_re_derives_the_total_from_the_survivors(self):
        """The withdrawn row leaves the input set and its sequence gap remains.

        PRD: "The period's deduction position is then recomputed from scratch, and
        the input set for that recomputation is precise: the period's events whose
        status is `ISSUED` or `DISPUTED`, taken in ascending `sequence_no`."

        Design: Corner/calculations/withdrawing_the_middle_event_replays_the_remaining_two_in_sequence_order
        """
        ctx = setup_verified_period()
        first = issue_deduction_event(ctx, 400, "UNAVAILABILITY")
        middle = issue_deduction_event(ctx, 300, "PERFORMANCE_FAILURE")
        last = issue_deduction_event(ctx, 200, "UNAVAILABILITY")
        before = refresh_service_period(ctx)

        withdrawn = validate_success(
            api_client.withdraw_deduction_event(
                middle["id"],
                withdraw_deduction_event_payload(
                    "duplicate of the category B entry already counted in event 1"
                ),
                GAMMA,
            )
        )

        assert (first["sequence_no"], middle["sequence_no"], last["sequence_no"]) == (1, 2, 3)
        assert before["total_deduction_cents"] == 1125000
        assert before["net_payment_cents"] == 7479167
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["points"] == 300
        assert withdrawn["raw_amount_cents"] == 375000
        assert withdrawn["allowed_amount_cents"] == 0
        assert withdrawn["pro_rata_amount_cents"] == 0
        assert withdrawn["sequence_no"] == 2
        survivor_one = validate_success(api_client.get_deduction_event(first["id"], ALPHA))
        survivor_three = validate_success(api_client.get_deduction_event(last["id"], ALPHA))
        assert survivor_one["allowed_amount_cents"] == 500000
        assert survivor_three["allowed_amount_cents"] == 250000
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 750000
        assert period["net_payment_cents"] == 7854167
        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 750000
        assert concession["deduction_points_ytd"] == 600
        assert concession["persistent_breach_flag"] is True
        _, issued_meta = list_deduction_events_for_period(
            ctx["service_period_id"], status="ISSUED"
        )
        assert issued_meta["total_count"] == 2
