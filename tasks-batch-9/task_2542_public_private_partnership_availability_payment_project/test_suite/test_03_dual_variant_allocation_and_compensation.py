"""Two figures computed from one input set: the cap allocation shadow, and the
four termination compensation formulae selected by contractual ground."""
from test_helpers import api_client, validate_success
from test_helpers.assertions import assert_deduction_event, assert_net_payment_identity
from test_helpers.factories import (
    calculate_compensation_payload,
    create_deduction_event_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    GAMMA,
    issue_deduction_event,
    list_deduction_events_for_period,
    raise_enforcement_action,
    refresh_concession,
    refresh_service_period,
    set_clock,
    setup_period_at_deduction_cap,
    setup_period_with_two_deduction_events,
)


class TestCapAllocationVariantsDiverge:
    def test_the_straddling_event_is_truncated_by_the_waterfall_but_scaled_by_the_shadow(self):
        """A third deduction takes the period past its cap, and the two variants split.

        PRD: "Walk the events in ascending `sequence_no`; each event is allowed the
        lesser of its own raw amount and the headroom that remains, and the headroom
        is then reduced by what it was allowed."

        Design: Difficulty/dual_variant_calc/deduction_cap_allocation_sequential_vs_pro_rata_diverge_per_event
        """
        ctx = setup_period_with_two_deduction_events()

        response = api_client.create_deduction_event(
            ctx["service_period_id"],
            create_deduction_event_payload("PERFORMANCE_FAILURE", 500),
            GAMMA,
        )

        event = validate_success(response, 201)
        assert_deduction_event(event)
        assert event["sequence_no"] == 3
        assert event["raw_amount_cents"] == 625000
        # Raw total 1875000 against a 1720833 cap: the waterfall leaves this event
        # only the residual headroom, while the shadow scales it pro rata.
        assert event["allowed_amount_cents"] == 470833
        assert event["pro_rata_amount_cents"] == 573611
        assert event["allowed_amount_cents"] != event["pro_rata_amount_cents"]

    def test_both_variants_sum_to_the_cap_while_attributing_it_differently(self):
        """Every one of the three events is attributed differently by the two variants.

        PRD: "Unlike the waterfall, this variant truncates no event to zero and
        leaves no event at its full raw amount; on identical inputs it deliberately
        gives a different per-event answer while summing to the same total."

        Design: Difficulty/dual_variant_calc/deduction_cap_allocation_sequential_vs_pro_rata_diverge_per_event
        """
        ctx = setup_period_with_two_deduction_events()
        issue_deduction_event(ctx, 500, "PERFORMANCE_FAILURE")

        rows, meta = list_deduction_events_for_period(ctx["service_period_id"])

        assert meta["total_count"] == 3
        allowed = [row["allowed_amount_cents"] for row in rows]
        pro_rata = [row["pro_rata_amount_cents"] for row in rows]
        assert allowed == [500000, 750000, 470833]
        assert pro_rata == [458888, 688334, 573611]
        assert sum(allowed) == 1720833
        assert sum(pro_rata) == 1720833
        for row in rows:
            assert row["allowed_amount_cents"] != row["pro_rata_amount_cents"]
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 1720833
        assert period["relief_credit_cents"] == 0
        assert period["net_payment_cents"] == 6883334
        assert_net_payment_identity(period)
        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 1720833
        assert concession["deduction_points_ytd"] == 1500


class TestTerminationCompensationVariantByGround:
    def test_the_voluntary_variant_makes_the_sponsor_whole_less_the_deduction_offset(self):
        """AUTHORITY_VOLUNTARY reads debt, equity, accrued return and unpaid invoices.

        PRD: "On `AUTHORITY_VOLUNTARY` the sponsor is made whole: the outstanding
        senior debt plus `equity_drawn_cents` plus the accrued equity return plus the
        unpaid invoices, less the deduction offset."

        Design: Difficulty/dual_variant_calc/termination_compensation_variant_selected_by_trigger_reason
        """
        ctx = setup_period_at_deduction_cap()
        set_clock("2028-01-21T00:00:00Z")
        action = raise_enforcement_action(
            ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2028-01-21", ALPHA
        )

        response = api_client.calculate_compensation(
            action["id"], calculate_compensation_payload("2028-01-21", 180000000), ALPHA
        )

        calculated = validate_success(response)
        assert calculated["elapsed_operational_months"] == 12
        assert calculated["accrued_equity_return_cents"] == 12000000
        assert calculated["unpaid_invoiced_cents"] == 0
        assert calculated["deduction_offset_cents"] == 1720833
        # 180000000 + 100000000 + 12000000 + 0 - 1720833
        assert calculated["compensation_cents"] == 290279167
        assert calculated["market_value_estimate_cents"] is None
        assert calculated["status"] == "COMPENSATION_CALCULATED"
        assert refresh_concession(ctx)["status"] == "OPERATIONS"

    def test_the_concessionaire_default_variant_drops_the_make_whole_terms_entirely(self):
        """CONCESSIONAIRE_DEFAULT reads three cost inputs no other variant reads.

        PRD: "On `CONCESSIONAIRE_DEFAULT` the basis changes completely — the debt,
        equity and accrued-return terms drop out entirely and three cost terms no
        other variant reads come in: the `market_value_estimate_cents` less the
        `rectification_cost_cents` less the `authority_reprocurement_cost_cents` less
        the deduction offset."

        Design: Difficulty/dual_variant_calc/termination_compensation_variant_selected_by_trigger_reason
        """
        ctx = setup_period_at_deduction_cap()
        set_clock("2028-01-21T00:00:00Z")
        voluntary = raise_enforcement_action(
            ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2028-01-21", ALPHA
        )
        default = raise_enforcement_action(
            ctx, "TERMINATION", "CONCESSIONAIRE_DEFAULT", "2028-01-21", ALPHA
        )

        voluntary_calculated = validate_success(
            api_client.calculate_compensation(
                voluntary["id"],
                calculate_compensation_payload("2028-01-21", 180000000),
                ALPHA,
            )
        )
        default_calculated = validate_success(
            api_client.calculate_compensation(
                default["id"],
                calculate_compensation_payload(
                    "2028-01-21",
                    180000000,
                    market_value_estimate_cents=210000000,
                    rectification_cost_cents=15000000,
                    authority_reprocurement_cost_cents=8000000,
                ),
                ALPHA,
            )
        )

        # 210000000 - 15000000 - 8000000 - 1720833
        assert default_calculated["compensation_cents"] == 185279167
        assert default_calculated["market_value_estimate_cents"] == 210000000
        assert voluntary_calculated["compensation_cents"] == 290279167
        assert voluntary_calculated["market_value_estimate_cents"] is None
        assert (
            voluntary_calculated["compensation_cents"]
            - default_calculated["compensation_cents"]
            == 105000000
        )
        assert default_calculated["status"] == "COMPENSATION_CALCULATED"
        assert voluntary_calculated["status"] == "COMPENSATION_CALCULATED"
        assert refresh_concession(ctx)["status"] == "OPERATIONS"
