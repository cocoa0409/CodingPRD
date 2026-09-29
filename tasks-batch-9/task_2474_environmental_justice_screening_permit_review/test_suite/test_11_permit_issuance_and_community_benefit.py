"""Issuance arithmetic and the rejection precedence in front of it.

The community benefit surcharge is keyed on the requested base rather than the
total it produces, and when an issuance request trips two gates at once the
earlier gate in the §2.10 ladder is the one that answers.
"""

from test_helpers import (
    ANALYST_HEADERS,
    APP_ENHANCED_REVIEW,
    APP_ISSUED,
    APP_PENDING_DECISION,
    ApiErrorId,
    ASSESSMENT_DRAFT,
    DECISION_ISSUED,
    DENIAL_THRESHOLD,
    DESIGNATION_MULTIPLIER,
    DESIGNATION_OVERBURDENED,
    DISPOSITION_ISSUE,
    MANAGER_HEADERS,
    MANAGER_USER_ID,
    MIN_BENEFIT_PER_APPROVED_TON,
    SURCHARGE_RATE_LOW,
    SURCHARGE_TIER_MID_BASE,
    assert_amount,
    assert_amounts,
    assert_empty_listing,
    assert_field,
    assert_fields,
    assert_ledgers,
    assert_rejected,
    decision_payload,
    find_assessment,
    find_decision,
    read_application,
    read_area,
    read_facility,
)


