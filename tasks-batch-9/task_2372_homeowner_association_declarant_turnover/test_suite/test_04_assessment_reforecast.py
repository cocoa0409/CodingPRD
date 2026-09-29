"""The post-subsidy budget re-forecast: composition, rounding order and the vote cap."""

from typing import Any, Dict, List

import pytest
from test_helpers import (
    ERR_OWNER_VOTE_REQUIRED,
    ERR_RESERVE_STUDY_NOT_ADOPTED,
    FUNDING_METHOD_CASH_FLOW,
    ApiClient,
    assert_pct,
    assert_schedule_waterfall,
    create_schedule_with_fresh_version,
    do_adopt_schedule,
    do_adopt_study,
    do_advance_financial,
    do_close_sale,
    do_recompute_study,
    fresh_association_version,
    make_transition_committee_headers,
    read_association,
    seed_assessment_schedule,
    seed_association,
    seed_audit_engagement,
    seed_lot,
    seed_reserve_study,
    seed_turnover_case,
    validate_error,
    validate_paginated,
    validate_success,
)

AUDIT_PERIOD_START = "2026-01-01T00:00:00Z"
AUDIT_PERIOD_END = "2026-06-30T00:00:00Z"
SUBSIDY_END_DATE = "2026-11-01T00:00:00Z"


def _seed_nine_lot_association(api: ApiClient, name: str, reserve_claim_pool_cents: int):
    """A nine-lot community whose fixed turnover date has already passed."""
    return seed_association(
        api,
        name=name,
        total_planned_lots=9,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=1200000,
        reserve_claim_pool_cents=reserve_claim_pool_cents,
        declarant_monthly_subsidy_cents=150000,
    )


def _seed_lots(
    api: ApiClient, association_id: str, prefix: str, statuses: List[str]
) -> List[Dict[str, Any]]:
    lots = []
    for index, status in enumerate(statuses, start=1):
        lot_number = f"{prefix}-{index:03d}"
        if status == "CLOSED":
            lot = seed_lot(api, association_id, lot_number)
        else:
            lot = seed_lot(api, association_id, lot_number, sale_status=status)
        lots.append(lot)
    return lots


def _open_audit_and_end_the_subsidy(api: ApiClient, association_id: str, case_id: str) -> None:
    seed_audit_engagement(api, association_id, AUDIT_PERIOD_START, AUDIT_PERIOD_END)
    do_advance_financial(api, case_id, association_id, SUBSIDY_END_DATE)


def _seed_cash_flow_study(api: ApiClient, association_id: str) -> Dict[str, Any]:
    return seed_reserve_study(
        api,
        association_id,
        FUNDING_METHOD_CASH_FLOW,
        planned_annual_contribution_cents=700000,
        projected_annual_expenditure_cents=500000,
    )


def _adopt_cash_flow_study(api: ApiClient, association_id: str) -> Dict[str, Any]:
    """Open the study, evaluate it under CASH_FLOW and adopt it."""
    study = _seed_cash_flow_study(api, association_id)
    do_recompute_study(api, study["id"], association_id, FUNDING_METHOD_CASH_FLOW)
    return do_adopt_study(api, study["id"], association_id)


# ─── Cedar Bluff, four closed and three under contract ─────────────────


@pytest.fixture
def cedar_bluff_mixed_lots(api: ApiClient) -> Dict[str, Any]:
    """Four closed lots, three under contract, two unsold, and an adopted study."""
    association = _seed_nine_lot_association(api, "Cedar Bluff", 3000000)
    case = seed_turnover_case(api, association["id"], total_seats=5)
    lots = _seed_lots(
        api,
        association["id"],
        "L",
        ["CLOSED"] * 4 + ["UNDER_CONTRACT"] * 3 + ["UNSOLD"] * 2,
    )
    for offset, lot in enumerate(lots[:4]):
        do_close_sale(api, lot["id"], f"2026-02-{10 + offset}T00:00:00Z")
    _adopt_cash_flow_study(api, association["id"])
    _open_audit_and_end_the_subsidy(api, association["id"], case["id"])
    return {"association": association, "case": case, "lots": lots}


