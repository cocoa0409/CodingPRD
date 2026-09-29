"""Per-condition credit rounding and the residual index it drives.

Three identical monitoring conditions each earn a raw 1.235 tpy of credit, so the
pinned round-then-sum order and the forbidden sum-then-round order are separated
by exactly one cent — a cent that then moves the residual impact index.
"""

from test_helpers import (
    APP_ENHANCED_REVIEW,
    CONDITION_ACTIVE,
    CONDITION_MONITORING,
    MITIGATION_CAP_HIGH,
    MONITORING_CONTINUOUS,
    MONITORING_QUARTERLY,
    add_condition,
    assert_amount,
    assert_amounts,
    assert_field,
    assert_page,
    assert_ratio,
    ANALYST_HEADERS,
    find_condition,
    read_application,
)


class TestPerConditionCreditRounding:
    """PRD §3.6 rounds each condition's credit before anything is summed."""

    def test_each_monitoring_condition_rounds_its_own_credit_to_1_24(
        self, api, app_a_assessment_accepted
    ):
        """12.35 tpy at 0.20 efficacy and 0.50 enforceability rounds up to 1.24.

        PRD §3.6: "Credit is earned per condition and stored on the condition as
        `credit_tpy`. Multiply the condition's `reduction_tpy` by its family's
        efficacy factor — **1.00** for `ADDITIONAL_CONTROL`, **0.20** for
        `MONITORING` and **0.10** for `COMMUNITY_BENEFIT` — and then by an
        enforceability factor of 1.00 when `enforceable` is true or **0.50** when it
        is false; round the product half up to two decimals."
        PRD §3.6: "A `MONITORING` condition requires a `monitoring_frequency` of
        `CONTINUOUS`, `QUARTERLY` or `ANNUAL`."
        PRD §3.6: "A condition lands in `status` `ACTIVE` and stamps
        `application_version_after`."

        Design: Difficulty/combinatorial_formula/mitigation_credit_round_per_condition_then_sum
        """
        state = app_a_assessment_accepted
        assert_amount(
            read_application(api, state["app_id"]).get("pre_mitigation_index"),
            81.82,
            "pre_mitigation_index",
        )

        frequencies = (MONITORING_QUARTERLY, MONITORING_QUARTERLY, MONITORING_CONTINUOUS)
        condition_ids = []
        for frequency in frequencies:
            condition = add_condition(
                api,
                state,
                CONDITION_MONITORING,
                reduction_tpy=12.35,
                enforceable=False,
                monitoring_frequency=frequency,
            )
            condition_ids.append(condition["id"])
            # 12.35 x 0.20 x 0.50 = 1.235, which rounds half up to 1.24.
            assert_amount(condition.get("credit_tpy"), 1.24, "credit_tpy")
            assert_field(condition, "status", CONDITION_ACTIVE)
            assert_field(condition, "enforceable", False)

        for condition_id in condition_ids:
            stored = find_condition(api, state["app_id"], condition_id)
            assert_amount(stored.get("credit_tpy"), 1.24, "credit_tpy")
            assert_field(stored, "condition_type", CONDITION_MONITORING)

        rows = assert_page(
            api.list_application_conditions(state["app_id"], ANALYST_HEADERS),
            expected_rows=3,
            expected_total=3,
            expected_has_more=False,
        )
        for row in rows:
            assert_field(row, "status", CONDITION_ACTIVE)

    def test_the_credit_total_sums_the_rounded_values_not_the_raw_products(
        self, api, app_a_assessment_accepted
    ):
        """Three rounded 1.24 credits total 3.72, never the raw-sum 3.71.

        PRD §3.6: "The application's `total_mitigation_credit_tpy` is then the sum of
        the `credit_tpy` values of the application's `ACTIVE` conditions only,
        accumulated in `created_at` ascending order with ties broken by `version`
        ascending, and rounded half up to two decimals." and "**The rounding order is
        pinned: round each condition's credit first, then sum the rounded values.**"
        and "The alternative reading — summing the raw products and rounding once at
        the end — is not used and produces a different number whenever the raw
        products carry a third decimal."

        Design: Difficulty/combinatorial_formula/mitigation_credit_round_per_condition_then_sum
        """
        state = app_a_assessment_accepted
        for frequency in (MONITORING_QUARTERLY, MONITORING_QUARTERLY, MONITORING_CONTINUOUS):
            add_condition(
                api,
                state,
                CONDITION_MONITORING,
                reduction_tpy=12.35,
                enforceable=False,
                monitoring_frequency=frequency,
            )

        application = read_application(api, state["app_id"])

        assert_amount(
            application.get("total_mitigation_credit_tpy"), 3.72, "total_mitigation_credit_tpy"
        )
        # Summing the raw 1.235 products first would give 3.705 and round to 3.71.
        assert abs(application["total_mitigation_credit_tpy"] - 3.71) > 0.001, (
            "the sum-then-round reading of 3.71 must not be used"
        )
        assert_field(application, "status", APP_ENHANCED_REVIEW)


