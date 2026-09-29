"""The endpoints that are not plain creates: the derived read, the amendment and the links."""
from test_helpers import OFFICER_GAMMA, api_client, validate_error, validate_success
from test_helpers.factories import (
    amend_concession_payload,
    calculate_compensation_payload,
    create_deduction_event_payload,
    handback_survey_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    CERTIFIER,
    GAMMA,
    LENDER,
    issue_deduction_event,
    refresh_concession,
    refresh_service_period,
    set_clock,
    setup_concession_at_financial_close,
    setup_drafted_concession,
    setup_notified_termination,
    setup_verified_period,
)


class TestPaymentSummaryPublishesBothAllocationVariants:
    def test_the_two_variants_agree_in_total_and_differ_event_by_event(self):
        """Raws of 500000, 750000 and 625000 overflow a 1720833 cap in two different shapes.

        PRD: "Publishing the two totals side by side is the whole point of computing
        both allocation variants: they sum to the same capped figure while
        attributing it differently across events."

        Design: Corner/endpoints/the_payment_summary_publishes_both_cap_variants_side_by_side
        """
        ctx = setup_verified_period()
        first = issue_deduction_event(ctx, 400, "UNAVAILABILITY")
        second = issue_deduction_event(ctx, 600, "UNAVAILABILITY")
        third = issue_deduction_event(ctx, 500, "PERFORMANCE_FAILURE")

        summary = validate_success(
            api_client.get_payment_summary(ctx["concession_id"], LENDER)
        )

        assert summary["monthly_unitary_charge_cents"] == 8604167
        assert summary["annual_cap_cents"] == 10000000
        assert summary["availability_deduction_ytd_cents"] == 1720833
        assert summary["sequential_total_cents"] == 1720833
        assert summary["pro_rata_total_cents"] == 1720833
        assert summary["deduction_points_ytd"] == 1500
        assert summary["persistent_breach_flag"] is True
        assert summary["lifecycle_reserve_balance_cents"] == 8000000
        assert summary["unpaid_invoiced_cents"] == 0
        assert "id" not in summary
        one = validate_success(api_client.get_deduction_event(first["id"], ALPHA))
        two = validate_success(api_client.get_deduction_event(second["id"], ALPHA))
        three = validate_success(api_client.get_deduction_event(third["id"], ALPHA))
        assert (one["allowed_amount_cents"], one["pro_rata_amount_cents"]) == (
            500000,
            458888,
        )
        assert (two["allowed_amount_cents"], two["pro_rata_amount_cents"]) == (
            750000,
            688334,
        )
        assert (three["allowed_amount_cents"], three["pro_rata_amount_cents"]) == (
            470833,
            573611,
        )
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 1720833
        assert period["net_payment_cents"] == 6883334


class TestAmendingADraftedConcession:
    def test_a_partial_amendment_bumps_the_version_and_mints_no_charge(self):
        """Two parameters are rewritten, the other commercial terms and the charge are not.

        PRD: "Amending does not derive a monthly charge —
        `monthly_unitary_charge_cents` stays null and is derived at financial close
        from whatever the amended values then are."

        Design: Corner/endpoints/amending_a_drafted_concession_leaves_the_charge_undecided
        """
        ctx = setup_drafted_concession()
        assert ctx["concession"]["version"] == 1
        set_clock("2026-09-05T00:00:00Z")

        amended = validate_success(
            api_client.amend_concession(
                ctx["concession_id"],
                amend_concession_payload(masp_cents=120000000, deduction_cap_pct=0.25),
                ALPHA,
            )
        )

        assert amended["masp_cents"] == 120000000
        assert amended["deduction_cap_pct"] == 0.25
        assert amended["indexation_pct"] == 0.0325
        assert amended["ld_cap_cents"] == 5000000
        assert amended["ld_daily_rate_cents"] == 250000
        assert amended["monthly_unitary_charge_cents"] is None
        assert amended["status"] == "DRAFTED"
        assert amended["financial_close_date"] is None
        assert amended["version"] == 2
        assert amended["updated_at"].startswith("2026-09-05T00:00:00")
        assert amended["created_at"].startswith("2026-09-01T00:00:00")