class TestFourInputComposition:
    """annual_requirement_cents composes inputs no single entity holds."""

    def test_the_requirement_sums_the_cost_the_reserve_and_the_subsidy_offset(
        self, api: ApiClient, cedar_bluff_mixed_lots: Dict[str, Any]
    ) -> None:
        """4,800,000 plus 700,000 less 1,500,000 lands on 4,000,000.

        "`subsidy_offset_cents` is the association's
        `declarant_monthly_subsidy_cents` multiplied by the number of months of
        the fiscal year still covered by the subsidy, counted as those of the
        year's twelve year-month labels that sort strictly before the year-month
        of the association's `subsidy_end_date`, and taken as zero when that date
        is null. `annual_requirement_cents` is `projected_operating_cost_cents`
        plus `reserve_contribution_cents` less `subsidy_offset_cents`."

        Design: Difficulty/combinatorial_formula/assessment_reforecast_four_input_non_linear_composition
        """
        association_id = cedar_bluff_mixed_lots["association"]["id"]
        schedule = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2026, 4800000),
            expected_status=201,
        )

        assert_schedule_waterfall(
            schedule,
            billable_lot_count=7,
            reserve_contribution=700000,
            subsidy_offset=1500000,
            annual_requirement=4000000,
            per_lot_monthly=47620,
            annual_total=4000080,
            residual=80,
            increase_pct=0.00,
            owner_vote_required=False,
        )
        assert schedule["status"] == "DRAFT"

    def test_the_billable_set_is_wider_than_the_turnover_numerator(
        self, api: ApiClient, cedar_bluff_mixed_lots: Dict[str, Any]
    ) -> None:
        """Under-contract lots pay; unsold lots do not.

        "`billable_lot_count` is the number of the association's lots whose
        `sale_status` is `CLOSED` or `UNDER_CONTRACT`; lots still `UNSOLD` are
        excluded from the divisor because the declarant absorbs their share of
        the deficit"

        Design: Difficulty/combinatorial_formula/assessment_reforecast_four_input_non_linear_composition
        """
        association_id = cedar_bluff_mixed_lots["association"]["id"]
        schedule = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2026, 4800000),
            expected_status=201,
        )

        association = read_association(api, association_id)
        assert association["sold_lot_count"] == 4, "Only closed lots reach the trigger numerator"
        assert schedule["billable_lot_count"] == 7, (
            "The billable set adds the three under-contract lots"
        )
        assert schedule["subsidy_offset_cents"] == 1500000, (
            "Ten FY2026 months sort strictly before 2026-11"
        )


# ─── Cedar Bluff, seven under contract: the rounding order ─────────────


@pytest.fixture
def cedar_bluff_under_contract(api: ApiClient) -> Dict[str, Any]:
    """Seven under-contract lots, an adopted study, and an FY2026 draft on the books."""
    association = _seed_nine_lot_association(api, "Cedar Bluff", 3000000)
    case = seed_turnover_case(api, association["id"], total_seats=5)
    _seed_lots(
        api, association["id"], "L", ["UNDER_CONTRACT"] * 7 + ["UNSOLD"] * 2
    )
    _adopt_cash_flow_study(api, association["id"])
    _open_audit_and_end_the_subsidy(api, association["id"], case["id"])
    schedule = seed_assessment_schedule(api, association["id"], 2026, 4800000)
    return {"association": association, "case": case, "schedule": schedule}


