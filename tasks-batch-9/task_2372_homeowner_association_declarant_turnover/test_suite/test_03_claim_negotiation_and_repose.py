"""Claim negotiation rounds, the repose deadline instant, and the conveyance gate."""

from typing import Any, Dict

import pytest
from test_helpers import (
    CLAIM_ACTION_NOTICE,
    CLAIM_ACTION_REINVESTIGATE,
    DEFAULT_CLOCK_UTC,
    ERR_COMPONENT_NOT_CONVEYED,
    ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
    ERR_REPOSE_PERIOD_EXPIRED,
    MILESTONE_CONVEYANCE_ACCEPTED,
    ApiClient,
    assert_instant,
    build_conveyed_component,
    claim_action_payload,
    do_build_complete,
    do_claim_developer_reject,
    do_claim_notice,
    do_claim_reinvestigate,
    do_deed_tendered,
    do_repose_sweep,
    make_transition_committee_headers,
    milestone_payload,
    seed_association,
    seed_component,
    seed_defect_claim,
    set_clock,
    validate_error,
    validate_success,
)

# ─── Fernhollow: three negotiation cycles then the cap ─────────────────


@pytest.fixture
def fernhollow(api: ApiClient) -> Dict[str, Any]:
    """A conveyed component with one claim still in INVESTIGATING."""
    association = seed_association(
        api,
        name="Fernhollow",
        total_planned_lots=18,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2028-03-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=600000,
        reserve_claim_pool_cents=2000000,
        declarant_monthly_subsidy_cents=70000,
    )
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2022-09-20T00:00:00Z",
        name="Perimeter Wall",
        category="STRUCTURE",
        replacement_cost_cents=2000000,
        useful_life_years=30,
        effective_age_years=4,
        promised_completion_date="2022-09-01T00:00:00Z",
    )
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Perimeter wall footing movement",
        repair_cost_estimate_cents=700000,
        diminution_value_cents=400000,
    )
    return {"association": association, "component": component, "claim": claim}


def _run_negotiation_cycle(api: ApiClient, claim_id: str, association_id: str) -> Dict[str, Any]:
    """NOTICE, let the declarant reject, then re-investigate — one full round."""
    do_claim_notice(api, claim_id, association_id)
    do_claim_developer_reject(api, claim_id)
    return do_claim_reinvestigate(api, claim_id, association_id)


class TestNegotiationCycle:
    """The loop is cyclic but bounded by a counter, not by a state."""

    def test_each_reinvestigation_returns_the_claim_and_increments_the_round(
        self, api: ApiClient, fernhollow: Dict[str, Any]
    ) -> None:
        """Three cycles walk negotiation_round from 0 to 3.

        "The committee may then send `REINVESTIGATE`, legal only from
        `REJECTED_BY_DEVELOPER`, which returns the claim
        `REJECTED_BY_DEVELOPER → INVESTIGATING` and increments
        `negotiation_round` by one — closing the cycle `INVESTIGATING → NOTICED →
        REJECTED_BY_DEVELOPER → INVESTIGATING`."

        Design: Difficulty/non_linear_state_machine/defect_claim_negotiation_cycle_reentry_and_round_cap
        """
        association_id = fernhollow["association"]["id"]
        claim_id = fernhollow["claim"]["id"]
        assert fernhollow["claim"]["negotiation_round"] == 0

        for expected_round in (1, 2, 3):
            claim = _run_negotiation_cycle(api, claim_id, association_id)
            assert claim["status"] == "INVESTIGATING"
            assert claim["negotiation_round"] == expected_round, (
                f"Cycle {expected_round} must land on negotiation_round {expected_round}"
            )
            assert_instant(
                claim["repose_deadline"], "2030-09-20T00:00:00Z", "repose_deadline"
            )

    def test_the_fourth_reinvestigation_is_refused_from_a_legal_from_state(
        self, api: ApiClient, fernhollow: Dict[str, Any]
    ) -> None:
        """The counter, not the state, stops the loop.

        "The loop is bounded: re-investigation requires `negotiation_round` to be
        strictly below three completed rounds, so the fourth attempt is refused
        with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/defect_claim_negotiation_cycle_reentry_and_round_cap
        """
        association_id = fernhollow["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        claim_id = fernhollow["claim"]["id"]

        for _ in range(3):
            _run_negotiation_cycle(api, claim_id, association_id)

        do_claim_notice(api, claim_id, association_id)
        rejected = do_claim_developer_reject(api, claim_id)
        assert rejected["status"] == "REJECTED_BY_DEVELOPER"

        validate_error(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_REINVESTIGATE), committee
            ),
            ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
        )

        claim = validate_success(api.get_defect_claim(claim_id, committee))
        assert claim["status"] == "REJECTED_BY_DEVELOPER", (
            "The refused call leaves the from-state untouched"
        )
        assert claim["negotiation_round"] == 3, "The refused call does not increment the round"
        assert_instant(claim["repose_deadline"], "2030-09-20T00:00:00Z", "repose_deadline")


