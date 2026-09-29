"""Ledgers that must return to their exact starting value after compensation."""

from test_helpers import (
    accepted_organ,
    allocatable_organ,
    assert_slot_conservation,
    assert_team_ledger,
    book_operation,
    cancel_operation,
    candidate_sequence,
    create_team,
    find_offer,
    list_offers,
    open_match_run,
    read_case,
    read_organ,
    read_run,
    read_team,
    respond_to_offer,
)

LEDGER_CLOCK = "2026-08-27T07:00:00Z"
SLOT_CLOCK = "2026-08-28T09:00:00Z"


# ---------------------------------------------------------------------------
# Conserved quantity one: the recovery team's OR-minutes ledger
# ---------------------------------------------------------------------------
def _liver_case_with_a_booked_theatre(env):
    team = create_team(env, specialty="ABDOMINAL", turnaround_buffer_minutes=90)
    assert team["booked_or_minutes"] == 0
    assert team["scheduled_operation_count"] == 0

    bundle = accepted_organ(
        env, "LIVER", LEDGER_CLOCK, candidate_count=1, primary_offer_slots=1
    )
    bundle.team = team
    bundle.operation = book_operation(
        env,
        bundle.case_id,
        team["id"],
        "2026-08-27T08:00:00Z",
        "2026-08-27T12:00:00Z",
    )
    return bundle


def test_a_new_team_starts_empty_and_the_booking_fills_the_ledger(env):
    """Zero to 240 minutes and zero to one scheduled operation.

    PRD 3.7: "A new team starts with `booked_or_minutes` and
    `scheduled_operation_count` at zero."
    PRD 3.7: "The team's `booked_or_minutes` increases by that `or_minutes` and
    its `scheduled_operation_count` by one."

    Design: Difficulty/compensating_invariant/recovery_team_or_minutes_ledger_returns_to_zero_on_cancel
    """
    bundle = _liver_case_with_a_booked_theatre(env)

    assert bundle.operation["or_minutes"] == 240
    assert_team_ledger(read_team(env, bundle.team["id"]), 240, 1)


