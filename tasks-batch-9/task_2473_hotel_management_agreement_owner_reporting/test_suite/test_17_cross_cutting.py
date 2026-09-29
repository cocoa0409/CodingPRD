"""Cross-cutting layers: the two version pins, the counter itself and the per-period cap."""

from test_helpers import (
    ASSET_HEADERS,
    AllocationBasis,
    ApiErrorId,
    BudgetDecision,
    FeeType,
    FeeVariant,
    MANAGER_HEADERS,
    OWNER_HEADERS,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    assert_error_envelope,
    assert_object_envelope,
    assert_page,
    budget_payload,
    charge_payload,
    true_up_payload,
)


# ---------------------------------------------------------------------------
# The budget-create version pin
# ---------------------------------------------------------------------------


def _stale_budget_hotel(scenario):
    """One ACTIVE agreement plus the version the client observed at activation."""
    agreement = scenario.register(
        hotel_name="Stale Budget Hotel",
        owner_entity_name="Stale Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    activated = scenario.activate(agreement["id"])
    return agreement["id"], activated["version"]


def _fy2027_body(version):
    """The same FY2027 revision body, differing only in the pinned version."""
    return budget_payload(
        version,
        fiscal_year=2027,
        budgeted_revenue_cents=320000000,
        budgeted_operating_expenses_cents=210000000,
    )


class TestBudgetCreateRejectsAStaleVersion:
    def test_the_first_create_consumes_the_version_the_second_replay_held(self, scenario):
        """PRD §2.6: "That request must carry `expected_agreement_version`, a non-optional integer
        holding the `version` of the `ManagementAgreement` as the client last observed it. If the
        value does not equal the agreement's current `version`, the create is rejected with
        `ERR_STALE_AGREEMENT_VERSION` (412)." PRD §3.2: "Separately, creating a revision increments
        the agreement's `version` by one."

        Design: Corner/cross-cutting complexity layers/budget_create_rejects_a_stale_expected_agreement_version
        """
        agreement_id, observed = _stale_budget_hotel(scenario)

        first = assert_object_envelope(
            scenario.api.create_budget(
                agreement_id,
                budget_payload(
                    observed,
                    fiscal_year=2026,
                    budgeted_revenue_cents=300000000,
                    budgeted_operating_expenses_cents=200000000,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        stale = scenario.api.create_budget(agreement_id, _fy2027_body(observed), MANAGER_HEADERS)

        assert first["fiscal_year"] == 2026
        assert scenario.agreement_version(agreement_id) == observed + 1
        assert_error_envelope(stale, ApiErrorId.STALE_AGREEMENT_VERSION)
        assert stale.status_code == 412
        assert_page(
            scenario.api.list_budgets(
                ASSET_HEADERS, {"agreement_id": agreement_id, "fiscal_year": 2027}
            ),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_only_exact_equality_passes_and_the_refreshed_pin_succeeds(self, scenario):
        """PRD §2.6: "If the value does not equal the agreement's current `version`, the create is
        rejected with `ERR_STALE_AGREEMENT_VERSION` (412)." PRD §2.8 rule 17:
        "`expected_agreement_version` equals the agreement's current `version`; otherwise
        `ERR_STALE_AGREEMENT_VERSION` (412)."

        Design: Corner/cross-cutting complexity layers/budget_create_rejects_a_stale_expected_agreement_version
        """
        agreement_id, observed = _stale_budget_hotel(scenario)
        scenario.budget(
            agreement_id,
            fiscal_year=2026,
            budgeted_revenue_cents=300000000,
            budgeted_operating_expenses_cents=200000000,
        )

        ahead = scenario.api.create_budget(
            agreement_id, _fy2027_body(observed + 99), MANAGER_HEADERS
        )
        refreshed = scenario.agreement_version(agreement_id)
        accepted = assert_object_envelope(
            scenario.api.create_budget(agreement_id, _fy2027_body(refreshed), MANAGER_HEADERS), 201
        )

        # A version ahead of the row is just as unequal as one behind it.
        assert_error_envelope(ahead, ApiErrorId.STALE_AGREEMENT_VERSION)
        assert ahead.status_code == 412
        assert refreshed == observed + 1
        assert accepted["fiscal_year"] == 2027


# ---------------------------------------------------------------------------
# The true-up version pin
# ---------------------------------------------------------------------------


def _stale_true_up_hotel(scenario):
    """One accepted period, with the version as read at activation kept deliberately stale."""
    agreement = scenario.register(
        hotel_name="Stale True Up Hotel",
        owner_entity_name="Stale TU Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
    )
    activated = scenario.activate(agreement["id"])
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
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "observed": activated["version"],
    }


def _final_incentive_rows(scenario, package_id):
    """The package's live FINAL incentive accrual page."""
    return scenario.api.list_fee_accruals(
        package_id, OWNER_HEADERS, {"fee_type": FeeType.INCENTIVE, "variant": FeeVariant.FINAL}
    )


class TestAnnualTrueUpRejectsAStaleVersion:
    def test_the_pre_budget_version_is_refused_and_posts_nothing(self, scenario):
        """PRD §2.6: "That request likewise must carry `expected_agreement_version` holding the
        client's last observed agreement `version`, and a mismatch with the agreement's current
        `version` is likewise rejected with `ERR_STALE_AGREEMENT_VERSION` (412)."

        Design: Corner/cross-cutting complexity layers/annual_true_up_rejects_a_stale_expected_agreement_version
        """
        state = _stale_true_up_hotel(scenario)

        stale = scenario.api.run_annual_true_up(
            state["agreement_id"], true_up_payload(state["observed"], 2026), MANAGER_HEADERS
        )

        assert_error_envelope(stale, ApiErrorId.STALE_AGREEMENT_VERSION)
        assert stale.status_code == 412
        assert_page(
            _final_incentive_rows(scenario, state["package_id"]),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_the_refreshed_pin_posts_the_final_accrual_exactly_once(self, scenario):
        """PRD §3.8: "The delta is posted as a new fee accrual with `fee_type` `INCENTIVE`,
        `variant` `FINAL` and `status` `ACCRUED`" And "any prior `FINAL` accrual of the same
        agreement and fiscal year is set to `REVERSED` first, so exactly one live `FINAL` accrual
        exists per fiscal year at any time."

        Design: Corner/cross-cutting complexity layers/annual_true_up_rejects_a_stale_expected_agreement_version
        """
        state = _stale_true_up_hotel(scenario)
        scenario.api.run_annual_true_up(
            state["agreement_id"], true_up_payload(state["observed"], 2026), MANAGER_HEADERS
        )

        refreshed = scenario.agreement_version(state["agreement_id"])
        summary = assert_object_envelope(
            scenario.api.run_annual_true_up(
                state["agreement_id"], true_up_payload(refreshed, 2026), MANAGER_HEADERS
            ),
            200,
        )

        assert summary["true_up_delta_cents"] == -939000
        assert summary["true_up_accrual_id"] is not None
        rows = assert_page(
            _final_incentive_rows(scenario, state["package_id"]),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["id"] == summary["true_up_accrual_id"]


# ---------------------------------------------------------------------------
# Which writes move the counter
# ---------------------------------------------------------------------------


def _version_walk_hotel(scenario):
    """A full monthly cycle driven over one agreement, with the opening version kept."""
    agreement = scenario.register(
        hotel_name="Version Walk Hotel",
        owner_entity_name="Walk Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
    )
    activated = scenario.activate(agreement["id"])
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
    return {
        "agreement_id": agreement["id"],
        "created_version": agreement["version"],
        "activated_version": activated["version"],
    }


class TestAgreementVersionIncrementsOnlyOnParentTouchingWrites:
    def test_the_intervening_child_writes_leave_the_counter_where_the_budget_left_it(
        self, scenario
    ):
        """PRD §2.3: "`version`, an integer that starts at 1 and increments by one on every
        mutation." PRD §2.6: "Submitting a budget, deciding a budget, filing a report package,
        posting a benchmark or a chargeback, reviewing a package, executing a distribution, funding
        a call, scoring a test, curing, terminating, advancing a dispute and allocating a claim all
        take no `expected_agreement_version` and perform no version comparison."

        Design: Corner/cross-cutting complexity layers/agreement_version_increments_only_on_parent_touching_writes
        """
        state = _version_walk_hotel(scenario)

        assert state["created_version"] == 1
        assert state["activated_version"] == 2
        # Activation and the budget create are the only version-advancing writes so far.
        assert scenario.agreement_version(state["agreement_id"]) == 3

    def test_the_true_up_advances_it_again_from_the_version_read_after_those_writes(self, scenario):
        """PRD §3.8: "Finally the agreement's `version` is incremented by one, which is precisely
        why the operation is version-pinned" PRD §2.3: "resources carry `created_at`, an ISO 8601
        UTC timestamp with three fractional digits recording when the row was first written."

        Design: Corner/cross-cutting complexity layers/agreement_version_increments_only_on_parent_touching_writes
        """
        state = _version_walk_hotel(scenario)
        observed = scenario.agreement_version(state["agreement_id"])

        assert_object_envelope(
            scenario.api.run_annual_true_up(
                state["agreement_id"], true_up_payload(observed, 2026), MANAGER_HEADERS
            ),
            200,
        )

        agreement = assert_object_envelope(
            scenario.api.get_agreement(state["agreement_id"], ASSET_HEADERS), 200
        )
        assert agreement["version"] == observed + 1 == 4
        assert agreement["created_at"]
        assert agreement["updated_at"]


# ---------------------------------------------------------------------------
# The cap is a per-period ceiling
# ---------------------------------------------------------------------------


def _cap_reset_hotels(scenario):
    """Two adjacent periods, each with gross revenue 26000000 and a 390000 cap."""
    agreement = scenario.register(
        hotel_name="Cap Reset Hotel",
        owner_entity_name="Cap Owner LLC",
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
    september = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    october = scenario.package(agreement["id"], fiscal_year=2026, period_month=10)
    return {"september_id": september["id"], "october_id": october["id"]}


def _revenue_charge(service_code, pool_amount_cents, **overrides):
    """A gross-revenue-based chargeback taking a five percent hotel share."""
    return charge_payload(
        service_code=service_code,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=pool_amount_cents,
        hotel_basis_share=0.05,
        **overrides,
    )


class TestCentralizedCapResetsForEachReportingPeriod:
    def test_each_period_absorbs_its_own_charge_under_its_own_ceiling(self, scenario):
        """PRD §3.4: "The period cap is the package's `gross_revenue_cents` multiplied by the
        agreement's `centralized_services_cap_pct` and floored to whole cents." And "with
        `ERR_CENTRALIZED_CAP_EXCEEDED` whenever cumulative `requested_amount_cents` across the
        package including the incoming charge would exceed the period cap, and nothing at all is
        persisted."

        Design: Corner/cross-cutting complexity layers/centralized_cap_resets_for_each_reporting_period
        """
        state = _cap_reset_hotels(scenario)

        september = assert_object_envelope(
            scenario.api.create_centralized_charge(
                state["september_id"],
                _revenue_charge(ServiceCode.RESERVATIONS, 6000000),
                MANAGER_HEADERS,
            ),
            201,
        )
        october = assert_object_envelope(
            scenario.api.create_centralized_charge(
                state["october_id"],
                _revenue_charge(ServiceCode.RESERVATIONS, 6000000),
                MANAGER_HEADERS,
            ),
            201,
        )
        refused = scenario.api.create_centralized_charge(
            state["september_id"],
            _revenue_charge(ServiceCode.REVENUE_MANAGEMENT, 2000000),
            MANAGER_HEADERS,
        )

        for charge in (september, october):
            assert charge["allocated_amount_cents"] == 300000
            assert charge["deferred_amount_cents"] == 0
        # 300000 already booked plus 100000 requested overruns the 390000 period ceiling.
        assert_error_envelope(refused, ApiErrorId.CENTRALIZED_CAP_EXCEEDED)
        assert refused.status_code == 422

    def test_the_ceiling_never_carries_across_the_two_periods(self, scenario):
        """PRD §3.4: "the charge is persisted with its `allocated_amount_cents` truncated to
        whatever cap remainder was left and `deferred_amount_cents` carrying the rest." And "Each
        charge's `requested_amount_cents` is its `pool_amount_cents` multiplied by its
        `hotel_basis_share`, rounded half up to whole cents." And "the package's
        `allocated_centralized_cents`
        is set to the sum of the allocated amounts across all its charges."

        Design: Corner/cross-cutting complexity layers/centralized_cap_resets_for_each_reporting_period
        """
        state = _cap_reset_hotels(scenario)
        scenario.api.create_centralized_charge(
            state["september_id"],
            _revenue_charge(ServiceCode.RESERVATIONS, 6000000),
            MANAGER_HEADERS,
        )
        scenario.api.create_centralized_charge(
            state["october_id"],
            _revenue_charge(ServiceCode.RESERVATIONS, 6000000),
            MANAGER_HEADERS,
        )

        deferred = assert_object_envelope(
            scenario.api.create_centralized_charge(
                state["september_id"],
                _revenue_charge(
                    ServiceCode.REVENUE_MANAGEMENT,
                    2000000,
                    allow_deferral=True,
                    supporting_detail_provided=True,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        exhausted = scenario.api.create_centralized_charge(
            state["september_id"],
            _revenue_charge(ServiceCode.IT_HOSTING, 1800000),
            MANAGER_HEADERS,
        )
        october_before = scenario.read_package(state["october_id"])["allocated_centralized_cents"]
        headroom = assert_object_envelope(
            scenario.api.create_centralized_charge(
                state["october_id"],
                _revenue_charge(ServiceCode.IT_HOSTING, 1800000),
                MANAGER_HEADERS,
            ),
            201,
        )

        assert deferred["requested_amount_cents"] == 100000
        assert deferred["allocated_amount_cents"] == 90000
        assert deferred["deferred_amount_cents"] == 10000
        assert_error_envelope(exhausted, ApiErrorId.CENTRALIZED_CAP_EXCEEDED)
        assert exhausted.status_code == 422
        # October's own 90000 of headroom is untouched by September's exhausted ceiling.
        assert october_before == 300000
        assert headroom["allocated_amount_cents"] == 90000
        assert headroom["deferred_amount_cents"] == 0
        assert scenario.read_package(state["september_id"])["allocated_centralized_cents"] == 390000
        assert scenario.read_package(state["october_id"])["allocated_centralized_cents"] == 390000
