"""Exact-boundary and tie-break arithmetic: one cent either side, and one half cent."""

from test_helpers import (
    AllocationBasis,
    ApiErrorId,
    BudgetDecision,
    DisclosureStatus,
    FeeType,
    FeeVariant,
    MANAGER_HEADERS,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    assert_error_envelope,
    assert_object_envelope,
    assert_page,
    charge_payload,
    find_accrual,
    rows_where,
)


# ---------------------------------------------------------------------------
# The aggregate period cap, one cent either side
# ---------------------------------------------------------------------------


def _cap_boundary_hotel(scenario):
    """A period whose cap is exactly 825000, with 325000 of headroom left."""
    agreement = scenario.register(
        hotel_name="Cap Boundary Hotel",
        owner_entity_name="Exact Cap Owner LLC",
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
    scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


def _fill_the_cap_exactly(scenario, package_id):
    """A second charge of exactly the 325000 that remains."""
    return scenario.api.create_centralized_charge(
        package_id,
        charge_payload(
            service_code=ServiceCode.REVENUE_MANAGEMENT,
            allocation_basis=AllocationBasis.ROOMS_AVAILABLE,
            pool_amount_cents=6500000,
            hotel_basis_share=0.05,
        ),
        MANAGER_HEADERS,
    )


def _one_cent_over(scenario, package_id, **overrides):
    """A single-cent charge posted once the cap is already exhausted."""
    return scenario.api.create_centralized_charge(
        package_id,
        charge_payload(
            service_code=ServiceCode.IT_HOSTING,
            allocation_basis=AllocationBasis.FLAT,
            pool_amount_cents=20,
            hotel_basis_share=0.05,
            **overrides,
        ),
        MANAGER_HEADERS,
    )


class TestCentralizedCapExactHit:
    def test_cumulative_requested_landing_on_the_cap_is_accepted(self, scenario):
        """PRD §2.8 rule 44: "Cumulative `requested_amount_cents` across the package's
        charges, including the incoming one, is at most the period cap — the floor of the
        package's `gross_revenue_cents` multiplied by the agreement's
        `centralized_services_cap_pct` — whenever the incoming charge carries
        `allow_deferral` false; otherwise `ERR_CENTRALIZED_CAP_EXCEEDED` (422)."

        Design: Difficulty/boundary_precision_check/centralized_cap_exact_hit_versus_one_cent_over
        """
        state = _cap_boundary_hotel(scenario)

        charge = assert_object_envelope(_fill_the_cap_exactly(scenario, state["package_id"]), 201)

        # 500000 already spent plus 325000 is exactly floor(55000025 * 0.015).
        assert charge["requested_amount_cents"] == 325000
        assert charge["allocated_amount_cents"] == 325000
        assert charge["deferred_amount_cents"] == 0
        assert charge["disclosure_status"] == DisclosureStatus.DISCLOSED

    def test_one_cent_beyond_the_cap_is_refused_and_persists_nothing(self, scenario):
        """PRD §3.5: "whenever cumulative `requested_amount_cents` across the package
        including the incoming charge would exceed the period cap, and nothing at all is
        persisted."

        Design: Difficulty/boundary_precision_check/centralized_cap_exact_hit_versus_one_cent_over
        """
        state = _cap_boundary_hotel(scenario)
        _fill_the_cap_exactly(scenario, state["package_id"])

        response = _one_cent_over(scenario, state["package_id"])

        assert_error_envelope(response, ApiErrorId.CENTRALIZED_CAP_EXCEEDED)
        assert response.status_code == 422
        assert_page(
            scenario.api.list_centralized_charges(state["package_id"], MANAGER_HEADERS),
            expected_rows=2,
            total_count=2,
            has_more=False,
        )

    def test_the_same_cent_is_accepted_once_deferral_is_permitted(self, scenario):
        """PRD §3.5: "What happens when the cap is breached depends entirely on the incoming
        charge's `allow_deferral` flag, and the two behaviours are mutually exclusive." and
        "the charge is persisted with its `allocated_amount_cents` truncated to whatever cap
        remainder was left and `deferred_amount_cents` carrying the rest."

        Design: Difficulty/boundary_precision_check/centralized_cap_exact_hit_versus_one_cent_over
        """
        state = _cap_boundary_hotel(scenario)
        _fill_the_cap_exactly(scenario, state["package_id"])
        _one_cent_over(scenario, state["package_id"])

        deferred = assert_object_envelope(
            _one_cent_over(
                scenario,
                state["package_id"],
                allow_deferral=True,
                supporting_detail_provided=True,
            ),
            201,
        )

        assert deferred["requested_amount_cents"] == 1
        assert deferred["allocated_amount_cents"] == 0
        assert deferred["deferred_amount_cents"] == 1
        assert scenario.read_package(state["package_id"])["allocated_centralized_cents"] == 825000
        assert_page(
            scenario.api.list_centralized_charges(state["package_id"], MANAGER_HEADERS),
            expected_rows=3,
            total_count=3,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# Exact half-cent ties inside the incentive formulas
# ---------------------------------------------------------------------------


def _half_cent_tie_hotel(scenario):
    """A period whose profit puts both incentive legs on an exact half cent."""
    agreement = scenario.register(
        hotel_name="Half Cent Tie Hotel",
        owner_entity_name="Half Up Owner LP",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        incentive_tier2_pct=0.15,
        incentive_tier2_threshold_cents=5000000,
        owner_priority_cents=12000000,
        centralized_services_cap_pct=0.015,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
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
    scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestIncentiveHalfCentTies:
    def test_the_monthly_tie_moves_away_from_zero(self, scenario):
        """PRD §2.5: "takes the absolute value of the quantity, adds one half, discards the
        fractional part, and re-applies the original sign; a value of exactly one half cent
        therefore moves away from zero." and "Fees are always rounded half up."

        Design: Difficulty/boundary_precision_check/incentive_fee_exact_half_cent_tie_rounds_half_up
        """
        state = _half_cent_tie_hotel(scenario)

        package = scenario.read_package(state["package_id"])

        assert package["agop_cents"] == 22712525
        # (22712525 - 1000000) * 0.10 is exactly 2171252.50.
        assert package["incentive_fee_provisional_cents"] == 2171253
        assert package["incentive_fee_provisional_cents"] != 2171252
        # No line-level tie arises at 0.0325 on these three revenue lines.
        assert package["base_fee_cents"] == 1787500

    def test_the_annual_second_tier_tie_moves_away_from_zero(self, scenario):
        """PRD §3.8: "Each tier is rounded on its own and the two rounded products are then
        added; the excess is never multiplied by a blended rate."

        Design: Difficulty/boundary_precision_check/incentive_fee_exact_half_cent_tie_rounds_half_up
        """
        state = _half_cent_tie_hotel(scenario)

        summary = scenario.true_up(state["agreement_id"], 2026)

        assert summary["annual_agop_cents"] == 22712525
        # The 5712525 second-tier base at 0.15 is exactly 856878.75.
        assert summary["final_incentive_fee_cents"] == 1356879
        assert summary["final_incentive_fee_cents"] != 1356878

    def test_the_settlement_accrual_carries_the_half_up_delta(self, scenario):
        """PRD §3.8: "The settlement figure `true_up_delta_cents` is
        `final_incentive_fee_cents` less `provisional_incentive_total_cents`, and it is
        signed"

        Design: Difficulty/boundary_precision_check/incentive_fee_exact_half_cent_tie_rounds_half_up
        """
        state = _half_cent_tie_hotel(scenario)

        summary = scenario.true_up(state["agreement_id"], 2026)

        assert summary["provisional_incentive_total_cents"] == 2171253
        assert summary["true_up_delta_cents"] == -814374
        accrual = find_accrual(
            scenario.accruals(state["package_id"]), FeeType.INCENTIVE, FeeVariant.FINAL
        )
        assert accrual["id"] == summary["true_up_accrual_id"]
        assert accrual["amount_cents"] == -814374


# ---------------------------------------------------------------------------
# The zero-cardinality boundary: an empty accepted-period set
# ---------------------------------------------------------------------------


def _empty_set_hotel(scenario):
    """One FY2026 period frozen but never accepted, so the eligible set is empty."""
    agreement = scenario.register(
        hotel_name="Empty Set Hotel",
        owner_entity_name="Zero Period Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        incentive_tier2_pct=0.15,
        incentive_tier2_threshold_cents=5000000,
        owner_priority_cents=12000000,
        centralized_services_cap_pct=0.015,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
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
    scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


def _run_true_up(scenario, agreement_id):
    return scenario.api.run_annual_true_up(
        agreement_id,
        {
            "fiscal_year": 2026,
            "expected_agreement_version": scenario.agreement_version(agreement_id),
        },
        MANAGER_HEADERS,
    )


class TestTrueUpOnAnEmptyAcceptedSet:
    def test_a_fiscal_year_with_no_accepted_period_is_refused(self, scenario):
        """PRD §3.8: "The eligible periods are that agreement's report packages whose
        `fiscal_year` matches the request and whose `financial_status` is `ACCEPTED`. Periods
        in `DISPUTED`, `SUBMITTED` and `PENDING` are all excluded, and a fiscal year with no
        accepted period is refused with `ERR_NO_ACCEPTED_PERIODS`."

        Design: Difficulty/boundary_precision_check/annual_true_up_on_empty_accepted_period_set_rejected
        """
        state = _empty_set_hotel(scenario)

        response = _run_true_up(scenario, state["agreement_id"])

        assert_error_envelope(response, ApiErrorId.NO_ACCEPTED_PERIODS)
        assert response.status_code == 422

    def test_the_refused_run_posts_no_final_accrual(self, scenario):
        """PRD §3.8: "The delta is posted as a new fee accrual with `fee_type` `INCENTIVE`,
        `variant` `FINAL` and `status` `ACCRUED`, attached to the accepted period with the
        highest `period_month`"

        Design: Difficulty/boundary_precision_check/annual_true_up_on_empty_accepted_period_set_rejected
        """
        state = _empty_set_hotel(scenario)

        _run_true_up(scenario, state["agreement_id"])

        accruals = scenario.accruals(state["package_id"])
        assert rows_where(accruals, variant=FeeVariant.FINAL) == []

    def test_one_accepted_period_lifts_the_count_from_zero_to_one(self, scenario):
        """PRD §3.8: "Their count is reported as `accepted_period_count` and
        `annual_agop_cents` is the sum of `agop_cents` over them — a sum in which a negative
        month genuinely reduces the annual total."

        Design: Difficulty/boundary_precision_check/annual_true_up_on_empty_accepted_period_set_rejected
        """
        state = _empty_set_hotel(scenario)
        _run_true_up(scenario, state["agreement_id"])

        scenario.review_package(
            state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT
        )
        summary = assert_object_envelope(_run_true_up(scenario, state["agreement_id"]), 200)

        assert summary["accepted_period_count"] == 1
        assert summary["annual_agop_cents"] == 22712525
        assert summary["final_incentive_fee_cents"] == 1356879
        assert summary["provisional_incentive_total_cents"] == 2171253
        assert summary["true_up_delta_cents"] == -814374
        accrual = find_accrual(
            scenario.accruals(state["package_id"]), FeeType.INCENTIVE, FeeVariant.FINAL
        )
        assert accrual["id"] == summary["true_up_accrual_id"]
        assert accrual["amount_cents"] == -814374
