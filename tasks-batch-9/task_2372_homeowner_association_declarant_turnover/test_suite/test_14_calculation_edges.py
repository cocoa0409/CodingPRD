"""Filtered input sets, applied constants and the precision of the derived figures."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ADEQUACY_DEFICIENT,
    ADEQUACY_MARGINAL,
    AUDITOR_USER_ID,
    FINDING_EXCEPTION_NOTED,
    FUNDING_METHOD_CASH_FLOW,
    TRIGGER_BASIS_FIXED_DATE,
    ApiClient,
    assert_instant,
    assert_pct,
    assert_seat_ledger,
    assert_study_evaluation,
    do_accept_item,
    do_build_complete,
    do_certify_trigger,
    do_close_sale,
    do_deliver_item,
    do_issue_engagement,
    do_recompute_study,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    seed_association,
    seed_audit_engagement,
    seed_component,
    seed_defect_claim,
    seed_lot,
    seed_records_item,
    seed_reserve_study,
    seed_subsidy_entry,
    seed_turnover_case,
    validate_paginated,
)

# ─── Coppice End: the planned lot denominator ──────────────────────────


@pytest.fixture
def coppice_end(api: ApiClient) -> Dict[str, Any]:
    """Eight planned lots, five platted rows, one of them under contract."""
    association = seed_association(
        api,
        name="Coppice End",
        total_planned_lots=8,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=0,
    )
    lots = [seed_lot(api, association["id"], f"C-00{n}") for n in (1, 2, 3)]
    under_contract = seed_lot(
        api, association["id"], "C-004", sale_status="UNDER_CONTRACT"
    )
    unsold = seed_lot(api, association["id"], "C-005")
    return {
        "association": association,
        "lots": lots,
        "under_contract": under_contract,
        "unsold": unsold,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestSoldLotArithmetic:
    """Three closings out of five rows is 37.50 percent of eight planned lots."""

    def test_the_percentage_divides_by_the_planned_total_not_the_rows_on_file(
        self, api: ApiClient, coppice_end: Dict[str, Any]
    ) -> None:
        """Each closing moves the pair, and 3 of 8 is 37.50 rather than 3 of 5.

        "`sold_lot_pct` then becomes one hundred multiplied by `sold_lot_count`,
        divided by `total_planned_lots`, rounded half up to two decimal places —
        note that the denominator is the declaration's planned lot total, not the
        number of lot records that happen to exist."

        Design: Corner/calculations/sold_lot_count_counts_closed_lots_only
        """
        association_id = coppice_end["association"]["id"]

        for lot, closing_date, expected_count, expected_pct in (
            (coppice_end["lots"][0], "2026-02-01T00:00:00Z", 1, 12.50),
            (coppice_end["lots"][1], "2026-03-01T00:00:00Z", 2, 25.00),
            (coppice_end["lots"][2], "2026-04-01T00:00:00Z", 3, 37.50),
        ):
            closed = do_close_sale(api, lot["id"], closing_date)
            assert closed["sale_status"] == "CLOSED"
            association = read_association(api, association_id)
            assert association["sold_lot_count"] == expected_count
            assert_pct(association["sold_lot_pct"], expected_pct, "sold_lot_pct")

    def test_an_under_contract_lot_stays_out_of_the_closed_numerator(
        self, api: ApiClient, coppice_end: Dict[str, Any]
    ) -> None:
        """The filtered listing and the derived count agree on the same three rows.

        "`sold_lot_count` becomes the number of that association's lots whose
        `sale_status` is `CLOSED`; lots still `UNSOLD` or `UNDER_CONTRACT` are
        excluded from that count."

        Design: Corner/calculations/sold_lot_count_counts_closed_lots_only
        """
        association_id = coppice_end["association"]["id"]
        committee = coppice_end["committee_headers"]

        for lot, closing_date in (
            (coppice_end["lots"][0], "2026-02-01T00:00:00Z"),
            (coppice_end["lots"][1], "2026-03-01T00:00:00Z"),
            (coppice_end["lots"][2], "2026-04-01T00:00:00Z"),
        ):
            do_close_sale(api, lot["id"], closing_date)

        _rows, meta = validate_paginated(
            api.list_lots(
                association_id, committee, {"sale_status": "CLOSED", "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3

        all_rows, all_meta = validate_paginated(api.list_lots(association_id, committee))
        assert all_meta["total_count"] == 5
        by_id = {row["id"]: row for row in all_rows}
        assert by_id[coppice_end["under_contract"]["id"]]["sale_status"] == "UNDER_CONTRACT"
        assert by_id[coppice_end["unsold"]["id"]]["sale_status"] == "UNSOLD"

        association = read_association(api, association_id)
        assert association["sold_lot_count"] == 3
        assert_pct(association["sold_lot_pct"], 37.50, "sold_lot_pct")


# ─── Dovegate: the five-year cash flow walk ───────────────────────────


@pytest.fixture
def dovegate(api: ApiClient) -> Dict[str, Any]:
    """A 400,000 cent pool and a draft study contributing 200,000 a year."""
    association = seed_association(
        api,
        name="Dovegate",
        total_planned_lots=6,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=400000,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=0,
    )
    marginal = seed_reserve_study(
        api,
        association["id"],
        FUNDING_METHOD_CASH_FLOW,
        planned_annual_contribution_cents=200000,
        projected_annual_expenditure_cents=300000,
    )
    return {
        "association": association,
        "marginal": marginal,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestCashFlowWalk:
    """The verdict is the running minimum of six balances, not a flat multiple."""

    def test_the_escalated_walk_bottoms_out_inside_the_marginal_floor(
        self, api: ApiClient, dovegate: Dict[str, Any]
    ) -> None:
        """Year five closes at -235,000, which is above the 500,000 cent floor.

        "The verdict is `ADEQUATE` when that minimum is zero or better, `MARGINAL`
        when it is negative but no deeper than 500,000 cents below zero, and
        `DEFICIENT` when it falls below that floor."

        Design: Corner/calculations/cash_flow_year_walk_escalates_expenditure_and_takes_the_running_minimum
        """
        evaluated = do_recompute_study(
            api,
            dovegate["marginal"]["id"],
            dovegate["association"]["id"],
            FUNDING_METHOD_CASH_FLOW,
        )
        assert evaluated["status"] == "DRAFT"
        assert_study_evaluation(
            evaluated,
            evaluated_method=FUNDING_METHOD_CASH_FLOW,
            verdict=ADEQUACY_MARGINAL,
            recommendation=247000,
            component_count=0,
            percent_funded=0.00,
            min_projected_balance=-235000,
        )

    def test_a_thinner_contribution_falls_past_the_floor_and_supersedes_the_draft(
        self, api: ApiClient, dovegate: Dict[str, Any]
    ) -> None:
        """100,000 a year bottoms out at -735,000 while the old draft keeps its figure.

        "Opening a study supersedes any other `DRAFT` study of the same
        association, so only one draft is ever live."

        Design: Corner/calculations/cash_flow_year_walk_escalates_expenditure_and_takes_the_running_minimum
        """
        association_id = dovegate["association"]["id"]
        committee = dovegate["committee_headers"]

        do_recompute_study(
            api, dovegate["marginal"]["id"], association_id, FUNDING_METHOD_CASH_FLOW
        )

        deficient = seed_reserve_study(
            api,
            association_id,
            FUNDING_METHOD_CASH_FLOW,
            planned_annual_contribution_cents=100000,
            projected_annual_expenditure_cents=300000,
        )
        evaluated = do_recompute_study(
            api, deficient["id"], association_id, FUNDING_METHOD_CASH_FLOW
        )
        assert_study_evaluation(
            evaluated,
            evaluated_method=FUNDING_METHOD_CASH_FLOW,
            verdict=ADEQUACY_DEFICIENT,
            recommendation=247000,
            min_projected_balance=-735000,
        )

        rows, meta = validate_paginated(
            api.list_reserve_studies(association_id, committee)
        )
        assert meta["total_count"] == 2
        superseded = next(
            row for row in rows if row["id"] == dovegate["marginal"]["id"]
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["min_projected_balance_cents"] == -235000, (
            "The superseded study keeps the figure it was evaluated at"
        )


# ─── Elmsworth: the audited month window ──────────────────────────────


@pytest.fixture
def elmsworth(api: ApiClient) -> Dict[str, Any]:
    """Four postings straddling both ends of a mid-month audit period."""
    association = seed_association(
        api,
        name="Elmsworth",
        total_planned_lots=6,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=100000,
    )
    january = seed_subsidy_entry(api, association["id"], "ACCRUAL", 100000, "2026-01")
    march = seed_subsidy_entry(api, association["id"], "PAYMENT", 40000, "2026-03")
    december = seed_subsidy_entry(api, association["id"], "ACCRUAL", 70000, "2025-12")
    april = seed_subsidy_entry(api, association["id"], "ACCRUAL", 50000, "2026-04")
    engagement = seed_audit_engagement(
        api, association["id"], "2026-01-15T00:00:00Z", "2026-03-20T00:00:00Z"
    )
    return {
        "association": association,
        "january": january,
        "march": march,
        "december": december,
        "april": april,
        "engagement": engagement,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestAuditSnapshotWindow:
    """Both month bounds are admitted whole; the neighbouring months are not."""

    def test_the_snapshot_admits_both_bound_months_and_excludes_the_neighbours(
        self, api: ApiClient, elmsworth: Dict[str, Any]
    ) -> None:
        """A 60,000 snapshot against a 180,000 receivable is an immediate exception.

        "`audited_receivable_snapshot_cents` is the total of the association's
        `POSTED` `ACCRUAL` amounts less the total of its `POSTED` `PAYMENT`
        amounts, restricted to entries whose `period_month` lies inside the
        engagement's window, where the window runs from the year-and-month of
        `period_start` to the year-and-month of `period_end` with both bounds
        included and the comparison made on the year-month strings themselves."

        Design: Corner/calculations/audit_snapshot_window_is_closed_on_both_month_bounds
        """
        association_id = elmsworth["association"]["id"]
        committee = elmsworth["committee_headers"]

        association = read_association(api, association_id)
        assert association["subsidy_receivable_cents"] == 180000

        issued = do_issue_engagement(api, elmsworth["engagement"]["id"])
        assert issued["audited_receivable_snapshot_cents"] == 60000
        assert issued["unreconciled_delta_cents"] == 120000
        assert issued["finding_status"] == FINDING_EXCEPTION_NOTED
        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == AUDITOR_USER_ID

        rows, _meta = validate_paginated(
            api.list_subsidy_entries(committee, {"association_id": association_id})
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[elmsworth["december"]["id"]]["status"] == "POSTED", (
            "The out-of-window entry is excluded by month, not by state"
        )
        assert by_id[elmsworth["april"]["id"]]["status"] == "POSTED"
        assert by_id[elmsworth["january"]["id"]]["period_month"] == "2026-01"
        assert by_id[elmsworth["march"]["id"]]["period_month"] == "2026-03"


# ─── Fernbrook: the completeness percentage ───────────────────────────


@pytest.fixture
def fernbrook(api: ApiClient) -> Dict[str, Any]:
    """A three-seat case carrying no records items at all."""
    association = seed_association(
        api,
        name="Fernbrook",
        total_planned_lots=6,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=0,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    return {
        "association": association,
        "case": case,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestCompletenessPrecision:
    """An empty required set is 100.00; one of three required is 33.33."""

    def test_an_empty_required_set_is_vacuously_complete_even_with_an_optional_item(
        self, api: ApiClient, fernbrook: Dict[str, Any]
    ) -> None:
        """Registering a non-required item leaves the divisor empty.

        "A case whose required set is empty is vacuously complete and reports
        100.00 rather than failing on a division — which is why a brand-new case
        starts at 100.00."

        Design: Corner/calculations/records_completeness_is_vacuously_complete_and_rounds_half_up
        """
        case_id = fernbrook["case"]["id"]

        assert_pct(
            fernbrook["case"]["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )

        optional = seed_records_item(api, case_id, "PERMITS", required=False)
        assert optional["required"] is False
        assert optional["status"] == "OUTSTANDING"

        case = read_turnover_case(api, case_id)
        assert_pct(
            case["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )

    def test_one_accepted_of_three_required_rounds_half_up_to_thirty_three_thirty_three(
        self, api: ApiClient, fernbrook: Dict[str, Any]
    ) -> None:
        """The optional row never enters the divisor, so the quotient is one third.

        "it is the number of required items whose `status` is `ACCEPTED`,
        multiplied by one hundred, divided by the number of required items,
        rounded half up to two decimal places"

        Design: Corner/calculations/records_completeness_is_vacuously_complete_and_rounds_half_up
        """
        association_id = fernbrook["association"]["id"]
        case_id = fernbrook["case"]["id"]

        optional = seed_records_item(api, case_id, "PERMITS", required=False)
        required = [
            seed_records_item(api, case_id, category, required=True)
            for category in ("FINANCIAL_RECORDS", "WARRANTIES", "PLANS_AND_SPECS")
        ]

        case = read_turnover_case(api, case_id)
        assert_pct(
            case["records_transfer_completeness_pct"],
            0.00,
            "records_transfer_completeness_pct",
        )

        do_deliver_item(api, required[0]["id"])
        do_accept_item(api, required[0]["id"], association_id)

        case = read_turnover_case(api, case_id)
        assert_pct(
            case["records_transfer_completeness_pct"],
            33.33,
            "records_transfer_completeness_pct",
        )

        rows, _meta = validate_paginated(
            api.list_records_items(case_id, fernbrook["committee_headers"])
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[optional["id"]]["status"] == "OUTSTANDING"
        assert by_id[required[1]["id"]]["status"] == "OUTSTANDING"
        assert by_id[required[2]["id"]]["status"] == "OUTSTANDING"


# ─── Gallowtree: two thirds of the board, rounded up ──────────────────


@pytest.fixture
def gallowtree(api: ApiClient) -> Dict[str, Any]:
    """Three communities whose declaration dates have passed, with 5, 3 and 7 seats."""
    boards = {}
    for label, seats in (("Five", 5), ("Three", 3), ("Seven", 7)):
        association = seed_association(
            api,
            name=f"Gallowtree {label}",
            total_planned_lots=6,
            turnover_threshold_pct=66.67,
            fixed_turnover_date="2026-07-01T00:00:00Z",
            statute_of_repose_years=8,
            reserve_pool_cents=0,
            reserve_claim_pool_cents=0,
            declarant_monthly_subsidy_cents=0,
        )
        case = seed_turnover_case(api, association["id"], total_seats=seats)
        boards[seats] = {"association": association, "case": case}
    return boards


class TestOwnerElectedSeatRequirement:
    """Five seats need four, three need two and seven need five."""

    def test_the_requirement_is_zero_until_certification_then_a_ceiling(
        self, api: ApiClient, gallowtree: Dict[str, Any]
    ) -> None:
        """Flooring two thirds would understate every one of the three boards.

        "From certification onward it is two thirds of `total_seats`, rounded up
        to the next whole seat — so a five-seat board requires four owner-elected
        directors, and a three-seat board requires two."

        Design: Corner/calculations/owner_elected_seat_requirement_is_a_ceiling_of_two_thirds_of_the_board
        """
        for seats in (5, 3, 7):
            case = gallowtree[seats]["case"]
            assert case["owner_elected_seats_required"] == 0
            assert case["governance_status"] == "DECLARANT_CONTROL"

        for seats, expected_required in ((5, 4), (3, 2), (7, 5)):
            board = gallowtree[seats]
            certified = do_certify_trigger(
                api,
                board["case"]["id"],
                board["association"]["id"],
                TRIGGER_BASIS_FIXED_DATE,
            )
            assert certified["governance_status"] == "ELECTION_CALLED"
            assert certified["owner_elected_seats_required"] == expected_required
            assert_seat_ledger(
                certified,
                declarant_appointed=0,
                owner_elected=0,
                vacant=seats,
                total_seats=seats,
            )


# ─── Hallowmere: the repose deadline's calendar arithmetic ────────────


@pytest.fixture
def hallowmere(api: ApiClient) -> Dict[str, Any]:
    """A five-year statute over one leap-day completion and one ordinary one."""
    association = seed_association(
        api,
        name="Hallowmere",
        total_planned_lots=6,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=5,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=900000,
        declarant_monthly_subsidy_cents=0,
    )
    leap = seed_component(
        api,
        association["id"],
        name="Leap Year Clubhouse",
        category="AMENITY",
        replacement_cost_cents=500000,
        useful_life_years=20,
        effective_age_years=6,
        promised_completion_date="2020-02-29T14:45:00Z",
    )
    plain = seed_component(
        api,
        association["id"],
        name="Perimeter Wall",
        category="STRUCTURE",
        replacement_cost_cents=300000,
        useful_life_years=25,
        effective_age_years=8,
        promised_completion_date="2018-03-15T09:30:00Z",
    )
    do_build_complete(api, leap["id"], "2020-02-29T14:45:00Z")
    do_build_complete(api, plain["id"], "2018-03-15T09:30:00Z")
    return {
        "association": association,
        "leap": leap,
        "plain": plain,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestReposeDeadlineArithmetic:
    """Calendar-year addition keeps the time of day and clamps 29 February."""

    def test_a_leap_day_completion_clamps_to_the_twenty_eighth(
        self, api: ApiClient, hallowmere: Dict[str, Any]
    ) -> None:
        """2020-02-29T14:45:00Z plus five years is 2025-02-28T14:45:00Z, not 03-01.

        "Once that date exists, the deadline is that instant advanced by the
        association's `statute_of_repose_years` whole calendar years, landing on
        the same month and day and preserving the time of day; where the target
        year has no such day — a 29 February base in a non-leap year — the
        deadline clamps back to 28 February."

        Design: Corner/calculations/repose_deadline_clamps_february_29_and_keeps_the_time_of_day
        """
        claim = seed_defect_claim(
            api,
            hallowmere["association"]["id"],
            hallowmere["leap"]["id"],
            defect_summary="Slab heave under the clubhouse",
            repair_cost_estimate_cents=400000,
            diminution_value_cents=250000,
        )
        assert_instant(
            claim["repose_deadline"], "2025-02-28T14:45:00Z", "repose_deadline"
        )
        assert claim["status"] == "INVESTIGATING"
        assert claim["reserved_amount_cents"] == 0
        assert claim["negotiation_round"] == 0

        rows, _meta = validate_paginated(
            api.list_components(
                hallowmere["association"]["id"], hallowmere["committee_headers"]
            )
        )
        leap = next(row for row in rows if row["id"] == hallowmere["leap"]["id"])
        assert_instant(
            leap["substantial_completion_date"],
            "2020-02-29T14:45:00Z",
            "substantial_completion_date",
        )

    def test_an_ordinary_completion_keeps_its_month_day_and_time_of_day(
        self, api: ApiClient, hallowmere: Dict[str, Any]
    ) -> None:
        """2018-03-15T09:30:00Z plus five years lands at 09:30, not at midnight.

        "the deadline is that instant advanced by the association's
        `statute_of_repose_years` whole calendar years, landing on the same month
        and day and preserving the time of day"

        Design: Corner/calculations/repose_deadline_clamps_february_29_and_keeps_the_time_of_day
        """
        claim = seed_defect_claim(
            api,
            hallowmere["association"]["id"],
            hallowmere["plain"]["id"],
            defect_summary="Wall footing displacement",
            repair_cost_estimate_cents=200000,
            diminution_value_cents=120000,
        )
        assert_instant(
            claim["repose_deadline"], "2023-03-15T09:30:00Z", "repose_deadline"
        )
        assert claim["status"] == "INVESTIGATING"

        rows, _meta = validate_paginated(
            api.list_components(
                hallowmere["association"]["id"], hallowmere["committee_headers"]
            )
        )
        plain = next(row for row in rows if row["id"] == hallowmere["plain"]["id"])
        assert_instant(
            plain["substantial_completion_date"],
            "2018-03-15T09:30:00Z",
            "substantial_completion_date",
        )
