"""Requests that break two rules at once, where only the lower-numbered rule is reported."""

from test_helpers import (
    AllocationBasis,
    ApiErrorId,
    BudgetDecision,
    BudgetStatus,
    DUAL_MANAGER_HEADERS,
    DUAL_USER_ID,
    MANAGER_HEADERS,
    MANAGER_USER_ID,
    OWNER_HEADERS,
    OWNER_USER_ID,
    Role,
    ServiceCode,
    assert_error_envelope,
    assert_page,
    budget_decision_payload,
    charge_payload,
    headers_with_role,
)


def _error_id(response) -> str:
    return response.json()["data"]["error_id"]


# ---------------------------------------------------------------------------
# Uniqueness (rule 37) against the aggregate period cap (rule 44)
# ---------------------------------------------------------------------------


def _priority_pair_hotel_a(scenario):
    """A frozen-cap period with 325000 of headroom left and RESERVATIONS already taken."""
    agreement = scenario.register(
        hotel_name="Priority Pair Hotel A",
        owner_entity_name="Conflict Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        centralized_services_cap_pct=0.015,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    package = scenario.expert_package(agreement["id"], fiscal_year=2026, period_month=9)
    charge = scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "charge_id": charge["id"],
    }


def _repeat_reservations(scenario, package_id):
    """A post that is both a duplicate service code and 675000 cents over the cap."""
    return scenario.api.create_centralized_charge(
        package_id,
        charge_payload(
            service_code=ServiceCode.RESERVATIONS,
            allocation_basis=AllocationBasis.HEADCOUNT,
            pool_amount_cents=20000000,
            hotel_basis_share=0.05,
        ),
        MANAGER_HEADERS,
    )


def _fresh_procurement(scenario, package_id):
    """The same oversized post under an untouched service code."""
    return scenario.api.create_centralized_charge(
        package_id,
        charge_payload(
            service_code=ServiceCode.PROCUREMENT,
            allocation_basis=AllocationBasis.HEADCOUNT,
            pool_amount_cents=20000000,
            hotel_basis_share=0.05,
        ),
        MANAGER_HEADERS,
    )


class TestDuplicateServiceCodeBeatsThePeriodCap:
    def test_duplicate_service_code_is_the_reported_error(self, scenario):
        """PRD §2.8: "When a request violates several rules at once, exactly one error is
        reported: the one belonging to the lowest-numbered rule below. The ordering is
        absolute and spans every endpoint." and rule 37: "The package carries no existing
        charge with the same `service_code`; otherwise `ERR_SERVICE_CODE_ALREADY_CHARGED`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_service_code_outranks_centralized_cap_exceeded
        """
        state = _priority_pair_hotel_a(scenario)

        response = _repeat_reservations(scenario, state["package_id"])

        assert_error_envelope(response, ApiErrorId.SERVICE_CODE_ALREADY_CHARGED)
        assert response.status_code == 409
        # Its requested 1000000 also blows through the 325000 of remaining cap.
        assert _error_id(response) != ApiErrorId.CENTRALIZED_CAP_EXCEEDED

    def test_a_fresh_service_code_isolates_the_cap_rejection(self, scenario):
        """PRD §2.8 rule 44: "Cumulative `requested_amount_cents` across the package's
        charges, including the incoming one, is at most the period cap — the floor of the
        package's `gross_revenue_cents` multiplied by the agreement's
        `centralized_services_cap_pct` — whenever the incoming charge carries
        `allow_deferral` false; otherwise `ERR_CENTRALIZED_CAP_EXCEEDED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_service_code_outranks_centralized_cap_exceeded
        """
        state = _priority_pair_hotel_a(scenario)

        response = _fresh_procurement(scenario, state["package_id"])

        assert_error_envelope(response, ApiErrorId.CENTRALIZED_CAP_EXCEEDED)
        assert response.status_code == 422

    def test_neither_rejected_post_left_a_charge_behind(self, scenario):
        """PRD §3.5: "Finally the package's `allocated_centralized_cents` is set to the sum of
        the allocated amounts across all its charges." PRD §2.3: "`total_count` counts every
        row matching the filters before paging is applied"

        Design: Difficulty/priority_pair_validation_conflict/duplicate_service_code_outranks_centralized_cap_exceeded
        """
        state = _priority_pair_hotel_a(scenario)

        _repeat_reservations(scenario, state["package_id"])
        _fresh_procurement(scenario, state["package_id"])

        rows = assert_page(
            scenario.api.list_centralized_charges(state["package_id"], MANAGER_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["id"] == state["charge_id"]
        assert rows[0]["allocated_amount_cents"] == 500000
        assert scenario.read_package(state["package_id"])["allocated_centralized_cents"] == 500000


# ---------------------------------------------------------------------------
# Segregation of duties (rule 30) against the one-approval-per-year rule (rule 38)
# ---------------------------------------------------------------------------


def _priority_pair_hotel_b(scenario):
    """An approved FY2026 budget plus a second FY2026 budget submitted by u-dual-1."""
    agreement = scenario.register(
        hotel_name="Priority Pair Hotel B",
        owner_entity_name="Duties Owner LP",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        owner_review_window_days=30,
    )
    scenario.activate(agreement["id"])

    first = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
    )
    scenario.submit_budget(first["id"], MANAGER_HEADERS)
    scenario.decide_budget(first["id"], BudgetDecision.APPROVE, OWNER_HEADERS)

    second = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=610000000,
        budgeted_operating_expenses_cents=405000000,
    )
    scenario.submit_budget(second["id"], DUAL_MANAGER_HEADERS)

    return {
        "agreement_id": agreement["id"],
        "first_id": first["id"],
        "second_id": second["id"],
    }


