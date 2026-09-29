"""Reserve study adequacy: the two funding methods and the empty funded set."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ADEQUACY_ADEQUATE,
    ADEQUACY_DEFICIENT,
    ADEQUACY_UNDETERMINED,
    ERR_ADEQUACY_NOT_EVALUATED,
    FUNDING_METHOD_CASH_FLOW,
    FUNDING_METHOD_COMPONENT_FULL_FUNDING,
    STUDY_ACTION_ADOPT,
    STUDY_ACTION_RECOMPUTE,
    ApiClient,
    assert_pct,
    assert_study_evaluation,
    build_conveyed_component,
    do_build_complete,
    do_deed_tendered,
    make_transition_committee_headers,
    read_association,
    seed_association,
    seed_component,
    seed_reserve_study,
    study_action_payload,
    validate_error,
    validate_success,
)

ADOPT_PAYLOAD = study_action_payload(STUDY_ACTION_ADOPT)


# ─── Alpha Ridge: two conveyed components, one draft study ─────────────


@pytest.fixture
def alpha_ridge(api: ApiClient) -> Dict[str, Any]:
    """An association whose whole depreciation table has been conveyed."""
    association = seed_association(
        api,
        name="Alpha Ridge",
        total_planned_lots=30,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=1200000,
        reserve_claim_pool_cents=3000000,
        declarant_monthly_subsidy_cents=150000,
    )
    build_conveyed_component(
        api,
        association["id"],
        effective_date="2024-05-10T00:00:00Z",
        name="Clubhouse",
        category="AMENITY",
        replacement_cost_cents=6000000,
        useful_life_years=20,
        effective_age_years=12,
        promised_completion_date="2024-05-01T00:00:00Z",
    )
    build_conveyed_component(
        api,
        association["id"],
        effective_date="2024-05-10T00:00:00Z",
        name="Private Streets",
        category="INFRASTRUCTURE",
        replacement_cost_cents=5000000,
        useful_life_years=25,
        effective_age_years=25,
        promised_completion_date="2024-05-01T00:00:00Z",
    )
    study = seed_reserve_study(
        api,
        association["id"],
        FUNDING_METHOD_COMPONENT_FULL_FUNDING,
        planned_annual_contribution_cents=700000,
        projected_annual_expenditure_cents=500000,
    )
    return {"association": association, "study": study}


class TestFundingMethodDivergence:
    """One study row, two methods, two verdicts."""

    def test_component_full_funding_reads_the_conveyed_depreciation_table(
        self, api: ApiClient, alpha_ridge: Dict[str, Any]
    ) -> None:
        """COMPONENT_FULL_FUNDING derives its verdict from the funded component set.

        "`fully_funded_balance_cents` is the sum, over that set, of each
        component's `replacement_cost_cents` multiplied by the lesser of its
        `effective_age_years` and its `useful_life_years`, divided by its
        `useful_life_years`, with each component's share rounded down to whole
        cents before it joins the sum."

        Design: Difficulty/dual_variant_calc/reserve_adequacy_component_full_funding_vs_cash_flow_divergence
        """
        association_id = alpha_ridge["association"]["id"]
        response = api.reserve_study_action(
            alpha_ridge["study"]["id"],
            study_action_payload(STUDY_ACTION_RECOMPUTE, method=FUNDING_METHOD_COMPONENT_FULL_FUNDING),
            make_transition_committee_headers(association_id),
        )
        study = validate_success(response)

        assert_study_evaluation(
            study,
            evaluated_method=FUNDING_METHOD_COMPONENT_FULL_FUNDING,
            verdict=ADEQUACY_DEFICIENT,
            recommendation=740000,
            component_count=2,
            fully_funded_balance=8600000,
            percent_funded=13.95,
            min_projected_balance=0,
        )

    def test_cash_flow_reads_the_contribution_pair_and_ignores_the_components(
        self, api: ApiClient, alpha_ridge: Dict[str, Any]
    ) -> None:
        """The same data is DEFICIENT under one method and ADEQUATE under the other.

        "This method never yields `UNDETERMINED`, so the very same data can be
        `ADEQUATE` under `CASH_FLOW` and `UNDETERMINED` under
        `COMPONENT_FULL_FUNDING`."

        Design: Difficulty/dual_variant_calc/reserve_adequacy_component_full_funding_vs_cash_flow_divergence
        """
        association_id = alpha_ridge["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        study_id = alpha_ridge["study"]["id"]

        validate_success(
            api.reserve_study_action(
                study_id,
                study_action_payload(
                    STUDY_ACTION_RECOMPUTE, method=FUNDING_METHOD_COMPONENT_FULL_FUNDING
                ),
                committee,
            )
        )
        study = validate_success(
            api.reserve_study_action(
                study_id,
                study_action_payload(STUDY_ACTION_RECOMPUTE, method=FUNDING_METHOD_CASH_FLOW),
                committee,
            )
        )

        assert_study_evaluation(
            study,
            evaluated_method=FUNDING_METHOD_CASH_FLOW,
            verdict=ADEQUACY_ADEQUATE,
            recommendation=700000,
            min_projected_balance=1200000,
        )
        # The component table is still reported, proving the walk ignored it.
        assert study["fully_funded_balance_cents"] == 8600000
        assert_pct(study["percent_funded"], 13.95, "percent_funded")

        association = read_association(api, association_id)
        assert association["reserve_pool_cents"] == 1200000, (
            "Evaluating a study moves no association cash"
        )


# ─── Northbrook: a completed but unconveyed component ──────────────────


@pytest.fixture
def northbrook(api: ApiClient) -> Dict[str, Any]:
    """A component finished but never accepted, so the funded set is empty."""
    association = seed_association(
        api,
        name="Northbrook",
        total_planned_lots=26,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-05-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=1200000,
        reserve_claim_pool_cents=400000,
        declarant_monthly_subsidy_cents=45000,
    )
    component = seed_component(
        api,
        association["id"],
        name="Trail Network",
        category="INFRASTRUCTURE",
        replacement_cost_cents=5000000,
        useful_life_years=25,
        effective_age_years=25,
        promised_completion_date="2024-01-01T00:00:00Z",
    )
    do_build_complete(api, component["id"], "2024-01-05T00:00:00Z")
    do_deed_tendered(api, component["id"])
    study = seed_reserve_study(
        api,
        association["id"],
        FUNDING_METHOD_COMPONENT_FULL_FUNDING,
        planned_annual_contribution_cents=700000,
        projected_annual_expenditure_cents=500000,
    )
    return {"association": association, "component": component, "study": study}


class TestEmptyFundedComponentSet:
    """An unconveyed component contributes nothing, and the guard is per-method."""

    def test_full_funding_reports_zero_percent_and_refuses_adoption(
        self, api: ApiClient, northbrook: Dict[str, Any]
    ) -> None:
        """An empty funded set leaves the verdict UNDETERMINED and blocks ADOPT.

        "Under `COMPONENT_FULL_FUNDING`, an empty or valueless funded set — a
        `fully_funded_balance_cents` of 0 — leaves `adequacy_verdict` at
        `UNDETERMINED`, `recommended_annual_contribution_cents` at 0 and
        `min_projected_balance_cents` at 0."

        Design: Difficulty/boundary_precision_check/empty_conveyed_component_set_is_undetermined_only_under_full_funding
        """
        association_id = northbrook["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        study_id = northbrook["study"]["id"]

        study = validate_success(
            api.reserve_study_action(
                study_id,
                study_action_payload(
                    STUDY_ACTION_RECOMPUTE, method=FUNDING_METHOD_COMPONENT_FULL_FUNDING
                ),
                committee,
            )
        )
        assert_study_evaluation(
            study,
            evaluated_method=FUNDING_METHOD_COMPONENT_FULL_FUNDING,
            verdict=ADEQUACY_UNDETERMINED,
            recommendation=0,
            component_count=0,
            fully_funded_balance=0,
            percent_funded=0.00,
            min_projected_balance=0,
        )

        validate_error(
            api.reserve_study_action(study_id, ADOPT_PAYLOAD, committee),
            ERR_ADEQUACY_NOT_EVALUATED,
        )

    def test_cash_flow_over_the_same_empty_set_is_adequate_and_adoptable(
        self, api: ApiClient, northbrook: Dict[str, Any]
    ) -> None:
        """The five-year walk never consults the funded set, so ADOPT succeeds.

        "Under `CASH_FLOW` the verdict comes from a five-year walk instead, and
        the funded component set is irrelevant to it."

        Design: Difficulty/boundary_precision_check/empty_conveyed_component_set_is_undetermined_only_under_full_funding
        """
        association_id = northbrook["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        study_id = northbrook["study"]["id"]

        validate_success(
            api.reserve_study_action(
                study_id,
                study_action_payload(
                    STUDY_ACTION_RECOMPUTE, method=FUNDING_METHOD_COMPONENT_FULL_FUNDING
                ),
                committee,
            )
        )
        validate_error(
            api.reserve_study_action(study_id, ADOPT_PAYLOAD, committee),
            ERR_ADEQUACY_NOT_EVALUATED,
        )

        study = validate_success(
            api.reserve_study_action(
                study_id,
                study_action_payload(STUDY_ACTION_RECOMPUTE, method=FUNDING_METHOD_CASH_FLOW),
                committee,
            )
        )
        assert_study_evaluation(
            study,
            evaluated_method=FUNDING_METHOD_CASH_FLOW,
            verdict=ADEQUACY_ADEQUATE,
            recommendation=700000,
            component_count=0,
            fully_funded_balance=0,
            min_projected_balance=1200000,
        )

        adopted = validate_success(
            api.reserve_study_action(study_id, ADOPT_PAYLOAD, committee)
        )
        assert adopted["status"] == "ADOPTED"