# ─── Pinecrest: one second either side of the deadline ─────────────────


@pytest.fixture
def pinecrest(api: ApiClient) -> Dict[str, Any]:
    """Two investigating claims whose repose deadline carries a 09:30:00 time of day."""
    set_clock(api, "2026-01-01T00:00:00Z")
    association = seed_association(
        api,
        name="Pinecrest",
        total_planned_lots=30,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=400000,
        reserve_claim_pool_cents=3000000,
        declarant_monthly_subsidy_cents=55000,
    )
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2018-03-15T09:30:00Z",
        name="Tennis Courts",
        category="AMENITY",
        replacement_cost_cents=2200000,
        useful_life_years=18,
        effective_age_years=8,
        promised_completion_date="2018-03-01T00:00:00Z",
    )
    on_time = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Court surface heaving, north court",
        repair_cost_estimate_cents=400000,
        diminution_value_cents=250000,
    )
    late = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Court surface heaving, south court",
        repair_cost_estimate_cents=400000,
        diminution_value_cents=250000,
    )
    return {"association": association, "on_time": on_time, "late": late}


class TestReposeDeadlineInclusivity:
    """Notice is inclusive of the deadline instant; the sweep is strict."""

    def test_notice_at_the_deadline_instant_succeeds_and_the_sweep_bars_nothing(
        self, api: ApiClient, pinecrest: Dict[str, Any]
    ) -> None:
        """The deadline keeps the base instant's time of day and is still inside the period.

        "Serving notice of a defect claim is permitted while the clock is at or
        before the claim's `repose_deadline`; the repose sweep only bars a claim
        once the clock is strictly past it."

        Design: Difficulty/boundary_precision_check/repose_deadline_inclusive_at_the_instant_and_strict_for_the_sweep
        """
        association_id = pinecrest["association"]["id"]
        assert_instant(
            pinecrest["on_time"]["repose_deadline"],
            "2026-03-15T09:30:00Z",
            "repose_deadline",
        )

        set_clock(api, "2026-03-15T09:30:00Z")
        noticed = do_claim_notice(api, pinecrest["on_time"]["id"], association_id)
        assert noticed["status"] == "NOTICED"

        swept = do_repose_sweep(api, association_id)
        assert swept["swept_claim_count"] == 0, (
            "A clock standing exactly on the deadline is not strictly past it"
        )
        assert swept["time_barred_claim_ids"] == []

    def test_notice_one_second_later_is_barred_and_the_sweep_takes_the_claim(
        self, api: ApiClient, pinecrest: Dict[str, Any]
    ) -> None:
        """One second past the deadline flips both comparisons.

        "A claim noticed too late, or noticed with no deadline at all, is refused
        with `ERR_REPOSE_PERIOD_EXPIRED`."

        Design: Difficulty/boundary_precision_check/repose_deadline_inclusive_at_the_instant_and_strict_for_the_sweep
        """
        association_id = pinecrest["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        late_id = pinecrest["late"]["id"]

        set_clock(api, "2026-03-15T09:30:00Z")
        do_claim_notice(api, pinecrest["on_time"]["id"], association_id)
        do_repose_sweep(api, association_id)

        set_clock(api, "2026-03-15T09:30:01Z")
        validate_error(
            api.defect_claim_action(
                late_id, claim_action_payload(CLAIM_ACTION_NOTICE), committee
            ),
            ERR_REPOSE_PERIOD_EXPIRED,
        )

        swept = do_repose_sweep(api, association_id)
        assert swept["swept_claim_count"] == 1
        assert swept["time_barred_claim_ids"] == [late_id]

        late_claim = validate_success(api.get_defect_claim(late_id, committee))
        assert late_claim["status"] == "TIME_BARRED"
        on_time_claim = validate_success(
            api.get_defect_claim(pinecrest["on_time"]["id"], committee)
        )
        assert on_time_claim["status"] == "NOTICED", "A noticed claim is never swept"


# ─── Quarry Ridge: notice waits on the component's conveyance ──────────


@pytest.fixture
def quarry_ridge(api: ApiClient) -> Dict[str, Any]:
    """A claim whose repose deadline is far away but whose component is only tendered."""
    association = seed_association(
        api,
        name="Quarry Ridge",
        total_planned_lots=18,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-09-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=250000,
        reserve_claim_pool_cents=4000000,
        declarant_monthly_subsidy_cents=35000,
    )
    component = seed_component(
        api,
        association["id"],
        name="Clubhouse Roof",
        category="STRUCTURE",
        replacement_cost_cents=3400000,
        useful_life_years=25,
        effective_age_years=3,
        promised_completion_date="2023-05-01T00:00:00Z",
    )
    do_build_complete(api, component["id"], "2023-05-05T00:00:00Z")
    do_deed_tendered(api, component["id"])
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Roof membrane delamination",
        repair_cost_estimate_cents=900000,
        diminution_value_cents=500000,
    )
    return {"association": association, "component": component, "claim": claim}