class TestCommunityBenefitSurchargeTier:
    """PRD §3.7 reads the surcharge tier off the input, not off the output."""

    def test_a_95000_base_takes_the_low_rate_not_the_rate_its_total_would_imply(
        self, api, app_a_issued
    ):
        """95000.00 sits under the 100000.00 tier, so the rate is 0.05.

        PRD §3.7: "The community benefit obligation is computed in a pinned order,
        and its tier selection is deliberately keyed on the input rather than the
        output. Begin from the requested `community_benefit_base_usd` and compute the
        application's `approved_net_emissions_tpy` from the mitigation credit
        aggregation." and "**Select the surcharge rate from the base**, never from the
        total the surcharge feeds: 0.12 when the base is at least 500000.00 US
        dollars, otherwise 0.08 when it is at least 100000.00, otherwise 0.05." and
        "Then choose a designation multiplier of 1.25 when the area's `designation` is
        `SEVERELY_OVERBURDENED`, 1.10 when it is `OVERBURDENED`, and 1.00 when it is
        `UNDESIGNATED`." and "`community_benefit_surcharge_usd` is the base multiplied
        by the surcharge rate multiplied by the designation multiplier, rounded half
        up to two decimals, and `community_benefit_total_usd` is the base plus that
        surcharge, rounded half up to two decimals."

        Design: Difficulty/combinatorial_formula/community_benefit_surcharge_tier_keyed_on_base_not_total
        """
        state = app_a_issued
        assert_field(
            read_area(api, state["area_id"]), "designation", DESIGNATION_OVERBURDENED
        )

        decision = find_decision(api, state["app_id"], state["decision_id"])

        assert_amounts(
            decision,
            {
                "community_benefit_base_usd": 95000.00,
                # 95000.00 x 0.05 x 1.10 = 5225.00.
                "community_benefit_surcharge_usd": 5225.00,
                "community_benefit_total_usd": 100225.00,
            },
        )
        assert decision["community_benefit_base_usd"] < SURCHARGE_TIER_MID_BASE, (
            "the base must sit below the 100000.00 tier for the 0.05 rate to apply"
        )
        expected_surcharge = round(
            decision["community_benefit_base_usd"]
            * SURCHARGE_RATE_LOW
            * DESIGNATION_MULTIPLIER[DESIGNATION_OVERBURDENED],
            2,
        )
        assert_amount(
            decision.get("community_benefit_surcharge_usd"),
            expected_surcharge,
            "community_benefit_surcharge_usd",
        )
        # Reading the tier off the 103360.00 total would give 0.08 and 8360.00.
        assert abs(decision["community_benefit_surcharge_usd"] - 8360.00) > 0.005, (
            "the surcharge must not be derived from the total it feeds"
        )
        assert abs(decision["community_benefit_total_usd"] - 103360.00) > 0.005, (
            "the total must not be derived from a tier read off itself"
        )

    def test_the_cleared_issuance_meets_its_minimum_and_books_both_ledgers(
        self, api, app_a_issued
    ):
        """A 100225.00 total clears the 75000.00 minimum and 50.00 tpy is booked.

        PRD §3.7: "The minimum required commitment is **1,500.00 US dollars per
        approved net ton** — that is, 1500.00 multiplied by
        `approved_net_emissions_tpy`, rounded half up to two decimals — and the fiscal
        gate applies only when the area's `designation` is not `UNDESIGNATED`: a
        `community_benefit_total_usd` below the minimum is refused with
        `ERR_BENEFIT_COMMITMENT_INSUFFICIENT`."
        PRD §3.7: "A cleared issuance moves the application `PENDING_DECISION →
        ISSUED` and writes a decision in `status` `ISSUED` carrying the approved net
        emissions, both benefit amounts and the residual snapshot." and "The
        application's own `approved_net_emissions_tpy` is set to its
        `proposed_emissions_tpy` minus `total_mitigation_credit_tpy`, floored at 0.00
        and rounded half up to two decimals; the facility's `existing_load_tpy` and
        the area's `permitted_load_tpy` are each increased by that amount; and the
        application's `version` increments by 1."
        PRD §3.7: "The decision record carries `residual_index_at_decision`, a
        snapshot of the application's `residual_impact_index` at decision time, and
        `decided_by_user_id`, the deciding manager's `X-User-ID`."

        Design: Difficulty/combinatorial_formula/community_benefit_surcharge_tier_keyed_on_base_not_total
        """
        state = app_a_issued
        decision = find_decision(api, state["app_id"], state["decision_id"])
        assert_fields(
            decision,
            {
                "status": DECISION_ISSUED,
                "decided_by_user_id": MANAGER_USER_ID,
            },
        )
        assert_amounts(
            decision,
            {
                "approved_net_emissions_tpy": 50.00,
                "residual_index_at_decision": 51.14,
            },
        )

        minimum = round(MIN_BENEFIT_PER_APPROVED_TON * 50.00, 2)
        assert_amount(minimum, 75000.00, "per-ton minimum commitment")
        assert decision["community_benefit_total_usd"] >= minimum, (
            "the committed total should clear the per-ton minimum"
        )

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_ISSUED)
        assert_amount(
            application.get("approved_net_emissions_tpy"),
            50.00,
            "approved_net_emissions_tpy",
        )

        assert_ledgers(
            area=read_area(api, state["area_id"]),
            facility=read_facility(api, state["facility_id"]),
            permitted_load_tpy=50.00,
            existing_load_tpy=50.00,
        )