class TestSegregationOfDutiesBeatsTheApprovedYear:
    def test_the_shared_identity_is_the_reported_error(self, scenario):
        """PRD §3.2: "the acting `X-User-ID` must differ from `submitted_by_user_id`
        (otherwise `ERR_SEGREGATION_OF_DUTIES`), and — on the approval branch — no other
        budget of the same agreement and fiscal year may already hold `APPROVED`,
        `DEEMED_APPROVED` or `DEADLOCK_CARRYFORWARD` (otherwise
        `ERR_BUDGET_YEAR_ALREADY_APPROVED`)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_budget_year_already_approved
        """
        state = _priority_pair_hotel_b(scenario)

        response = scenario.api.decide_budget(
            state["second_id"],
            budget_decision_payload(BudgetDecision.APPROVE),
            headers_with_role(DUAL_USER_ID, Role.OWNER_REP),
        )

        assert_error_envelope(response, ApiErrorId.SEGREGATION_OF_DUTIES)
        assert response.status_code == 403
        assert _error_id(response) != ApiErrorId.BUDGET_YEAR_ALREADY_APPROVED

    def test_a_distinct_decider_isolates_the_approved_year_rejection(self, scenario):
        """PRD §2.8 rule 38: "No other budget of the same agreement and `fiscal_year` already
        holds `APPROVED`, `DEEMED_APPROVED` or `DEADLOCK_CARRYFORWARD`; otherwise
        `ERR_BUDGET_YEAR_ALREADY_APPROVED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_budget_year_already_approved
        """
        state = _priority_pair_hotel_b(scenario)

        response = scenario.api.decide_budget(
            state["second_id"], budget_decision_payload(BudgetDecision.APPROVE), OWNER_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.BUDGET_YEAR_ALREADY_APPROVED)
        assert response.status_code == 409

    def test_both_rejections_leave_the_two_budgets_as_they_stood(self, scenario):
        """PRD §3.2: "An approval moves the row `SUBMITTED → APPROVED` and records
        `decided_by_user_id` as the acting `X-User-ID`; that is its entire effect."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_budget_year_already_approved
        """
        state = _priority_pair_hotel_b(scenario)

        scenario.api.decide_budget(
            state["second_id"],
            budget_decision_payload(BudgetDecision.APPROVE),
            headers_with_role(DUAL_USER_ID, Role.OWNER_REP),
        )
        scenario.api.decide_budget(
            state["second_id"], budget_decision_payload(BudgetDecision.APPROVE), OWNER_HEADERS
        )

        second = scenario.read_budget(state["second_id"])
        assert second["status"] == BudgetStatus.SUBMITTED
        assert second["decided_by_user_id"] is None
        assert second["submitted_by_user_id"] == DUAL_USER_ID

        first = scenario.read_budget(state["first_id"])
        assert first["status"] == BudgetStatus.APPROVED
        assert first["decided_by_user_id"] == OWNER_USER_ID