class TestHandbackSurveyIsAdmittedFromOperationsOnly:
    def test_a_survey_at_financial_close_leaves_every_handback_field_null(self):
        """The certifier and the body are both correct; only the concession state is not.

        PRD: "The survey requires the concession to be in `OPERATIONS`, otherwise
        `ERR_CONCESSION_STATE_FORBIDS_OPERATION` (HTTP 409), and it is frozen by a
        live enforcement action with `ERR_CONCESSION_UNDER_ENFORCEMENT` (HTTP 409)."

        Design: Corner/endpoints/a_handback_survey_before_operations_is_refused
        """
        ctx = setup_concession_at_financial_close()

        response = api_client.handback_survey(
            ctx["concession_id"],
            handback_survey_payload("2026-09-20", 12000000),
            CERTIFIER,
        )

        validate_error(response, "ERR_CONCESSION_STATE_FORBIDS_OPERATION", 409)
        concession = refresh_concession(ctx)
        assert concession["handback_status"] == "NOT_SURVEYED"
        assert concession["handback_survey_date"] is None
        assert concession["handback_rectification_cost_cents"] is None
        assert concession["handback_required_reserve_cents"] is None
        assert concession["handback_shortfall_cents"] is None
        assert concession["status"] == "FINANCIAL_CLOSE"


class TestConditionallyMandatoryCompensationInputs:
    def test_a_default_calculation_missing_two_of_its_three_inputs_is_a_schema_refusal(self):
        """The market-value variant cannot default its inputs to zero.

        PRD: "Schema conformance covers every create and amend operation and yields
        `ERR_INVALID_REQUEST` (HTTP 400): a required field absent, an enumeration
        value outside its declared set, an amount field that is not a non-negative
        integer, a percentage field outside the range 0 to 1 inclusive, a
        basis-point field that is not a non-negative integer, a malformed ISO 8601
        date, a reversal attempted through the plain ledger-append operation, or a
        compensation calculation on concessionaire default that omits any of its
        three market-value inputs."

        Design: Corner/endpoints/the_default_variant_refuses_to_cost_without_its_market_value_inputs
        """
        ctx = setup_notified_termination(
            trigger_reason="CONCESSIONAIRE_DEFAULT", effective_date="2027-04-05"
        )
        action_id = ctx["enforcement_action"]["id"]
        set_clock("2028-01-21T00:00:00Z")

        response = api_client.calculate_compensation(
            action_id,
            calculate_compensation_payload(
                "2028-01-21", 180000000, market_value_estimate_cents=210000000
            ),
            ALPHA,
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        action = validate_success(api_client.get_enforcement_action(action_id, ALPHA))
        assert action["status"] == "NOTIFIED"
        assert action["compensation_cents"] is None
        assert action["calculated_by_user_id"] is None
        assert action["market_value_estimate_cents"] is None
        assert action["termination_date"] is None
        assert refresh_concession(ctx)["status"] == "OPERATIONS"


class TestAnEventMayCiteItsOwnPeriodsReport:
    def test_citing_the_periods_own_report_stores_the_link_and_leaves_the_money_alone(self):
        """400 points cost 500000 whether or not the evidencing return is named.

        PRD: "Deduction events accept `service_period_id`, `performance_report_id`,
        `deduction_type` and `status`, and that list is the only way to reach the
        self-report-understatement and handback-shortfall events the cascades raise."

        Design: Corner/endpoints/an_event_may_cite_its_own_periods_report
        """
        ctx = setup_verified_period()
        report_id = ctx["performance_report"]["id"]

        event = validate_success(
            api_client.create_deduction_event(
                ctx["service_period_id"],
                create_deduction_event_payload(
                    "UNAVAILABILITY", 400, performance_report_id=report_id
                ),
                GAMMA,
            ),
            201,
        )

        assert event["performance_report_id"] == report_id
        assert event["service_period_id"] == ctx["service_period_id"]
        assert event["sequence_no"] == 1
        assert event["raw_amount_cents"] == 500000
        assert event["allowed_amount_cents"] == 500000
        assert event["status"] == "ISSUED"
        assert event["issued_by_user_id"] == OFFICER_GAMMA
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 500000
        assert period["net_payment_cents"] == 8104167
        body = api_client.list_deduction_events(
            ALPHA, params={"performance_report_id": report_id}
        ).json()
        assert body["meta"]["total_count"] == 1
        assert body["data"][0]["id"] == event["id"]
