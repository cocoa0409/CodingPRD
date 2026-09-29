"""Role boundaries: endpoint lists, per-action splits, per-row ceilings and open reads."""

from test_helpers import (
    ASSET_HEADERS,
    ASSET_USER_ID,
    AccrualStatus,
    AllocationBasis,
    ApiErrorId,
    ApprovalLevel,
    BudgetDecision,
    BudgetStatus,
    DisclosureStatus,
    FeeType,
    FeeVariant,
    HEADERS_BY_ROLE,
    MANAGER_HEADERS,
    OWNER_ALT_HEADERS,
    OWNER_ALT_USER_ID,
    OWNER_HEADERS,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    VarianceCategory,
    VarianceStatus,
    adjust_payload,
    agreement_payload,
    assert_error_envelope,
    assert_object_envelope,
    assert_page,
    assert_variance_pct,
    brand_dispute_payload,
    budget_decision_payload,
    budget_payload,
    contest_payload,
    find_accrual,
    reaffirm_payload,
    true_up_payload,
    variance_decision_payload,
)


# ---------------------------------------------------------------------------
# The true-up is a manager-only computation
# ---------------------------------------------------------------------------


def _true_up_role_hotel(scenario):
    """One accepted period ready to be trued up."""
    agreement = scenario.register(
        hotel_name="True Up Role Hotel",
        owner_entity_name="Role Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)
    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestAnnualTrueUpByTheOwnerRepIsForbidden:
    def test_the_owner_side_is_refused_on_the_endpoint_role_list(self, scenario):
        """PRD §2.8 rule 2: "The acting role appears in the endpoint's authorized-roles list;
        otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint." PRD §3.8: "A
        `HotelManagerOps` actor runs it against an `ACTIVE` agreement for a named `fiscal_year`,
        pinning the agreement with `expected_agreement_version`."

        Design: Corner/rbac/annual_true_up_by_the_owner_rep_is_forbidden
        """
        state = _true_up_role_hotel(scenario)
        version = scenario.agreement_version(state["agreement_id"])

        response = scenario.api.run_annual_true_up(
            state["agreement_id"], true_up_payload(version, 2026), OWNER_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.UNAUTHORIZED)
        assert response.status_code == 403
        assert_page(
            scenario.api.list_fee_accruals(
                state["package_id"],
                OWNER_HEADERS,
                {"fee_type": FeeType.INCENTIVE, "variant": FeeVariant.FINAL},
            ),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )
        assert scenario.agreement_version(state["agreement_id"]) == version

    def test_the_manager_runs_the_identical_body_and_the_owner_reads_the_result(self, scenario):
        """PRD §3.8: "The delta is posted as a new fee accrual with `fee_type` `INCENTIVE`,
        `variant` `FINAL` and `status` `ACCRUED`" PRD §2.9: "Each period's fee accruals, its
        calculated distributions, and each agreement's reserve ledger can all be listed by any of
        the four roles."

        Design: Corner/rbac/annual_true_up_by_the_owner_rep_is_forbidden
        """
        state = _true_up_role_hotel(scenario)
        version = scenario.agreement_version(state["agreement_id"])
        scenario.api.run_annual_true_up(
            state["agreement_id"], true_up_payload(version, 2026), OWNER_HEADERS
        )

        summary = assert_object_envelope(
            scenario.api.run_annual_true_up(
                state["agreement_id"], true_up_payload(version, 2026), MANAGER_HEADERS
            ),
            200,
        )

        assert summary["final_incentive_fee_cents"] == 983000
        assert summary["true_up_delta_cents"] == -939000
        rows = assert_page(
            scenario.api.list_fee_accruals(
                state["package_id"],
                OWNER_HEADERS,
                {"fee_type": FeeType.INCENTIVE, "variant": FeeVariant.FINAL},
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["status"] == AccrualStatus.ACCRUED
        assert rows[0]["amount_cents"] == -939000


# ---------------------------------------------------------------------------
# Five writes, five roles that do not hold them
# ---------------------------------------------------------------------------


def _role_sweep_hotel(scenario):
    """An ACTIVE agreement holding one SUBMITTED FY2026 budget."""
    agreement = scenario.register(
        hotel_name="Role Sweep Hotel",
        owner_entity_name="Sweep Owner LLC",
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
    scenario.submit_budget(budget["id"])
    return {"agreement_id": agreement["id"], "budget_id": budget["id"]}


def _rogue_writes(scenario, state, version):
    """Each write attempted by an authentic role the endpoint does not list."""
    return [
        scenario.api.create_agreement(
            agreement_payload(
                hotel_name="Rogue Hotel",
                owner_entity_name="Rogue Owner LLC",
                base_fee_pct=0.03,
                incentive_fee_pct=0.10,
                owner_priority_cents=12000000,
            ),
            MANAGER_HEADERS,
        ),
        scenario.api.create_budget(
            state["agreement_id"],
            budget_payload(
                version,
                fiscal_year=2027,
                budgeted_revenue_cents=320000000,
                budgeted_operating_expenses_cents=210000000,
            ),
            OWNER_HEADERS,
        ),
        scenario.api.decide_budget(
            state["budget_id"], budget_decision_payload(BudgetDecision.APPROVE), ASSET_HEADERS
        ),
        scenario.api.create_brand_dispute(
            state["agreement_id"],
            brand_dispute_payload(
                franchise_requirement_ref="BRAND-STD-ROGUE",
                estimated_cost_cents=400000,
                remediation_start_utc="2026-09-01T00:00:00Z",
                remediation_deadline_utc="2026-12-01T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        scenario.api.set_clock("2026-09-01T00:00:00Z", OWNER_HEADERS),
    ]


class TestWriteEndpointsRejectUnlistedRoles:
    def test_all_five_unlisted_roles_are_refused_with_the_same_code(self, scenario):
        """PRD §2.8 rule 2: "The acting role appears in the endpoint's authorized-roles list;
        otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint." PRD §2.8 rule 3: "The body
        carries every required field with its declared type; otherwise `ERR_INVALID_REQUEST` (400).
        Applies to every POST endpoint."

        Design: Corner/rbac/write_endpoints_reject_every_role_outside_their_declared_set_unauthorized
        """
        state = _role_sweep_hotel(scenario)
        version = scenario.agreement_version(state["agreement_id"])

        responses = _rogue_writes(scenario, state, version)

        for response in responses:
            assert_error_envelope(response, ApiErrorId.UNAUTHORIZED)
            assert response.status_code == 403

    def test_none_of_the_refusals_left_a_trace(self, scenario):
        """PRD §2.6: "If the value does not equal the agreement's current `version`, the create is
        rejected with `ERR_STALE_AGREEMENT_VERSION` (412)." PRD §2.4: "Before any client sets it,
        the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/rbac/write_endpoints_reject_every_role_outside_their_declared_set_unauthorized
        """
        state = _role_sweep_hotel(scenario)
        version = scenario.agreement_version(state["agreement_id"])
        _rogue_writes(scenario, state, version)

        assert_page(
            scenario.api.list_budgets(ASSET_HEADERS, {"agreement_id": state["agreement_id"]}),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        budget = scenario.read_budget(state["budget_id"])
        # The refused clock write never ran a sweep, so no deemed approval landed.
        assert budget["status"] == BudgetStatus.SUBMITTED
        assert budget["decided_by_user_id"] is None
        assert_page(
            scenario.api.list_brand_disputes(state["agreement_id"], ASSET_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )
        # A 403 never advances the concurrency counter.
        assert scenario.agreement_version(state["agreement_id"]) == version


# ---------------------------------------------------------------------------
# One endpoint, two roles, actions split by side
# ---------------------------------------------------------------------------


def _action_split_hotel(scenario):
    """A submitted period carrying one DISCLOSED 300000 reservations charge."""
    agreement = scenario.register(
        hotel_name="Action Split Hotel",
        owner_entity_name="Split Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        centralized_services_cap_pct=0.015,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)
    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    charge = scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=6000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    return {"package_id": package["id"], "charge_id": charge["id"]}


class TestChargeReviewActionsAreSplitBySide:
    def test_the_manager_cannot_contest_its_own_chargeback(self, scenario):
        """PRD §2.8 rule 32: "The `action` requested on a multi-action endpoint is permitted for the
        acting role; otherwise `ERR_ACTION_ROLE_MISMATCH` (403)." PRD §3.5: "An `AssetManager`
        contests a charge, moving its `disclosure_status` `DISCLOSED → CONTESTED`" And "The contest
        has teeth: the parent package's `CENTRALIZED_SERVICES` fee accrual, if it sits in `ACCRUED`
        or `INVOICED`, is moved to `DISPUTED_HELD`"

        Design: Corner/rbac/charge_review_contest_by_the_manager_is_an_action_role_mismatch
        """
        state = _action_split_hotel(scenario)

        refused = scenario.api.review_centralized_charge(
            state["charge_id"],
            contest_payload(note="manager contesting its own allocation"),
            MANAGER_HEADERS,
        )
        contested = assert_object_envelope(
            scenario.api.review_centralized_charge(
                state["charge_id"],
                contest_payload(note="owner contests the reservation pool basis"),
                ASSET_HEADERS,
            ),
            200,
        )

        # The role is listed on the endpoint, so this is a mismatch and not ERR_UNAUTHORIZED.
        assert_error_envelope(refused, ApiErrorId.ACTION_ROLE_MISMATCH)
        assert refused.status_code == 403
        assert contested["disclosure_status"] == DisclosureStatus.CONTESTED
        held = find_accrual(
            scenario.accruals(state["package_id"]),
            FeeType.CENTRALIZED_SERVICES,
            FeeVariant.PROVISIONAL,
        )
        assert held["status"] == AccrualStatus.DISPUTED_HELD

    def test_the_owner_side_cannot_restate_the_allocation_the_manager_reaffirms(self, scenario):
        """PRD §3.5: "The manager answers in one of two ways, and both belong to
        `HotelManagerOps`." And "it returns to `ACCRUED` when the package's `financial_status` is
        `SUBMITTED`, or to `INVOICED` when the package's `financial_status` is `ACCEPTED`, with its
        `amount_cents` rewritten to the charge's post-review allocated amount."

        Design: Corner/rbac/charge_review_contest_by_the_manager_is_an_action_role_mismatch
        """
        state = _action_split_hotel(scenario)
        scenario.contest_charge(state["charge_id"])

        refused = scenario.api.review_centralized_charge(
            state["charge_id"], adjust_payload(250000), ASSET_HEADERS
        )
        reaffirmed = assert_object_envelope(
            scenario.api.review_centralized_charge(
                state["charge_id"], reaffirm_payload(note="basis stands"), MANAGER_HEADERS
            ),
            200,
        )

        assert_error_envelope(refused, ApiErrorId.ACTION_ROLE_MISMATCH)
        assert refused.status_code == 403
        assert reaffirmed["disclosure_status"] == DisclosureStatus.DISCLOSED
        assert reaffirmed["allocated_amount_cents"] == 300000
        released = find_accrual(
            scenario.accruals(state["package_id"]),
            FeeType.CENTRALIZED_SERVICES,
            FeeVariant.PROVISIONAL,
        )
        assert released["status"] == AccrualStatus.ACCRUED
        assert released["amount_cents"] == 300000


# ---------------------------------------------------------------------------
# Approval authority is a per-row ceiling
# ---------------------------------------------------------------------------


def _authority_hotel(scenario):
    """An approved 200000000 operating line carrying one OWNER_REP-level request."""
    agreement = scenario.register(
        hotel_name="Authority Hotel",
        owner_entity_name="Authority Owner LLC",
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
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)
    variance = scenario.variance(
        budget["id"],
        category=VarianceCategory.OPERATING,
        requested_amount_cents=60000000,
        justification="full-floor guestroom soft goods overrun",
    )
    return {"budget_id": budget["id"], "variance_id": variance["id"], "variance": variance}


class TestApprovalAuthorityCeiling:
    def test_the_asset_manager_cannot_sign_an_owner_rep_tier_request(self, scenario):
        """PRD §3.3: "Everything else, whether by ratio or by absolute size, is routed to
        `OWNER_REP`." And "the acting role's authority must cover the row's `approval_level` —
        `AssetManager` covers `ASSET_MANAGER` only, while `OwnerRep` covers both `ASSET_MANAGER` and
        `OWNER_REP`. An `AssetManager` deciding an `OWNER_REP`-tier request is refused with
        `ERR_APPROVAL_AUTHORITY_INSUFFICIENT`."

        Design: Corner/rbac/asset_manager_cannot_approve_an_owner_rep_level_variance
        """
        state = _authority_hotel(scenario)
        assert state["variance"]["effective_baseline_cents"] == 200000000
        assert_variance_pct(state["variance"]["variance_pct"], 0.300000)
        assert state["variance"]["approval_level"] == ApprovalLevel.OWNER_REP
        assert state["variance"]["status"] == VarianceStatus.PENDING

        refused = scenario.api.decide_variance_request(
            state["variance_id"],
            variance_decision_payload(
                BudgetDecision.APPROVE, note="asset manager signing above its ceiling"
            ),
            ASSET_HEADERS,
        )

        assert_error_envelope(refused, ApiErrorId.APPROVAL_AUTHORITY_INSUFFICIENT)
        assert refused.status_code == 403
        pending = scenario.variances(state["budget_id"])[0]
        assert pending["status"] == VarianceStatus.PENDING
        assert pending["decided_by_user_id"] is None
        approved = assert_object_envelope(
            scenario.api.decide_variance_request(
                state["variance_id"],
                variance_decision_payload(BudgetDecision.APPROVE, note="owner rep approves"),
                OWNER_ALT_HEADERS,
            ),
            200,
        )
        assert approved["status"] == VarianceStatus.APPROVED
        assert approved["decided_by_user_id"] == OWNER_ALT_USER_ID

    def test_the_ceiling_runs_one_way_so_the_lower_tier_admits_both_roles(self, scenario):
        """PRD §3.3: "Failing that, a request whose `variance_pct` is at most 0.15 and whose
        `requested_amount_cents` is at most 25,000,000 cents — a quarter of a million dollars — is
        routed to `ASSET_MANAGER`." And "Both outcomes — `PENDING → APPROVED` and
        `PENDING → DENIED` — record `decided_by_user_id` as the acting `X-User-ID` and nothing
        else"

        Design: Corner/rbac/asset_manager_cannot_approve_an_owner_rep_level_variance
        """
        state = _authority_hotel(scenario)
        lower = scenario.variance(
            state["budget_id"],
            category=VarianceCategory.OPERATING,
            requested_amount_cents=20000000,
            justification="ballroom carpet replacement",
        )

        assert lower["approval_level"] == ApprovalLevel.ASSET_MANAGER
        assert lower["status"] == VarianceStatus.PENDING
        decided = assert_object_envelope(
            scenario.api.decide_variance_request(
                lower["id"],
                variance_decision_payload(BudgetDecision.APPROVE),
                ASSET_HEADERS,
            ),
            200,
        )
        assert decided["status"] == VarianceStatus.APPROVED
        assert decided["decided_by_user_id"] == ASSET_USER_ID


# ---------------------------------------------------------------------------
# Reads are open to everybody
# ---------------------------------------------------------------------------


def _open_reads_hotel(scenario):
    """One ACTIVE agreement holding a single DRAFT FY2026 budget."""
    agreement = scenario.register(
        hotel_name="Open Reads Hotel",
        owner_entity_name="Reads Owner LLC",
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
    return {"agreement_id": agreement["id"], "budget_id": budget["id"]}


class TestEveryReadEndpointAdmitsAllFourRoles:
    def test_the_same_list_returns_an_identical_body_to_all_four_roles(self, scenario):
        """PRD §4: "`GET` | `/hotel-management/budgets` | List budget revisions, filterable by
        agreement, superseded target, fiscal year and status | `PlatformAdmin`, `HotelManagerOps`,
        `AssetManager`, `OwnerRep`"

        Design: Corner/rbac/every_read_endpoint_admits_all_four_roles
        """
        state = _open_reads_hotel(scenario)

        bodies = []
        for headers in HEADERS_BY_ROLE.values():
            rows = assert_page(
                scenario.api.list_budgets(headers, {"agreement_id": state["agreement_id"]}),
                expected_rows=1,
                total_count=1,
                has_more=False,
            )
            bodies.append(rows)

        assert len(bodies) == 4
        for rows in bodies:
            assert rows[0]["id"] == state["budget_id"]
            # No role receives a redacted projection: the field set is identical.
            assert set(rows[0]) == set(bodies[0][0])
            assert rows[0] == bodies[0][0]

    def test_the_detail_read_is_unscoped_by_the_acting_identity(self, scenario):
        """PRD §2.2: "Those recorded values are used only for the segregation-of-duties comparison
        described below; they are never resolved to a user record." PRD §3.2: "The budgeted adjusted
        gross operating profit, `budgeted_agop_cents`, is the budgeted gross revenue less the
        budgeted operating expenses, less the budgeted base fee, less the budgeted centralized
        charge."

        Design: Corner/rbac/every_read_endpoint_admits_all_four_roles
        """
        state = _open_reads_hotel(scenario)

        budget = assert_object_envelope(
            scenario.api.get_budget(state["budget_id"], OWNER_HEADERS), 200
        )

        assert budget["status"] == BudgetStatus.DRAFT
        assert budget["budgeted_agop_cents"] == 86500000
        assert budget["revision_round"] == 0