class TestResidualImpactFromCredit:
    """PRD §3.6 turns the credit total into the residual the denial rests on."""

    def test_the_credit_ratio_stays_under_the_cap_and_sets_the_residual_to_78_02(
        self, api, app_a_assessment_accepted
    ):
        """A 0.0465 credit ratio is far below the 0.60 cap, so it governs directly.

        PRD §3.6: "Begin with the application's `pre_mitigation_index`, taken from
        the governing assessment. Compute the credit ratio as
        `total_mitigation_credit_tpy` divided by `proposed_emissions_tpy`, rounded
        half up to four decimals, then capped at 1.0000." and "Select the mitigation
        cap from the **pre-mitigation** index, never from the residual it produces:
        the cap is 0.60 when `pre_mitigation_index` is at least 75.00, otherwise 0.75
        when it is at least 50.00, otherwise 1.00; both comparisons are inclusive."
        and "The effective reduction is the smaller of the credit ratio and the cap."
        and "Finally, `residual_impact_index` is `pre_mitigation_index` multiplied by
        one minus the effective reduction, rounded half up to two decimals."
        PRD §3.6: "Attaching a condition recomputes the credit aggregation and the
        residual index, increments the application's `version` by 1 and stamps
        `application_version_after`."

        Design: Difficulty/combinatorial_formula/mitigation_credit_round_per_condition_then_sum
        """
        state = app_a_assessment_accepted
        for frequency in (MONITORING_QUARTERLY, MONITORING_QUARTERLY, MONITORING_CONTINUOUS):
            add_condition(
                api,
                state,
                CONDITION_MONITORING,
                reduction_tpy=12.35,
                enforceable=False,
                monitoring_frequency=frequency,
            )

        application = read_application(api, state["app_id"])

        assert_amounts(
            application,
            {
                "pre_mitigation_index": 81.82,
                "total_mitigation_credit_tpy": 3.72,
                # 81.82 x (1 - 0.0465) = 78.0153, rounding half up to 78.02.
                "residual_impact_index": 78.02,
            },
        )
        credit_ratio = round(
            application["total_mitigation_credit_tpy"]
            / application["proposed_emissions_tpy"],
            4,
        )
        assert_ratio(credit_ratio, 0.0465, "credit ratio")
        assert credit_ratio < MITIGATION_CAP_HIGH, (
            "the credit ratio should bind before the 0.60 mitigation cap does"
        )

    def test_the_one_cent_credit_difference_shows_up_in_the_approved_net(
        self, api, app_a_assessment_accepted
    ):
        """The pinned 3.72 total drives the residual; the forbidden 3.71 would not.

        PRD §3.6: "**The rounding order is pinned: round each condition's credit
        first, then sum the rounded values.**"

        Design: Difficulty/combinatorial_formula/mitigation_credit_round_per_condition_then_sum
        """
        state = app_a_assessment_accepted
        for frequency in (MONITORING_QUARTERLY, MONITORING_QUARTERLY, MONITORING_CONTINUOUS):
            add_condition(
                api,
                state,
                CONDITION_MONITORING,
                reduction_tpy=12.35,
                enforceable=False,
                monitoring_frequency=frequency,
            )

        application = read_application(api, state["app_id"])

        assert_amount(
            application.get("total_mitigation_credit_tpy"), 3.72, "total_mitigation_credit_tpy"
        )
        assert_amount(application.get("residual_impact_index"), 78.02, "residual_impact_index")
        # The pinned 3.72 total, not the forbidden raw-sum 3.71, is what the residual
        # and the eventual approved-net figure are both derived from.
        assert abs(application["total_mitigation_credit_tpy"] - 3.71) > 0.001, (
            "the sum-then-round reading of 3.71 must not be used"
        )