class TestNoticeDependsOnConveyance:
    """A field on a different entity decides whether the claim may move."""

    def test_notice_is_refused_while_the_component_is_only_deed_tendered(
        self, api: ApiClient, quarry_ridge: Dict[str, Any]
    ) -> None:
        """The claim is impeccable; the component is not conveyed.

        "`NOTICE` is legal only from `INVESTIGATING` (otherwise
        `ERR_CLAIM_STATE_INVALID`), requires the referenced component's
        `conveyance_status` to be `CONVEYED` (otherwise
        `ERR_COMPONENT_NOT_CONVEYED`)"

        Design: Difficulty/cross_entity_state_dependency/claim_notice_depends_on_conveyance_state_of_the_component
        """
        association_id = quarry_ridge["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        claim_id = quarry_ridge["claim"]["id"]

        assert_instant(
            quarry_ridge["claim"]["repose_deadline"],
            "2031-05-05T00:00:00Z",
            "repose_deadline",
        )

        validate_error(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_NOTICE), committee
            ),
            ERR_COMPONENT_NOT_CONVEYED,
        )

        claim = validate_success(api.get_defect_claim(claim_id, committee))
        assert claim["status"] == "INVESTIGATING", "The refused notice moved nothing"

    def test_accepting_the_conveyance_unblocks_the_identical_notice(
        self, api: ApiClient, quarry_ridge: Dict[str, Any]
    ) -> None:
        """Acceptance stamps conveyed_at from the logical clock and lets notice through.

        "a `TransitionCommittee` records `CONVEYANCE_ACCEPTED`, legal only from
        `DEED_TENDERED`, which advances `conveyance_status` to `CONVEYED` and
        stamps `conveyed_at` with the logical clock."

        Design: Difficulty/cross_entity_state_dependency/claim_notice_depends_on_conveyance_state_of_the_component
        """
        association_id = quarry_ridge["association"]["id"]
        committee = make_transition_committee_headers(association_id)
        claim_id = quarry_ridge["claim"]["id"]

        validate_error(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_NOTICE), committee
            ),
            ERR_COMPONENT_NOT_CONVEYED,
        )

        component = validate_success(
            api.record_milestone(
                quarry_ridge["component"]["id"],
                milestone_payload(MILESTONE_CONVEYANCE_ACCEPTED),
                committee,
            )
        )
        assert component["conveyance_status"] == "CONVEYED"
        assert_instant(component["conveyed_at"], DEFAULT_CLOCK_UTC, "conveyed_at")

        noticed = validate_success(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_NOTICE), committee
            )
        )
        assert noticed["status"] == "NOTICED"
