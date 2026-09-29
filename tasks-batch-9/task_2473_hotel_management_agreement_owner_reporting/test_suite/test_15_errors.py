"""The error catalogue: identity, entity-specific not-found and state codes."""

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    AgreementStatus,
    ApiErrorId,
    BudgetDecision,
    BudgetStatus,
    CallReason,
    CallStatus,
    ClaimAction,
    ClaimStatus,
    DisputeStatus,
    FinancialStatus,
    HEADERS_BY_ROLE,
    MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    ONLY_ROLE_HEADERS,
    ONLY_USER_ID_HEADERS,
    OWNER_HEADERS,
    PositionClass,
    ReviewDecision,
    ReviewDimension,
    UNDECLARED_ROLE,
    assert_error_envelope,
    assert_object_envelope,
    assert_page,
    budget_decision_payload,
    budget_payload,
    claim_allocation_payload,
    contest_payload,
    elect_cure_payload,
    fund_payload,
    headers_with_role,
    owner_counter_payload,
    owner_review_payload,
    variance_decision_payload,
    working_capital_call_payload,
)


# ---------------------------------------------------------------------------
# No identity at all
# ---------------------------------------------------------------------------


def _auth_header_hotel(scenario):
    """One ACTIVE agreement so the probed path resolves to a real row."""
    agreement = scenario.register(
        hotel_name="Auth Header Hotel",
        owner_entity_name="Auth Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(agreement["id"])
    return agreement["id"]


class TestMissingRoleHeaderReturnsUnauthenticated:
    def test_absent_headers_are_refused_before_the_row_is_read(self, scenario):
        """PRD §2.8 rule 1: "Both headers present and `X-User-Role` among the four declared roles;
        otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint." PRD §2.2: "The `meta`
        object for error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/missing_role_header_returns_unauthenticated
        """
        agreement_id = _auth_header_hotel(scenario)

        nothing = scenario.api.get_agreement(agreement_id, NO_HEADERS)
        no_role = scenario.api.get_agreement(agreement_id, ONLY_USER_ID_HEADERS)
        no_user = scenario.api.get_agreement(agreement_id, ONLY_ROLE_HEADERS)

        for response in (nothing, no_role, no_user):
            assert_error_envelope(response, ApiErrorId.UNAUTHENTICATED)
            assert response.status_code == 401
            meta = response.json()["meta"]
            assert meta["api_request_id"]
            assert meta["api_request_timestamp"]

    def test_an_undeclared_role_is_unauthenticated_rather_than_unauthorized(self, scenario):
        """PRD §2.8 rule 1: "Both headers present and `X-User-Role` among the four declared roles;
        otherwise `ERR_UNAUTHENTICATED` (401)." PRD §2.8 rule 2: "The acting role appears in the
        endpoint's authorized-roles list; otherwise `ERR_UNAUTHORIZED` (403). Applies to every
        endpoint."

        Design: Corner/errors/missing_role_header_returns_unauthenticated
        """
        agreement_id = _auth_header_hotel(scenario)

        response = scenario.api.get_agreement(
            agreement_id, headers_with_role("u-mgr-1", UNDECLARED_ROLE)
        )

        # A role string outside the four declared roles never reaches the 403 check.
        assert_error_envelope(response, ApiErrorId.UNAUTHENTICATED)
        assert response.status_code == 401
        for headers in HEADERS_BY_ROLE.values():
            agreement = assert_object_envelope(
                scenario.api.get_agreement(agreement_id, headers), 200
            )
            assert agreement["status"] == AgreementStatus.ACTIVE


# ---------------------------------------------------------------------------
# Nine path segments, nine not-found codes
# ---------------------------------------------------------------------------


class TestUnknownIdsMapToEntitySpecificNotFound:
    def test_each_path_segment_carries_its_own_not_found_code(self, scenario):
        """PRD §2.8 rules 7-15: "The budget named in the path exists; otherwise
        `ERR_BUDGET_NOT_FOUND` (404)." And "The report package named in the path exists; otherwise
        `ERR_PACKAGE_NOT_FOUND` (404)." And "The variance request named in the path exists;
        otherwise `ERR_VARIANCE_NOT_FOUND` (404)." And "The centralized service charge named in the
        path exists; otherwise `ERR_CHARGE_NOT_FOUND` (404)." And "The distribution named in the
        path exists; otherwise `ERR_DISTRIBUTION_NOT_FOUND` (404)." And "The working capital call
        named in the path exists; otherwise `ERR_CALL_NOT_FOUND` (404)." And "The performance test
        named in the path exists; otherwise `ERR_TEST_NOT_FOUND` (404)." And "The brand standard
        dispute named in the path exists; otherwise `ERR_DISPUTE_NOT_FOUND` (404)." And "The
        employment claim named in the path exists; otherwise `ERR_CLAIM_NOT_FOUND` (404)."

        Design: Corner/errors/unknown_ids_map_to_entity_specific_not_found_errors
        """
        probes = [
            (
                scenario.api.get_budget(NON_EXISTENT_UUID, ASSET_HEADERS),
                ApiErrorId.BUDGET_NOT_FOUND,
            ),
            (
                scenario.api.get_report_package(NON_EXISTENT_UUID, ASSET_HEADERS),
                ApiErrorId.PACKAGE_NOT_FOUND,
            ),
            (
                scenario.api.decide_variance_request(
                    NON_EXISTENT_UUID,
                    variance_decision_payload(),
                    OWNER_HEADERS,
                ),
                ApiErrorId.VARIANCE_NOT_FOUND,
            ),
            (
                scenario.api.review_centralized_charge(
                    NON_EXISTENT_UUID, contest_payload(), ASSET_HEADERS
                ),
                ApiErrorId.CHARGE_NOT_FOUND,
            ),
            (
                scenario.api.execute_distribution(NON_EXISTENT_UUID, MANAGER_HEADERS),
                ApiErrorId.DISTRIBUTION_NOT_FOUND,
            ),
            (
                scenario.api.fund_working_capital_call(
                    NON_EXISTENT_UUID, fund_payload(500000), OWNER_HEADERS
                ),
                ApiErrorId.CALL_NOT_FOUND,
            ),
            (
                scenario.api.cure_performance_test(
                    NON_EXISTENT_UUID, elect_cure_payload(), MANAGER_HEADERS
                ),
                ApiErrorId.TEST_NOT_FOUND,
            ),
            (
                scenario.api.advance_brand_dispute(
                    NON_EXISTENT_UUID, owner_counter_payload(500000), OWNER_HEADERS
                ),
                ApiErrorId.DISPUTE_NOT_FOUND,
            ),
            (
                scenario.api.allocate_employment_claim(
                    NON_EXISTENT_UUID, claim_allocation_payload(), ASSET_HEADERS
                ),
                ApiErrorId.CLAIM_NOT_FOUND,
            ),
        ]

        for response, expected_error_id in probes:
            assert_error_envelope(response, expected_error_id)
            assert response.status_code == 404
        assert len({expected for _, expected in probes}) == 9

    def test_the_container_is_resolved_before_the_version_pin_is_checked(self, scenario):
        """PRD §2.8: "Path identifiers resolve left to right, so a nested identifier is looked up
        only after its container has been found, and the first identifier in the path that names
        nothing produces that container's own not-found error." And rule 6: "The agreement named in
        the path exists; otherwise `ERR_AGREEMENT_NOT_FOUND` (404). Applies to every endpoint
        beneath `/hotel-management/agreements/{id}`." And rule 17: "`expected_agreement_version`
        equals the agreement's current `version`; otherwise `ERR_STALE_AGREEMENT_VERSION` (412)."

        Design: Corner/errors/unknown_ids_map_to_entity_specific_not_found_errors
        """
        response = scenario.api.create_budget(
            NON_EXISTENT_UUID,
            budget_payload(
                99,
                fiscal_year=2026,
                budgeted_revenue_cents=300000000,
                budgeted_operating_expenses_cents=200000000,
            ),
            MANAGER_HEADERS,
        )

        # Rule 6 outranks rule 17, so the unknown container wins over the stale pin.
        assert_error_envelope(response, ApiErrorId.AGREEMENT_NOT_FOUND)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Four entities, four state codes
# ---------------------------------------------------------------------------


def _state_codes_hotel(scenario):
    """A DRAFT budget, an unsubmitted period, a FILED claim and an OPENED dispute."""
    agreement = scenario.register(
        hotel_name="State Codes Hotel",
        owner_entity_name="State Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    claim = scenario.claim(
        agreement["id"], position_class=PositionClass.GM, claim_amount_cents=3000000
    )
    dispute = scenario.dispute(
        agreement["id"],
        franchise_requirement_ref="BRAND-STD-SIGNAGE-2026",
        estimated_cost_cents=400000,
        remediation_start_utc="2026-09-01T00:00:00Z",
        remediation_deadline_utc="2026-12-01T00:00:00Z",
    )
    return {
        "agreement_id": agreement["id"],
        "budget_id": budget["id"],
        "package_id": package["id"],
        "claim_id": claim["id"],
        "dispute_id": dispute["id"],
    }


class TestInvalidStateErrorsAreDistinctPerEntity:
    def test_four_out_of_sequence_actions_report_four_different_codes(self, scenario):
        """PRD §2.8 rule 20: "The budget's `status` is one the requested transition declares as its
        origin; otherwise `ERR_INVALID_BUDGET_STATE` (409)." And rule 21: "The package's
        `financial_status` is one the requested financial transition declares as its origin;
        otherwise `ERR_INVALID_PACKAGE_STATE` (409)." And rule 28: "The claim's `status` is one the
        requested allocation action declares as its origin; otherwise `ERR_INVALID_CLAIM_STATE`
        (409)." And rule 27: "The dispute's `status` is one the requested round action declares as
        its origin; otherwise `ERR_INVALID_DISPUTE_STATE` (409)."

        Design: Corner/errors/invalid_state_errors_are_distinct_per_entity
        """
        state = _state_codes_hotel(scenario)

        on_budget = scenario.api.decide_budget(
            state["budget_id"], budget_decision_payload(BudgetDecision.APPROVE), OWNER_HEADERS
        )
        on_package = scenario.api.review_report_package(
            state["package_id"],
            owner_review_payload(ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT),
            OWNER_HEADERS,
        )
        on_claim = scenario.api.allocate_employment_claim(
            state["claim_id"], claim_allocation_payload(ClaimAction.REVERSE), ASSET_HEADERS
        )
        on_dispute = scenario.api.advance_brand_dispute(
            state["dispute_id"], owner_counter_payload(500000), OWNER_HEADERS
        )

        for response, expected_error_id in (
            (on_budget, ApiErrorId.INVALID_BUDGET_STATE),
            (on_package, ApiErrorId.INVALID_PACKAGE_STATE),
            (on_claim, ApiErrorId.INVALID_CLAIM_STATE),
            (on_dispute, ApiErrorId.INVALID_DISPUTE_STATE),
        ):
            assert_error_envelope(response, expected_error_id)
            assert response.status_code == 409

    def test_none_of_the_four_rejections_moved_its_row(self, scenario):
        """PRD §3.4: "A freshly opened package sits at `financial_status` `PENDING`,
        `benchmark_status` `PENDING` and `package_status` `INCOMPLETE`" PRD §3.10: "persists the
        claim in `FILED` with both `owner_share_cents` and `manager_share_cents` at zero." PRD §3.9:
        "The dispute opens in `OPENED` with `round` at 0, `current_cost_estimate_cents` seeded from
        `estimated_cost_cents`, `funding_source` null and `funded_amount_cents` at zero."

        Design: Corner/errors/invalid_state_errors_are_distinct_per_entity
        """
        state = _state_codes_hotel(scenario)
        scenario.api.decide_budget(
            state["budget_id"], budget_decision_payload(BudgetDecision.APPROVE), OWNER_HEADERS
        )
        scenario.api.review_report_package(
            state["package_id"],
            owner_review_payload(ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT),
            OWNER_HEADERS,
        )
        scenario.api.allocate_employment_claim(
            state["claim_id"], claim_allocation_payload(ClaimAction.REVERSE), ASSET_HEADERS
        )
        scenario.api.advance_brand_dispute(
            state["dispute_id"], owner_counter_payload(500000), OWNER_HEADERS
        )

        assert scenario.read_budget(state["budget_id"])["status"] == BudgetStatus.DRAFT
        assert scenario.read_package(state["package_id"])["financial_status"] == (
            FinancialStatus.PENDING
        )
        claim = scenario.claims(state["agreement_id"])[0]
        assert claim["status"] == ClaimStatus.FILED
        dispute = scenario.disputes(state["agreement_id"])[0]
        assert dispute["status"] == DisputeStatus.OPENED
        assert dispute["round"] == 0


# ---------------------------------------------------------------------------
# Children cannot attach to a DRAFT agreement
# ---------------------------------------------------------------------------


def _draft_guard_hotel(scenario):
    """One agreement created and deliberately never activated."""
    agreement = scenario.register(
        hotel_name="Draft Guard Hotel",
        owner_entity_name="Draft Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        initial_working_capital_cents=0,
        working_capital_floor_cents=0,
    )
    return agreement["id"]


class TestAgreementNotActiveGuardOnADraftAgreement:
    def test_unrelated_child_creations_share_one_refusal(self, scenario):
        """PRD §2.8 rule 18: "The agreement's `status` is `ACTIVE`; otherwise
        `ERR_AGREEMENT_NOT_ACTIVE` (409). Applies to twelve write operations" And "A `DRAFT`,
        `CURE_PERIOD`, `TERMINATION_NOTICED` or `TERMINATED` agreement fails this rule."

        Design: Corner/errors/agreement_not_active_guard_on_a_draft_agreement
        """
        agreement_id = _draft_guard_hotel(scenario)

        on_package = scenario.api.create_report_package(
            agreement_id,
            {
                "fiscal_year": 2026,
                "period_month": 9,
                "rooms_revenue_cents": 20000000,
                "fnb_revenue_cents": 5000000,
                "other_revenue_cents": 1000000,
                "operating_expenses_cents": 5000000,
                "closing_cash_available_cents": 0,
            },
            MANAGER_HEADERS,
        )
        on_call = scenario.api.create_working_capital_call(
            agreement_id,
            working_capital_call_payload(500000, CallReason.FLOOR_RESTORATION),
            MANAGER_HEADERS,
        )

        for response in (on_package, on_call):
            assert_error_envelope(response, ApiErrorId.AGREEMENT_NOT_ACTIVE)
            assert response.status_code == 409
        assert_page(
            scenario.api.list_working_capital_calls(agreement_id, ASSET_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_activation_lets_the_identical_call_through(self, scenario):
        """PRD §3.1: "It moves the agreement `DRAFT → ACTIVE`, writes
        `initial_working_capital_cents` into `working_capital_balance_cents` — this is the only
        moment the opening deposit is recognised — sets `distribution_hold` to false, and increments
        the agreement's `version` by one."

        Design: Corner/errors/agreement_not_active_guard_on_a_draft_agreement
        """
        agreement_id = _draft_guard_hotel(scenario)
        scenario.api.create_working_capital_call(
            agreement_id,
            working_capital_call_payload(500000, CallReason.FLOOR_RESTORATION),
            MANAGER_HEADERS,
        )

        activated = assert_object_envelope(
            scenario.api.activate_agreement(agreement_id, ADMIN_HEADERS), 200
        )
        created = assert_object_envelope(
            scenario.api.create_working_capital_call(
                agreement_id,
                working_capital_call_payload(500000, CallReason.FLOOR_RESTORATION),
                MANAGER_HEADERS,
            ),
            201,
        )

        assert activated["status"] == AgreementStatus.ACTIVE
        assert activated["version"] == 2
        assert created["status"] == CallStatus.REQUESTED
        assert created["amount_cents"] == 500000