class TestPerLotRoundingOrder:
    """Divide to a per-lot figure first, then multiply back up."""

    def test_the_ceiling_per_lot_figure_overshoots_and_leaves_a_residual(
        self, api: ApiClient, cedar_bluff_under_contract: Dict[str, Any]
    ) -> None:
        """The total is multiplied back up from the per-lot ceiling.

        "`residual_cents` is `annual_budget_total_cents` less
        `annual_requirement_cents` — a small over-collection that arises
        precisely because of the ceiling."

        Design: Difficulty/combinatorial_formula/assessment_per_lot_rounding_order_produces_residual
        """
        schedule = cedar_bluff_under_contract["schedule"]
        assert_schedule_waterfall(
            schedule,
            billable_lot_count=7,
            reserve_contribution=700000,
            subsidy_offset=1500000,
            annual_requirement=4000000,
            per_lot_monthly=47620,
            annual_total=4000080,
            residual=80,
        )
        assert schedule["residual_cents"] != 0, (
            "Summing first and rounding once at the end would force a zero residual"
        )

    def test_adoption_credits_the_residual_to_the_reserve_pool(
        self, api: ApiClient, cedar_bluff_under_contract: Dict[str, Any]
    ) -> None:
        """The rounding order is observable again on the association's cash.

        "the schedule's `residual_cents` is credited to the association's
        `reserve_pool_cents`, `budget_forecast_status` returns from `STALE` to
        `CURRENT`, and the association's `version` advances."

        Design: Difficulty/combinatorial_formula/assessment_per_lot_rounding_order_produces_residual
        """
        association_id = cedar_bluff_under_contract["association"]["id"]
        adopted = do_adopt_schedule(
            api, cedar_bluff_under_contract["schedule"]["id"], association_id
        )
        assert adopted["status"] == "ADOPTED"

        association = read_association(api, association_id)
        assert association["reserve_pool_cents"] == 1200080
        assert association["budget_forecast_status"] == "CURRENT"

        next_year = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2027, 4100050),
            expected_status=201,
        )
        assert_schedule_waterfall(
            next_year,
            billable_lot_count=7,
            reserve_contribution=700000,
            subsidy_offset=0,
            annual_requirement=4800050,
            per_lot_monthly=57144,
            annual_total=4800096,
            residual=46,
        )


# ─── Oakhaven: the twenty percent cap, tested at adjacent cents ────────


@pytest.fixture
def oakhaven(api: ApiClient) -> Dict[str, Any]:
    """FY2026 and FY2027 both adopted, so FY2027's 57,144 is the increase baseline."""
    association = _seed_nine_lot_association(api, "Oakhaven", 500000)
    case = seed_turnover_case(api, association["id"], total_seats=5)
    _seed_lots(
        api, association["id"], "O", ["UNDER_CONTRACT"] * 7 + ["UNSOLD"] * 2
    )
    _adopt_cash_flow_study(api, association["id"])
    _open_audit_and_end_the_subsidy(api, association["id"], case["id"])

    first = seed_assessment_schedule(api, association["id"], 2026, 4800000)
    do_adopt_schedule(api, first["id"], association["id"])
    baseline = seed_assessment_schedule(api, association["id"], 2027, 4100050)
    baseline = do_adopt_schedule(api, baseline["id"], association["id"])
    return {"association": association, "case": case, "baseline": baseline}


class TestOwnerVoteCap:
    """The vote is required only strictly above the cap."""

    def test_an_increase_that_rounds_to_exactly_the_cap_needs_no_vote(
        self, api: ApiClient, oakhaven: Dict[str, Any]
    ) -> None:
        """20.00 percent is not strictly greater than 20.00 percent.

        "`owner_vote_required` is true only when that percentage is **strictly
        greater** than the statutory cap of 20.00 percent; an increase that
        rounds to exactly 20.00 needs no vote."

        Design: Difficulty/boundary_precision_check/assessment_increase_strictly_above_cap_requires_owner_vote
        """
        association_id = oakhaven["association"]["id"]
        assert oakhaven["baseline"]["per_lot_monthly_assessment_cents"] == 57144

        at_cap = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2028, 5060250),
            expected_status=201,
        )
        assert at_cap["annual_requirement_cents"] == 5760250
        assert at_cap["per_lot_monthly_assessment_cents"] == 68575
        assert at_cap["residual_cents"] == 50
        assert_pct(at_cap["increase_pct_vs_prior"], 20.00, "increase_pct_vs_prior")
        assert at_cap["owner_vote_required"] is False

    def test_one_cent_more_crosses_the_cap_and_gates_adoption_on_ratification(
        self, api: ApiClient, oakhaven: Dict[str, Any]
    ) -> None:
        """A per-lot figure of 68,576 rounds to 20.01 and demands the flag.

        "when `owner_vote_required` is true the payload must carry
        `owner_vote_ratified` set to true, else `ERR_OWNER_VOTE_REQUIRED`"

        Design: Difficulty/boundary_precision_check/assessment_increase_strictly_above_cap_requires_owner_vote
        """
        association_id = oakhaven["association"]["id"]
        committee = make_transition_committee_headers(association_id)

        at_cap = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2028, 5060250),
            expected_status=201,
        )
        over_cap = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2028, 5060350),
            expected_status=201,
        )

        assert over_cap["per_lot_monthly_assessment_cents"] == 68576
        assert_pct(over_cap["increase_pct_vs_prior"], 20.01, "increase_pct_vs_prior")
        assert over_cap["owner_vote_required"] is True

        rows, _meta = validate_paginated(
            api.list_assessment_schedules(association_id, committee, {"fiscal_year": 2028})
        )
        at_cap_row = next(row for row in rows if row["id"] == at_cap["id"])
        assert at_cap_row["status"] == "SUPERSEDED", (
            "The newer FY2028 draft supersedes the earlier one"
        )

        validate_error(
            api.adopt_assessment_schedule(over_cap["id"], committee),
            ERR_OWNER_VOTE_REQUIRED,
        )

        adopted = do_adopt_schedule(
            api, over_cap["id"], association_id, owner_vote_ratified=True
        )
        assert adopted["status"] == "ADOPTED"
        assert adopted["owner_vote_ratified"] is True