class TestStateCheckOutranksAssessmentCheck:
    """PRD §2.10 answers with the state code when both checks would fail."""

    def test_issuing_from_enhanced_review_reports_the_state_error(
        self, api, app_a_screening_assessment
    ):
        """The application is not `PENDING_DECISION`, so that failure answers first.

        PRD §2.10: "When a single request violates more than one rule, exactly one
        error is returned, and which one is fully determined. The server evaluates
        checks in the following order and returns the first failure it finds; a later
        check never masks an earlier one."
        PRD §2.10: "The target resource is in a state from which the requested
        transition is declared — otherwise the per-family state code:
        `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_ASSESSMENT_STATE`,
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_MEETING_STATE`,
        `ERR_INVALID_CONDITION_STATE`, `ERR_INVALID_DECISION_STATE`,
        `ERR_INVALID_COMPLAINT_STATE`, `ERR_INVALID_INSPECTION_STATE`, or
        `ERR_AREA_NOT_STALE` when recertification is asked of an area whose
        `data_status` is already `CURRENT`. All are HTTP 409."
        PRD §2.10: "Advance-to-decision and permit decision creation: on the enhanced
        track the governing assessment exists and is `ACCEPTED` — otherwise
        `ERR_ASSESSMENT_NOT_ACCEPTED` (409)."
        PRD §3.7: "A `PermitManager` decides a `PENDING_DECISION` application by
        naming its `permit_application_id` and a `disposition` of `ISSUE` or `DENY`."

        Design: Difficulty/priority_pair_validation_conflict/decision_state_precondition_outranks_assessment_not_accepted
        """
        state = app_a_screening_assessment
        assert_field(
            read_application(api, state["app_id"]), "status", APP_ENHANCED_REVIEW
        )
        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_DRAFT,
        )

        response = api.create_permit_decision(
            decision_payload(
                permit_application_id=state["app_id"],
                disposition=DISPOSITION_ISSUE,
                community_benefit_base_usd=200000.00,
            ),
            MANAGER_HEADERS,
        )

        assert_rejected(response, ApiErrorId.INVALID_APPLICATION_STATE)
        assert response.status_code == 409, (
            "the state failure is an HTTP 409 conflict"
        )
        # The later assessment check would also have failed, and must not answer.
        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.ASSESSMENT_NOT_ACCEPTED, (
            "the assessment check must not mask the earlier state check"
        )

    def test_the_refused_issuance_leaves_the_whole_file_untouched(
        self, api, app_a_screening_assessment
    ):
        """No decision row, no approved tonnage and no ledger movement.

        PRD §2.10: "When a single request violates more than one rule, exactly one
        error is returned, and which one is fully determined."
        PRD §3.7: "A cleared issuance moves the application `PENDING_DECISION →
        ISSUED` and writes a decision in `status` `ISSUED` carrying the approved net
        emissions, both benefit amounts and the residual snapshot."
        PRD §2.12: "Both start at 0.00, both move only on permit issuance and permit
        rescission, and both are maintained by increment and decrement rather than by
        recomputation from scratch: issuance adds the application's
        `approved_net_emissions_tpy` to both ledgers, and rescission subtracts the
        same amount from both before zeroing the application's own
        `approved_net_emissions_tpy`."

        Design: Difficulty/priority_pair_validation_conflict/decision_state_precondition_outranks_assessment_not_accepted
        """
        state = app_a_screening_assessment
        response = api.create_permit_decision(
            decision_payload(
                permit_application_id=state["app_id"],
                disposition=DISPOSITION_ISSUE,
                community_benefit_base_usd=200000.00,
            ),
            MANAGER_HEADERS,
        )
        assert_rejected(response, ApiErrorId.INVALID_APPLICATION_STATE)

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_ENHANCED_REVIEW)
        assert_amount(
            application.get("approved_net_emissions_tpy"),
            0.00,
            "approved_net_emissions_tpy",
        )

        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_DRAFT,
        )
        assert_empty_listing(
            api.list_application_decisions(state["app_id"], ANALYST_HEADERS)
        )
        assert_ledgers(
            area=read_area(api, state["area_id"]),
            facility=read_facility(api, state["facility_id"]),
            permitted_load_tpy=0.00,
            existing_load_tpy=0.00,
        )