# ---------------------------------------------------------------------------
# Budget state (rule 20) against segregation of duties (rule 30)
# ---------------------------------------------------------------------------


def _priority_pair_hotel_c(scenario):
    """Two FY2026 budgets both submitted by u-mgr-1, the first already approved."""
    agreement = scenario.register(
        hotel_name="Priority Pair Hotel C",
        owner_entity_name="State First Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        owner_review_window_days=30,
    )
    scenario.activate(agreement["id"])

    first = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
    )
    scenario.submit_budget(first["id"], MANAGER_HEADERS)
    scenario.decide_budget(first["id"], BudgetDecision.APPROVE, OWNER_HEADERS)

    second = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=605000000,
        budgeted_operating_expenses_cents=402000000,
    )
    scenario.submit_budget(second["id"], MANAGER_HEADERS)

    return {
        "agreement_id": agreement["id"],
        "first_id": first["id"],
        "second_id": second["id"],
    }


class TestBudgetStateBeatsSegregationOfDuties:
    def test_the_wrong_origin_status_is_the_reported_error(self, scenario):
        """PRD §2.8 rule 20: "The budget's `status` is one the requested transition declares
        as its origin; otherwise `ERR_INVALID_BUDGET_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_budget_state_outranks_segregation_of_duties
        """
        state = _priority_pair_hotel_c(scenario)

        response = scenario.api.decide_budget(
            state["first_id"],
            budget_decision_payload(BudgetDecision.REQUEST_REVISION),
            headers_with_role(MANAGER_USER_ID, Role.OWNER_REP),
        )

        assert_error_envelope(response, ApiErrorId.INVALID_BUDGET_STATE)
        assert response.status_code == 409
        # The acting id also collides with the budget's own submitter.
        assert _error_id(response) != ApiErrorId.SEGREGATION_OF_DUTIES

    def test_a_still_submitted_budget_isolates_the_duties_rejection(self, scenario):
        """PRD §2.8 rule 30: "The acting `X-User-ID` differs from the `submitted_by_user_id`
        of the budget being decided, and from the `requested_by_user_id` of the variance
        request being decided; otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_budget_state_outranks_segregation_of_duties
        """
        state = _priority_pair_hotel_c(scenario)

        response = scenario.api.decide_budget(
            state["second_id"],
            budget_decision_payload(BudgetDecision.REQUEST_REVISION),
            headers_with_role(MANAGER_USER_ID, Role.OWNER_REP),
        )

        assert_error_envelope(response, ApiErrorId.SEGREGATION_OF_DUTIES)
        assert response.status_code == 403

    def test_neither_rejection_spent_a_revision_round(self, scenario):
        """PRD §3.2: "When `revision_round` is strictly below the agreement's
        `max_revision_rounds`, the row moves `SUBMITTED → REVISION_REQUESTED` and records
        `decided_by_user_id`; the manager may then revise and resubmit."

        Design: Difficulty/priority_pair_validation_conflict/invalid_budget_state_outranks_segregation_of_duties
        """
        state = _priority_pair_hotel_c(scenario)

        scenario.api.decide_budget(
            state["first_id"],
            budget_decision_payload(BudgetDecision.REQUEST_REVISION),
            headers_with_role(MANAGER_USER_ID, Role.OWNER_REP),
        )
        scenario.api.decide_budget(
            state["second_id"],
            budget_decision_payload(BudgetDecision.REQUEST_REVISION),
            headers_with_role(MANAGER_USER_ID, Role.OWNER_REP),
        )

        first = scenario.read_budget(state["first_id"])
        assert first["status"] == BudgetStatus.APPROVED
        assert first["revision_round"] == 0

        second = scenario.read_budget(state["second_id"])
        assert second["status"] == BudgetStatus.SUBMITTED
        assert second["revision_round"] == 0
