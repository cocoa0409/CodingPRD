"""Stale parent views, the cascades that fan out across collections, and same-request visibility."""
from test_helpers import (
    OFFICER_ALPHA,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    consent_refinancing_payload,
    create_drawdown_milestone_payload,
    create_performance_report_payload,
    settle_enforcement_action_payload,
    verify_service_period_payload,
    withdraw_deduction_event_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    BETA,
    GAMMA,
    add_reserve_transaction,
    add_service_period,
    approve_milestone,
    calculate_compensation,
    disburse_milestone,
    invoice_period,
    issue_deduction_event,
    list_deduction_events_for_period,
    list_reserve_rows,
    pay_period,
    propose_refinancing,
    raise_enforcement_action,
    refresh_concession,
    refresh_service_period,
    request_milestone,
    set_clock,
    setup_concession_at_financial_close,
    setup_concession_in_operations,
    setup_pending_service_period,
    setup_verified_period,
    submit_performance_report,
    verify_period,
)


class TestAStalePeriodViewCannotSupersedeAReport:
    def test_the_second_return_must_carry_the_version_the_first_one_produced(self):
        """Resubmission is a legal self-loop, which is exactly why it is version-guarded.

        PRD: "Creating a performance report against a service period requires
        `expected_service_period_version` to equal that period's current `version`, and
        a mismatch is rejected with `ERR_STALE_SERVICE_PERIOD_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_stale_period_view_cannot_supersede_a_report
        """
        ctx = setup_pending_service_period()
        original_version = refresh_service_period(ctx)["version"]
        first = submit_performance_report(ctx, 100, 2, 4, original_version)
        after_first = refresh_service_period(ctx)["version"]

        refused = api_client.create_performance_report(
            ctx["service_period_id"],
            create_performance_report_payload(40, 1, 1, original_version),
            ctx["cnr_headers"],
        )

        validate_error(refused, "ERR_STALE_SERVICE_PERIOD_VERSION", 412)
        assert original_version == 1
        assert after_first == 2
        held = validate_success(api_client.get_performance_report(first["id"], ALPHA))
        assert held["status"] == "SUBMITTED"
        assert held["reported_points"] == 320
        listing = api_client.list_performance_reports(
            ALPHA, params={"service_period_id": ctx["service_period_id"]}
        ).json()
        assert listing["meta"]["total_count"] == 1
        assert refresh_service_period(ctx)["version"] == 2

        second = validate_success(
            api_client.create_performance_report(
                ctx["service_period_id"],
                create_performance_report_payload(40, 1, 1, after_first),
                ctx["cnr_headers"],
            ),
            201,
        )

        assert second["status"] == "SUBMITTED"
        assert second["reported_points"] == 130
        superseded = validate_success(
            api_client.get_performance_report(first["id"], ALPHA)
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["reported_points"] == 320
        period = refresh_service_period(ctx)
        assert period["reporting_status"] == "SELF_REPORTED"
        assert period["version"] == 3


class TestAPreDisbursementViewCannotRequestTheNextDrawdown:
    def test_one_increment_per_mutating_request_and_none_for_the_approval(self):
        """The four-link disbursement cascade counts once; certification counts not at all.

        PRD: "Creating a drawdown milestone under a concession requires
        `expected_concession_version` to equal that concession's current `version`."

        PRD: "Ten of the eleven resource types additionally carry `updated_at`, an ISO
        8601 UTC timestamp refreshed from the logical clock on every mutation, and
        `version`, an integer that starts at 1 and increases by exactly 1 on every
        successful mutation of the row."

        Design: Corner/cross_cutting_complexity_layers/a_pre_disbursement_view_cannot_request_the_next_drawdown
        """
        ctx = setup_concession_at_financial_close()
        after_close = refresh_concession(ctx)["version"]
        first = request_milestone(ctx, "M1 Foundations Complete", 120000000)
        after_create = refresh_concession(ctx)["version"]
        approve_milestone(ctx, first["id"], 120000000)
        after_approve = refresh_concession(ctx)["version"]
        disburse_milestone(ctx, first["id"])
        after_disburse = refresh_concession(ctx)["version"]

        refused = api_client.create_drawdown_milestone(
            ctx["concession_id"],
            create_drawdown_milestone_payload(
                "M2 Structures Complete", 80000000, after_create
            ),
            ctx["cnr_headers"],
        )

        validate_error(refused, "ERR_STALE_CONCESSION_VERSION", 412)
        assert after_close == 2
        assert after_create == 3
        assert after_approve == 3
        assert after_disburse == 4
        listing = api_client.list_drawdown_milestones(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert listing["meta"]["total_count"] == 1
        assert refresh_concession(ctx)["version"] == 4

        second = validate_success(
            api_client.create_drawdown_milestone(
                ctx["concession_id"],
                create_drawdown_milestone_payload(
                    "M2 Structures Complete", 80000000, after_disburse
                ),
                ctx["cnr_headers"],
            ),
            201,
        )

        assert second["status"] == "REQUESTED"
        assert second["requested_amount_cents"] == 80000000
        concession = refresh_concession(ctx)
        assert concession["version"] == 5
        assert concession["equity_drawn_cents"] == 100000000
        assert concession["senior_debt_drawn_cents"] == 20000000


class TestConsentOnAViewThatPredatesAContribution:
    def test_a_routine_contribution_invalidates_the_officers_view_of_the_parent(self):
        """The stale parent is not even named in the consent path, and the gain is frozen.

        PRD: "Consenting to or refusing a proposed refinancing likewise requires
        `expected_concession_version` to equal the concession's current `version`, and
        a mismatch is rejected with `ERR_STALE_CONCESSION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/consent_on_a_view_that_predates_a_reserve_contribution_is_rejected
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-03-01T00:00:00Z")
        proposal = propose_refinancing(
            ctx, "2027-03-01", 300000000, 240000000, 10000000, ctx["cnr_headers"]
        )
        stale_version = refresh_concession(ctx)["version"]
        contribution = add_reserve_transaction(
            ctx, "CONTRIBUTION", 2000000, "quarterly lifecycle funding"
        )
        fresh_version = refresh_concession(ctx)["version"]

        refused = api_client.consent_refinancing_event(
            proposal["id"], consent_refinancing_payload("CONSENT", stale_version), BETA
        )

        validate_error(refused, "ERR_STALE_CONCESSION_VERSION", 412)
        assert fresh_version == stale_version + 1
        mid = validate_success(api_client.get_refinancing_event(proposal["id"], ALPHA))
        assert mid["status"] == "PROPOSED"
        assert mid["reserve_sweep_cents"] == 0
        assert mid["consented_at"] is None
        concession_mid = refresh_concession(ctx)
        assert concession_mid["lifecycle_reserve_balance_cents"] == 10000000
        assert concession_mid["version"] == fresh_version
        assert contribution["sequence_no"] == 2
        assert contribution["resulting_balance_cents"] == 10000000

        consented = validate_success(
            api_client.consent_refinancing_event(
                proposal["id"], consent_refinancing_payload("CONSENT", fresh_version), BETA
            )
        )

        assert consented["status"] == "CONSENTED"
        assert consented["gross_gain_cents"] == 50000000
        assert consented["concessionaire_share_cents"] == 35000000
        assert consented["reserve_sweep_cents"] == 8750000
        concession = refresh_concession(ctx)
        assert concession["lifecycle_reserve_balance_cents"] == 18750000
        assert concession["version"] == fresh_version + 1
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 3
        assert rows[-1]["sequence_no"] == 3
        assert rows[-1]["amount_cents"] == 8750000
        assert rows[-1]["resulting_balance_cents"] == 18750000


class TestSettlementSweepsOnePaymentStateOnly:
    def test_the_invoiced_period_is_adjusted_and_the_paid_period_is_left_alone(self):
        """The unpaid-invoice term is read before the cascade converts the row it came from.

        PRD: "It then moves `COMPENSATION_CALCULATED → SETTLED` and fires the widest
        cascade in the system, in three links: the concession moves from `OPERATIONS`
        or `STEP_IN` to `TERMINATED`; **every** service period of that concession whose
        payment axis sits at `INVOICED` moves `INVOICED → ADJUSTED`, with its
        `net_payment_cents` frozen at whatever it then held, because those invoices will
        now be dealt with inside the compensation sum rather than paid in the ordinary
        course; and the sponsor vehicle moves to `WOUND_UP`."

        Design: Corner/cross_cutting_complexity_layers/settlement_adjusts_the_invoiced_period_and_leaves_the_paid_one_alone
        """
        ctx = setup_concession_in_operations()
        first = add_service_period(ctx, 1, "2027-03-01", "2027-04-01")
        second = add_service_period(ctx, 2, "2027-04-01", "2027-05-01")
        set_clock("2027-04-02T00:00:00Z")
        submit_performance_report(ctx, 100, 2, 4, service_period_id=first["id"])
        verify_period(ctx, 100, 2, 4, service_period_id=first["id"])
        invoice_period(ctx, service_period_id=first["id"])
        pay_period(ctx, "PAY-2027-03", service_period_id=first["id"])
        set_clock("2027-05-02T00:00:00Z")
        submit_performance_report(ctx, 0, 0, 0, service_period_id=second["id"])
        verify_period(ctx, 0, 0, 0, service_period_id=second["id"])
        invoice_period(ctx, service_period_id=second["id"])
        set_clock("2028-01-21T00:00:00Z")
        action = raise_enforcement_action(
            ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2028-01-21", ALPHA
        )
        calculated = calculate_compensation(
            ctx, action["id"], "2028-01-21", 180000000, ALPHA
        )

        settled = validate_success(
            api_client.settle_enforcement_action(
                action["id"], settle_enforcement_action_payload("SETTLE-2028-0002"), GAMMA
            )
        )

        assert calculated["compensation_cents"] == 300604167
        assert calculated["unpaid_invoiced_cents"] == 8604167
        assert settled["status"] == "SETTLED"
        assert settled["settlement_reference"] == "SETTLE-2028-0002"
        assert settled["compensation_cents"] == 300604167
        assert refresh_concession(ctx)["status"] == "TERMINATED"
        period_two = validate_success(api_client.get_service_period(second["id"], ALPHA))
        assert period_two["payment_status"] == "ADJUSTED"
        assert period_two["net_payment_cents"] == 8604167
        assert period_two["reporting_status"] == "VERIFIED"
        period_one = validate_success(api_client.get_service_period(first["id"], ALPHA))
        assert period_one["payment_status"] == "PAID"
        assert period_one["payment_reference"] == "PAY-2027-03"
        assert period_one["reporting_status"] == "VERIFIED"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "WOUND_UP"
        listing = api_client.list_service_periods(
            ALPHA,
            params={
                "concession_id": ctx["concession_id"],
                "payment_status": "ADJUSTED",
            },
        ).json()
        assert listing["meta"]["total_count"] == 1
        assert listing["data"][0]["id"] == second["id"]


class TestWithdrawalClearsThePersistentBreachFlag:
    def test_the_flag_is_recomputed_downward_rather_than_latched(self):
        """500 points set the flag; dropping back to 300 must clear it again.

        PRD: "The concession's `deduction_points_ytd` is the sum of `points` over every
        deduction event of every one of its periods whose status is `ISSUED` or
        `DISPUTED`, and `persistent_breach_flag` is true exactly when that total is at
        least 500 points — the boundary is inclusive, so exactly 500 points does set the
        flag while 499 does not."

        Design: Corner/cross_cutting_complexity_layers/withdrawing_an_event_clears_the_persistent_breach_flag
        """
        ctx = setup_verified_period()
        kept = issue_deduction_event(ctx, 300, "PERFORMANCE_FAILURE")
        dropped = issue_deduction_event(ctx, 200, "UNAVAILABILITY")
        before = validate_success(
            api_client.get_payment_summary(ctx["concession_id"], ALPHA)
        )
        assert before["deduction_points_ytd"] == 500
        assert before["persistent_breach_flag"] is True

        withdrawn = validate_success(
            api_client.withdraw_deduction_event(
                dropped["id"],
                withdraw_deduction_event_payload(
                    "Category B failures were double counted."
                ),
                GAMMA,
            )
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["allowed_amount_cents"] == 0
        assert withdrawn["pro_rata_amount_cents"] == 0
        assert withdrawn["points"] == 200
        assert withdrawn["raw_amount_cents"] == 250000
        survivor = validate_success(api_client.get_deduction_event(kept["id"], ALPHA))
        assert survivor["status"] == "ISSUED"
        assert survivor["allowed_amount_cents"] == 375000
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 375000
        assert period["net_payment_cents"] == 8229167
        concession = refresh_concession(ctx)
        assert concession["persistent_breach_flag"] is False
        assert concession["availability_deduction_ytd_cents"] == 375000
        after = validate_success(
            api_client.get_payment_summary(ctx["concession_id"], ALPHA)
        )
        assert after["deduction_points_ytd"] == 300
        assert after["persistent_breach_flag"] is False


class TestVerificationReturnsMoneyFromARowItJustCreated:
    def test_the_understatement_charge_is_already_inside_the_200_body(self):
        """The response must reflect a deduction event the caller has not yet seen.

        PRD: "Verification then settles the period's money, and the order of the three
        steps is contractual: the period's deduction allocation is recomputed first —
        both variants of it — then the relief credit, and only then the net payment."

        PRD: "Its `deduction_type` is `SELF_REPORT_UNDERSTATEMENT`, its
        `issued_by_user_id` is the literal string `SYSTEM`, its `performance_report_id`
        points at the report that understated, and its `points` are the point *delta* —
        verified total less reported total — multiplied by one plus a twenty-five per
        cent uplift, rounded half up to a whole point."

        Design: Corner/consistency_model/verification_returns_money_that_depends_on_a_row_it_just_created
        """
        ctx = setup_pending_service_period()
        report = submit_performance_report(ctx, 40, 1, 1)

        body = validate_success(
            api_client.verify_service_period(
                ctx["service_period_id"], verify_service_period_payload(100, 2, 4), BETA
            )
        )

        assert body["reporting_status"] == "VERIFIED"
        assert body["payment_status"] == "UNBILLED"
        assert body["unavailable_minutes_verified"] == 100
        assert body["availability_ratio"] == 0.9978
        assert body["total_deduction_cents"] == 297500
        assert body["relief_credit_cents"] == 0
        assert body["net_payment_cents"] == 8306667
        # deduction_points_total sums the points of the period's live events, which is
        # the single understatement event the verification just raised.
        assert body["deduction_points_total"] == 238
        reread = refresh_service_period(ctx)
        assert reread["total_deduction_cents"] == body["total_deduction_cents"]
        assert reread["net_payment_cents"] == body["net_payment_cents"]
        verified_report = validate_success(
            api_client.get_performance_report(report["id"], ALPHA)
        )
        assert verified_report["status"] == "VERIFIED"
        assert verified_report["reported_points"] == 130
        assert verified_report["variance_pct"] == 1.4615
        rows, meta = list_deduction_events_for_period(ctx["service_period_id"])
        assert meta["total_count"] == 1
        assert rows[0]["deduction_type"] == "SELF_REPORT_UNDERSTATEMENT"
        assert rows[0]["issued_by_user_id"] == "SYSTEM"
        assert rows[0]["performance_report_id"] == report["id"]
        assert rows[0]["points"] == 238
        assert rows[0]["raw_amount_cents"] == 297500
        assert rows[0]["allowed_amount_cents"] == 297500
        assert rows[0]["status"] == "ISSUED"
        assert rows[0]["issued_by_user_id"] != OFFICER_ALPHA
        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 297500
        assert concession["deduction_points_ytd"] == 238
        assert concession["persistent_breach_flag"] is False
        summary = validate_success(
            api_client.get_payment_summary(ctx["concession_id"], ALPHA)
        )
        assert summary["availability_deduction_ytd_cents"] == 297500