class TestImpactGateOutranksFiscalGate:
    """PRD §2.10 refuses on the unmitigated impact before the money."""

    def test_an_unmitigated_residual_answers_before_the_benefit_shortfall(
        self, api, app_a_pending_decision
    ):
        """81.82 residual and a 42200.00 total both fail; the impact gate answers.

        PRD §2.10: "Issuance: `residual_impact_index` is below the denial threshold —
        otherwise `ERR_DISPROPORTIONATE_IMPACT_UNMITIGATED` (409)."
        PRD §2.10: "Issuance: the community benefit total meets the per-ton minimum
        when the area is designated — otherwise
        `ERR_BENEFIT_COMMITMENT_INSUFFICIENT` (422)."
        PRD §3.7: "The application's `residual_impact_index` must be **strictly below
        60.00**; an impact that mitigation could not bring under that threshold may
        not be permitted, and the refusal carries
        `ERR_DISPROPORTIONATE_IMPACT_UNMITIGATED`."

        Design: Difficulty/priority_pair_validation_conflict/disproportionate_impact_outranks_insufficient_benefit
        """
        state = app_a_pending_decision
        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_PENDING_DECISION)
        assert_amounts(
            application,
            {
                "residual_impact_index": 81.82,
                "total_mitigation_credit_tpy": 0.00,
                "approved_net_emissions_tpy": 0.00,
            },
        )
        assert application["residual_impact_index"] >= DENIAL_THRESHOLD, (
            "the residual must sit at or above the 60.00 denial threshold"
        )

        response = api.create_permit_decision(
            decision_payload(
                permit_application_id=state["app_id"],
                disposition=DISPOSITION_ISSUE,
                community_benefit_base_usd=40000.00,
            ),
            MANAGER_HEADERS,
        )

        assert_rejected(response, ApiErrorId.DISPROPORTIONATE_IMPACT_UNMITIGATED)
        assert response.status_code == 409, (
            "the unmitigated-impact failure is an HTTP 409 conflict"
        )
        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.BENEFIT_COMMITMENT_INSUFFICIENT, (
            "the fiscal gate must not mask the earlier impact gate"
        )

    def test_the_shortfall_that_did_not_answer_was_real(
        self, api, app_a_pending_decision
    ):
        """A 42200.00 total is far below the 120000.00 minimum for 80.00 tons.

        PRD §3.7: "**Select the surcharge rate from the base**, never from the total
        the surcharge feeds: 0.12 when the base is at least 500000.00 US dollars,
        otherwise 0.08 when it is at least 100000.00, otherwise 0.05."
        PRD §3.7: "The minimum required commitment is **1,500.00 US dollars per
        approved net ton** — that is, 1500.00 multiplied by
        `approved_net_emissions_tpy`, rounded half up to two decimals — and the fiscal
        gate applies only when the area's `designation` is not `UNDESIGNATED`: a
        `community_benefit_total_usd` below the minimum is refused with
        `ERR_BENEFIT_COMMITMENT_INSUFFICIENT`."
        PRD §3.6: "From the credit total comes the application's
        `approved_net_emissions_tpy` figure: the application's
        `proposed_emissions_tpy` minus `total_mitigation_credit_tpy`, floored at 0.00,
        rounded half up to two decimals."

        Design: Difficulty/priority_pair_validation_conflict/disproportionate_impact_outranks_insufficient_benefit
        """
        state = app_a_pending_decision
        application = read_application(api, state["app_id"])
        assert_amount(
            application.get("proposed_emissions_tpy"), 80.00, "proposed_emissions_tpy"
        )

        # 40000.00 x 0.05 x 1.10 = 2200.00, so the total on offer is 42200.00.
        offered_total = round(
            40000.00
            + 40000.00
            * SURCHARGE_RATE_LOW
            * DESIGNATION_MULTIPLIER[DESIGNATION_OVERBURDENED],
            2,
        )
        assert_amount(offered_total, 42200.00, "offered community benefit total")
        minimum = round(MIN_BENEFIT_PER_APPROVED_TON * 80.00, 2)
        assert_amount(minimum, 120000.00, "per-ton minimum commitment")
        assert offered_total < minimum, (
            "the offered total should fall short of the per-ton minimum"
        )

        response = api.create_permit_decision(
            decision_payload(
                permit_application_id=state["app_id"],
                disposition=DISPOSITION_ISSUE,
                community_benefit_base_usd=40000.00,
            ),
            MANAGER_HEADERS,
        )
        assert_rejected(response, ApiErrorId.DISPROPORTIONATE_IMPACT_UNMITIGATED)

        assert_field(
            read_application(api, state["app_id"]), "status", APP_PENDING_DECISION
        )
        assert_empty_listing(
            api.list_application_decisions(state["app_id"], MANAGER_HEADERS)
        )
        assert_ledgers(
            area=read_area(api, state["area_id"]),
            facility=read_facility(api, state["facility_id"]),
            permitted_load_tpy=0.00,
            existing_load_tpy=0.00,
        )
