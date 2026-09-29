"""Certifying the turnover trigger: the threshold, the five-hop cascade, the seat majority."""

from typing import Any, Dict

import pytest
from test_helpers import (
    DEFAULT_CLOCK_UTC,
    ERR_TURNOVER_THRESHOLD_NOT_MET,
    POSTURE_OWNER_CONTROL_OPEN,
    POSTURE_TRANSITION_RESTRICTED,
    SEAT_TYPE_DECLARANT_APPOINTED,
    TRIGGER_BASIS_FIXED_DATE,
    TRIGGER_BASIS_PERCENT_SOLD,
    ApiClient,
    assert_cancellation_window,
    assert_dimensions,
    assert_instant,
    assert_pct,
    assert_posture,
    assert_seat_ledger,
    build_adopted_reserve_study,
    certify_trigger_payload,
    do_adopt_schedule,
    do_advance_financial,
    do_advance_governance,
    do_certify_trigger,
    do_close_sale,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    seed_assessment_schedule,
    seed_association,
    seed_audit_engagement,
    seed_component,
    seed_declarant_appointed_director,
    seed_lot,
    seed_owner_elected_director,
    seed_turnover_case,
    seed_vendor_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Elmgate: owner control while the subsidy is still running ──────────


@pytest.fixture
def elmgate(api: ApiClient) -> Dict[str, Any]:
    """A five-seat case standing at the fixed turnover date with nothing else done."""
    association = seed_association(
        api,
        name="Elmgate",
        total_planned_lots=12,
        turnover_threshold_pct=75.00,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=10,
        reserve_pool_cents=400000,
        reserve_claim_pool_cents=1000000,
        declarant_monthly_subsidy_cents=80000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    return {"association": association, "case": case}


class TestGovernanceMovesIndependentlyOfTheSubsidy:
    """The two dimensions run on independent triggers."""

    def test_the_fourth_owner_director_holds_the_election_on_a_five_seat_board(
        self, api: ApiClient, elmgate: Dict[str, Any]
    ) -> None:
        """Three seated owners is not yet a two-thirds majority; the fourth is.

        "From certification onward it is two thirds of `total_seats`, rounded up
        to the next whole seat — so a five-seat board requires four owner-elected
        directors, and a three-seat board requires two."

        Design: Difficulty/non_linear_state_machine/turnover_case_governance_reaches_owner_control_while_subsidy_still_active
        """
        association_id = elmgate["association"]["id"]
        case_id = elmgate["case"]["id"]

        certified = do_certify_trigger(
            api, case_id, association_id, TRIGGER_BASIS_FIXED_DATE
        )
        assert_dimensions(
            certified,
            governance="ELECTION_CALLED",
            financial="SUBSIDY_ACTIVE",
            posture=POSTURE_TRANSITION_RESTRICTED,
        )
        assert certified["owner_elected_seats_required"] == 4

        for index in range(3):
            seed_owner_elected_director(
                api, case_id, full_name=f"Owner Director {index + 1}"
            )
        after_three = read_turnover_case(api, case_id)
        assert after_three["governance_status"] == "ELECTION_CALLED", (
            "Three of the four required seats does not hold the election"
        )
        assert_seat_ledger(
            after_three, declarant_appointed=0, owner_elected=3, vacant=2, total_seats=5
        )

        seed_owner_elected_director(api, case_id, full_name="Owner Director 4")
        after_four = read_turnover_case(api, case_id)
        assert after_four["governance_status"] == "ELECTION_HELD"
        assert_seat_ledger(
            after_four, declarant_appointed=0, owner_elected=4, vacant=1, total_seats=5
        )

    def test_the_governance_handover_leaves_the_financial_dimension_untouched(
        self, api: ApiClient, elmgate: Dict[str, Any]
    ) -> None:
        """OWNER_CONTROL_OPEN is reached with the subsidy still active.

        "It moves `governance_status` `ELECTION_HELD → OWNER_CONTROL` and
        re-derives `turnover_posture`, which becomes `OWNER_CONTROL_OPEN` while
        the financial dimension is still open."

        Design: Difficulty/non_linear_state_machine/turnover_case_governance_reaches_owner_control_while_subsidy_still_active
        """
        association_id = elmgate["association"]["id"]
        case_id = elmgate["case"]["id"]

        do_certify_trigger(api, case_id, association_id, TRIGGER_BASIS_FIXED_DATE)
        for index in range(4):
            seed_owner_elected_director(
                api, case_id, full_name=f"Owner Director {index + 1}"
            )

        advanced = do_advance_governance(api, case_id, association_id)
        assert_dimensions(
            advanced,
            governance="OWNER_CONTROL",
            financial="SUBSIDY_ACTIVE",
            posture=POSTURE_OWNER_CONTROL_OPEN,
        )
        assert_seat_ledger(
            advanced, declarant_appointed=0, owner_elected=4, vacant=1, total_seats=5
        )
        assert_pct(
            advanced["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )


# ─── Harrowfield: five hops from one certification ─────────────────────


@pytest.fixture
def harrowfield(api: ApiClient) -> Dict[str, Any]:
    """An appointed board, an affiliated contract, an adopted budget and a fresh draft."""
    association = seed_association(
        api,
        name="Harrowfield",
        total_planned_lots=9,
        turnover_threshold_pct=90.00,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=1200000,
        reserve_claim_pool_cents=1000000,
        declarant_monthly_subsidy_cents=150000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    director = seed_declarant_appointed_director(
        api, case["id"], full_name="Avery Doyle"
    )
    component = seed_component(
        api,
        association["id"],
        name="Mail Kiosk",
        category="INFRASTRUCTURE",
        replacement_cost_cents=150000,
        useful_life_years=15,
        effective_age_years=3,
        promised_completion_date="2025-01-01T00:00:00Z",
    )
    contract = seed_vendor_contract(
        api,
        association["id"],
        component["id"],
        vendor_name="Declarant Property Services",
        developer_affiliated=True,
        annual_cost_cents=480000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-31T00:00:00Z",
    )
    for index in range(1, 8):
        seed_lot(api, association["id"], f"H-{index:03d}", sale_status="UNDER_CONTRACT")

    build_adopted_reserve_study(
        api,
        association["id"],
        planned_annual_contribution_cents=700000,
        projected_annual_expenditure_cents=500000,
    )
    seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
    )
    do_advance_financial(api, case["id"], association["id"], "2026-11-01T00:00:00Z")

    adopted = seed_assessment_schedule(api, association["id"], 2027, 4100050)
    adopted = do_adopt_schedule(api, adopted["id"], association["id"])
    draft = seed_assessment_schedule(api, association["id"], 2028, 5060250)
    return {
        "association": association,
        "case": case,
        "director": director,
        "component": component,
        "contract": contract,
        "adopted_schedule": adopted,
        "draft_schedule": draft,
    }


class TestCertificationCascade:
    """Each hop is caused by the hop before it, not by the request."""

    def test_the_first_two_hops_call_the_election_and_empty_the_appointed_seats(
        self, api: ApiClient, harrowfield: Dict[str, Any]
    ) -> None:
        """The appointed director resigns as a consequence of ELECTION_CALLED.

        "Entering `ELECTION_CALLED` in turn empties the declarant's side of the
        board: every director of this case whose `seat_type` is
        `DECLARANT_APPOINTED` and whose `status` is `SEATED` moves `SEATED →
        RESIGNED` with `vacated_at` stamped from the clock, processed oldest
        first, dropping `declarant_appointed_seats` to 0 and freeing those seats
        into `vacant_seats`."

        Design: Difficulty/transitive_cascade/certify_trigger_five_hop_cascade_to_superseded_draft_budget
        """
        association_id = harrowfield["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        case_id = harrowfield["case"]["id"]

        case = do_certify_trigger(api, case_id, association_id, TRIGGER_BASIS_FIXED_DATE)
        assert case["governance_status"] == "ELECTION_CALLED"
        assert case["trigger_basis"] == TRIGGER_BASIS_FIXED_DATE
        assert_instant(
            case["trigger_certified_at"], DEFAULT_CLOCK_UTC, "trigger_certified_at"
        )
        assert case["owner_elected_seats_required"] == 4
        assert_posture(case, POSTURE_TRANSITION_RESTRICTED)

        directors, _meta = validate_paginated(api.list_directors(case_id, committee))
        resigned = next(
            row for row in directors if row["id"] == harrowfield["director"]["id"]
        )
        assert resigned["status"] == "RESIGNED"
        assert resigned["seat_type"] == SEAT_TYPE_DECLARANT_APPOINTED
        assert_instant(resigned["vacated_at"], DEFAULT_CLOCK_UTC, "vacated_at")
        assert_seat_ledger(
            case, declarant_appointed=0, owner_elected=0, vacant=5, total_seats=5
        )

    def test_the_third_hop_makes_the_affiliated_contract_cancellable(
        self, api: ApiClient, harrowfield: Dict[str, Any]
    ) -> None:
        """The cancellation window opens ninety days after the certified instant.

        "Emptying the appointed seats is what opens the statutory cancellation
        right: every vendor contract of the association whose
        `developer_affiliated` flag is true and whose `status` is `ACTIVE` moves
        `ACTIVE → CANCELLABLE`, again oldest first, with
        `cancellation_window_end` set to `trigger_certified_at` plus ninety
        days."

        Design: Difficulty/transitive_cascade/certify_trigger_five_hop_cascade_to_superseded_draft_budget
        """
        association_id = harrowfield["association"]["id"]
        committee = make_transition_committee_headers(association_id)

        assert harrowfield["contract"]["status"] == "ACTIVE"
        do_certify_trigger(
            api, harrowfield["case"]["id"], association_id, TRIGGER_BASIS_FIXED_DATE
        )

        contract = validate_success(
            api.get_vendor_contract(harrowfield["contract"]["id"], committee)
        )
        assert contract["status"] == "CANCELLABLE"
        assert_instant(
            contract["cancellation_window_end"],
            "2026-10-30T00:00:00Z",
            "cancellation_window_end",
        )
        assert_cancellation_window(contract, DEFAULT_CLOCK_UTC)

    def test_the_last_two_hops_stale_the_forecast_and_supersede_only_the_draft(
        self, api: ApiClient, harrowfield: Dict[str, Any]
    ) -> None:
        """The adopted schedule survives; the draft built on the old obligations does not.

        "Creating those cancellable obligations makes the adopted operating
        forecast unreliable, so the association's `budget_forecast_status` moves
        from `CURRENT` to `STALE` and its `version` advances — and the stale
        forecast then supersedes every `DRAFT` assessment schedule of the
        association, oldest first."

        Design: Difficulty/transitive_cascade/certify_trigger_five_hop_cascade_to_superseded_draft_budget
        """
        association_id = harrowfield["association"]["id"]
        committee = make_transition_committee_headers(association_id)

        before = read_association(api, association_id)
        assert before["budget_forecast_status"] == "CURRENT", (
            "Adopting the FY2027 schedule returned the forecast to CURRENT"
        )

        do_certify_trigger(
            api, harrowfield["case"]["id"], association_id, TRIGGER_BASIS_FIXED_DATE
        )

        after = read_association(api, association_id)
        assert after["budget_forecast_status"] == "STALE"
        assert after["version"] > before["version"]

        rows, _meta = validate_paginated(
            api.list_assessment_schedules(association_id, committee)
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[harrowfield["draft_schedule"]["id"]]["status"] == "SUPERSEDED"
        assert by_id[harrowfield["adopted_schedule"]["id"]]["status"] == "ADOPTED", (
            "Only DRAFT schedules are superseded"
        )


# ─── Marlowe Court: two of three sold, rounded half up ─────────────────


@pytest.fixture
def marlowe_court(api: ApiClient) -> Dict[str, Any]:
    """A three-lot community whose threshold sits exactly on the two-of-three ratio."""
    association = seed_association(
        api,
        name="Marlowe Court",
        total_planned_lots=3,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2030-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=50000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=20000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    lots = [
        seed_lot(api, association["id"], f"M-{index:03d}") for index in range(1, 4)
    ]
    return {"association": association, "case": case, "lots": lots}


class TestSoldPercentageRoundsOntoTheThreshold:
    """The comparison is made against the rounded percentage."""

    def test_one_of_three_sold_falls_short_of_the_threshold(
        self, api: ApiClient, marlowe_court: Dict[str, Any]
    ) -> None:
        """33.33 percent cannot certify a 66.67 percent trigger.

        "On the `PERCENT_SOLD` basis, the association's `sold_lot_pct` must be
        greater than or equal to its `turnover_threshold_pct`, with equality
        sufficient; a shortfall is `ERR_TURNOVER_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/sold_lot_pct_rounds_half_up_exactly_onto_turnover_threshold
        """
        association_id = marlowe_court["association"]["id"]
        committee = make_transition_committee_headers(association_id)

        do_close_sale(api, marlowe_court["lots"][0]["id"], "2026-03-01T00:00:00Z")
        association = read_association(api, association_id)
        assert association["sold_lot_count"] == 1
        assert_pct(association["sold_lot_pct"], 33.33, "sold_lot_pct")

        validate_error(
            api.certify_trigger(
                marlowe_court["case"]["id"],
                certify_trigger_payload(trigger_basis=TRIGGER_BASIS_PERCENT_SOLD),
                committee,
            ),
            ERR_TURNOVER_THRESHOLD_NOT_MET,
        )

    def test_the_second_closing_rounds_half_up_and_certifies(
        self, api: ApiClient, marlowe_court: Dict[str, Any]
    ) -> None:
        """66.666… becomes 66.67, which equals the threshold.

        "Threshold comparisons are made against the **rounded** value, never
        against the unrounded quotient, so a two-of-three sold ratio is compared
        as 66.67 rather than as an endlessly repeating decimal."

        Design: Difficulty/boundary_precision_check/sold_lot_pct_rounds_half_up_exactly_onto_turnover_threshold
        """
        association_id = marlowe_court["association"]["id"]
        case_id = marlowe_court["case"]["id"]

        do_close_sale(api, marlowe_court["lots"][0]["id"], "2026-03-01T00:00:00Z")
        do_close_sale(api, marlowe_court["lots"][1]["id"], "2026-03-02T00:00:00Z")

        association = read_association(api, association_id)
        assert association["sold_lot_count"] == 2
        assert_pct(association["sold_lot_pct"], 66.67, "sold_lot_pct")
        assert association["sold_lot_pct"] != pytest.approx(66.66, abs=0.001), (
            "Truncating the quotient would report 66.66 and refuse the certification"
        )

        case = do_certify_trigger(
            api, case_id, association_id, TRIGGER_BASIS_PERCENT_SOLD
        )
        assert case["governance_status"] == "ELECTION_CALLED"
        assert case["trigger_basis"] == TRIGGER_BASIS_PERCENT_SOLD
        assert case["owner_elected_seats_required"] == 4

        lots, _meta = validate_paginated(
            api.list_lots(association_id, make_transition_committee_headers(association_id))
        )
        third = next(
            row for row in lots if row["id"] == marlowe_court["lots"][2]["id"]
        )
        assert third["sale_status"] == "UNSOLD", "The third lot was never closed"