# ─── Ridgeline Park: the study must be adopted, not merely evaluated ───


@pytest.fixture
def ridgeline_park(api: ApiClient) -> Dict[str, Any]:
    """A study evaluated as ADEQUATE but deliberately left in DRAFT."""
    association = _seed_nine_lot_association(api, "Ridgeline Park", 500000)
    case = seed_turnover_case(api, association["id"], total_seats=5)
    _seed_lots(
        api, association["id"], "R", ["UNDER_CONTRACT"] * 7 + ["UNSOLD"] * 2
    )
    _open_audit_and_end_the_subsidy(api, association["id"], case["id"])
    study = _seed_cash_flow_study(api, association["id"])
    study = do_recompute_study(
        api, study["id"], association["id"], FUNDING_METHOD_CASH_FLOW
    )
    return {"association": association, "case": case, "study": study}


class TestScheduleNeedsAnAdoptedStudy:
    """The gate is the study's state, not its contents."""

    def test_creation_is_refused_while_the_evaluated_study_is_still_a_draft(
        self, api: ApiClient, ridgeline_park: Dict[str, Any]
    ) -> None:
        """The recommendation is already 700,000, yet the draft cannot be read from.

        "The association's financial dimension must have left `SUBSIDY_ACTIVE`,
        else `ERR_SUBSIDY_STILL_ACTIVE`, and an `ADOPTED` reserve study must
        exist, else `ERR_RESERVE_STUDY_NOT_ADOPTED`."

        Design: Difficulty/cross_entity_state_dependency/assessment_creation_depends_on_adopted_reserve_study_state
        """
        association_id = ridgeline_park["association"]["id"]
        study = ridgeline_park["study"]
        assert study["status"] == "DRAFT"
        assert study["adequacy_verdict"] == "ADEQUATE"
        assert study["recommended_annual_contribution_cents"] == 700000

        validate_error(
            create_schedule_with_fresh_version(api, association_id, 2027, 4100050),
            ERR_RESERVE_STUDY_NOT_ADOPTED,
        )

    def test_adopting_the_study_unblocks_the_identical_creation(
        self, api: ApiClient, ridgeline_park: Dict[str, Any]
    ) -> None:
        """The created schedule carries the adopted study's recommendation.

        "`reserve_contribution_cents` is the
        `recommended_annual_contribution_cents` of the association's single
        `ADOPTED` study."

        Design: Difficulty/cross_entity_state_dependency/assessment_creation_depends_on_adopted_reserve_study_state
        """
        association_id = ridgeline_park["association"]["id"]

        validate_error(
            create_schedule_with_fresh_version(api, association_id, 2027, 4100050),
            ERR_RESERVE_STUDY_NOT_ADOPTED,
        )

        adopted_study = do_adopt_study(
            api, ridgeline_park["study"]["id"], association_id
        )
        assert adopted_study["status"] == "ADOPTED"

        version_before = fresh_association_version(api, association_id)
        schedule = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2027, 4100050),
            expected_status=201,
        )
        assert version_before >= 1
        assert_schedule_waterfall(
            schedule,
            billable_lot_count=7,
            reserve_contribution=700000,
            subsidy_offset=0,
            annual_requirement=4800050,
            per_lot_monthly=57144,
            annual_total=4800096,
            residual=46,
            increase_pct=0.00,
            owner_vote_required=False,
        )