def test_cancelling_returns_the_ledger_to_exactly_zero(env):
    """The compensation is exact rather than approximate.

    PRD 3.7: "it moves `SCHEDULED → CANCELLED` with `cancelled_reason`
    `LOGISTICS_WITHDRAWN`, decreases the team's `booked_or_minutes` by that
    operation's `or_minutes`, and decreases its `scheduled_operation_count` by
    one".
    PRD 2.11: "Any forward action that adds to these ledgers has a compensating
    action that removes from them."

    Design: Difficulty/compensating_invariant/recovery_team_or_minutes_ledger_returns_to_zero_on_cancel
    """
    bundle = _liver_case_with_a_booked_theatre(env)

    cancelled = cancel_operation(env, bundle.operation["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "LOGISTICS_WITHDRAWN"

    assert_team_ledger(read_team(env, bundle.team["id"]), 0, 0)


def test_the_cancellation_touches_only_the_operating_room_ledger(env):
    """The organ stays accepted and the case stays allocated across the cancel.

    PRD 3.6: "the organ moves `OFFERING → ACCEPTED` with its `accepted_offer_id`
    set to the accepting offer".
    PRD 3.6: "The case's `allocation_status` advances `OFFERS_IN_FLIGHT →
    ALLOCATED` and its `organs_accepted_count` increases by one."

    Design: Difficulty/compensating_invariant/recovery_team_or_minutes_ledger_returns_to_zero_on_cancel
    """
    bundle = _liver_case_with_a_booked_theatre(env)
    cancel_operation(env, bundle.operation["id"])

    assert read_organ(env, bundle.only_organ_id)["status"] == "ACCEPTED"
    case = read_case(env, bundle.case_id)
    assert case["allocation_status"] == "ALLOCATED"
    assert case["organs_accepted_count"] == 1


# ---------------------------------------------------------------------------
# Conserved quantity two: the allocation slot ledger
# ---------------------------------------------------------------------------
def _run_of_three_candidates_over_two_slots(env):
    bundle = allocatable_organ(env, "LIVER", SLOT_CLOCK)
    bundle.run = open_match_run(
        env,
        bundle.only_organ_id,
        candidate_sequence(3, 240),
        primary_offer_slots=2,
    )
    bundle.refresh_offers()
    return bundle


def test_the_initial_fill_takes_both_slots_and_queues_the_third(env):
    """Two offers go pending, the third waits, and the ledger balances at two.

    PRD 3.6: "while the run's `pending_offer_count` is below its
    `primary_offer_slots` and the pool is non-empty, the ranked head is taken".
    PRD 2.11: "for each match run, `pending_offer_count` plus `slots_free`
    always equals `primary_offer_slots`".

    Design: Difficulty/compensating_invariant/allocation_slot_conservation_across_acceptance_withdrawal
    """
    bundle = _run_of_three_candidates_over_two_slots(env)

    assert find_offer(bundle.offers, 1)["status"] == "PENDING"
    assert find_offer(bundle.offers, 2)["status"] == "PENDING"
    assert find_offer(bundle.offers, 3)["status"] == "QUEUED"

    run = read_run(env, bundle.run_id)
    assert run["pending_offer_count"] == 2
    assert run["slots_free"] == 0
    assert_slot_conservation(run)


def test_acceptance_bypasses_the_peers_and_frees_every_slot(env):
    """The ledger swings to zero pending and two free without leaking a slot.

    PRD 3.6: "and every other offer on the run whose status is `QUEUED` or
    `PENDING` moves to `BYPASSED` with `bypass_reason` `PEER_ACCEPTED`. The run's
    `pending_offer_count` settles at zero and its `slots_free` at its
    `primary_offer_slots`."

    Design: Difficulty/compensating_invariant/allocation_slot_conservation_across_acceptance_withdrawal
    """
    bundle = _run_of_three_candidates_over_two_slots(env)

    respond_to_offer(env, bundle.run_id, find_offer(bundle.offers, 1)["id"], "ACCEPT")

    run = read_run(env, bundle.run_id)
    assert run["status"] == "CLOSED"
    assert run["pending_offer_count"] == 0
    assert run["slots_free"] == 2
    assert_slot_conservation(run)

    offers = list_offers(env, bundle.run_id)
    for position in (2, 3):
        peer = find_offer(offers, position)
        assert peer["status"] == "BYPASSED"
        assert peer["bypass_reason"] == "PEER_ACCEPTED"


def test_withdrawal_restores_the_peer_bypasses_and_refills_the_slots(env):
    """Unwinding the acceptance puts the ledger back where the fill left it.

    PRD 3.6: "Every offer on that run whose status is `BYPASSED` **and** whose
    `bypass_reason` is `PEER_ACCEPTED` is restored to `QUEUED` with
    `bypass_reason` cleared to null".
    PRD 3.6: "The promotion selector then re-runs, bringing `pending_offer_count`
    back up to the smaller of `primary_offer_slots` and the number of queued
    offers now available."
    PRD 3.6: "The case's `allocation_status` returns `ALLOCATED →
    OFFERS_IN_FLIGHT` and its `organs_accepted_count` decreases by one."

    Design: Difficulty/compensating_invariant/allocation_slot_conservation_across_acceptance_withdrawal
    """
    bundle = _run_of_three_candidates_over_two_slots(env)
    accepted_offer_id = find_offer(bundle.offers, 1)["id"]
    respond_to_offer(env, bundle.run_id, accepted_offer_id, "ACCEPT")

    respond_to_offer(env, bundle.run_id, accepted_offer_id, "WITHDRAW_ACCEPTANCE")

    run = read_run(env, bundle.run_id)
    assert run["status"] == "OPEN"
    assert run["closed_reason"] is None
    assert run["pending_offer_count"] == 2
    assert run["slots_free"] == 0
    assert_slot_conservation(run)

    offers = list_offers(env, bundle.run_id)
    assert find_offer(offers, 1)["status"] == "WITHDRAWN"
    for position in (2, 3):
        restored = find_offer(offers, position)
        assert restored["status"] == "PENDING"
        assert restored["bypass_reason"] is None

    organ = read_organ(env, bundle.only_organ_id)
    assert organ["status"] == "OFFERING"
    assert organ["accepted_offer_id"] is None

    case = read_case(env, bundle.case_id)
    assert case["allocation_status"] == "OFFERS_IN_FLIGHT"
    assert case["organs_accepted_count"] == 0
