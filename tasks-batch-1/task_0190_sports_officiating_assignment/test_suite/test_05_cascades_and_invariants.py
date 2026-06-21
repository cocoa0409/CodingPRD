"""Cyclic state machines, depth-2/3 cascades, and conserved-quantity invariants
(crew count, money, penalty points) across decline/no-show/cancel/settle/appeal.

Each test translates exactly one design instance (Difficulty queue A or Corner queue B).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_game_payload, create_crew_slot_payload, create_appeal_payload,
    TEST_USERS, make_official_headers,
    create_league, create_official, create_wide_availability,
    offer_slot, accept_assignment, decline_assignment,
    current_game_version, set_clock, lock_game,
    setup_accepted_assignment, get_season_ledger,
)

ADMIN = TEST_USERS["league_admin_headers"]
ASSIGNOR = TEST_USERS["assignor_headers"]


# ─── Non-linear / cyclic state machine (Difficulty) ──────────────────────────

def test_crewslot_cyclic_reoffer_after_decline(api):
    """PRD §3.6: "The slot then returns from `OFFERED` to `VACANT`, its
    `current_assignment_id` is cleared, and it becomes offerable again — the cyclic
    re-offer loop that lets a slot be put back on the market."
    PRD §3.4: "When it succeeds, the system creates an assignment in `OFFERED`, sets
    the slot's `current_assignment_id`, advances the slot from `VACANT` to
    `OFFERED`".

    Design: Difficulty/non_linear_state_machine/crewslot_cyclic_reoffer_after_decline
    """
    league = create_league(sport="BASKETBALL")
    oa = create_official(league["id"], full_name="A", rank="ROOKIE")
    ob = create_official(league["id"], full_name="B", rank="ROOKIE")
    create_wide_availability(oa["id"])
    create_wide_availability(ob["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-20T18:00:00Z"), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    a1 = offer_slot(slot["id"], oa["id"], game["id"])
    decline_assignment(a1["id"], oa["id"])  # slot back to VACANT
    a2 = offer_slot(slot["id"], ob["id"], game["id"])  # fresh offer on the SAME slot
    slot_after = validate_success(api.get_crew_slot(slot["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "OFFERED"
    assert slot_after["current_assignment_id"] == a2["id"]
    a1_after = validate_success(api.get_assignment(a1["id"], ASSIGNOR), 200)
    a2_after = validate_success(api.get_assignment(a2["id"], ASSIGNOR), 200)
    assert a1_after["status"] == "DECLINED"
    assert a2_after["status"] == "OFFERED"


def test_game_staffed_bubbles_open_on_withdraw(api):
    """PRD §2.5: "if that count reaches the game's `required_crew_size` — the game
    automatically advances from `OPEN` to `STAFFED` without any explicit request on
    the game itself. Conversely, when a filled slot is vacated by a decline,
    no-show, withdrawal, or cancellation, `crew_filled_count` is recomputed
    downward, and if it falls below `required_crew_size` the game automatically
    bubbles from `STAFFED` back to `OPEN` so the slot can be re-offered."
    PRD §3.6: "A withdrawal is treated as a late decline: it advances the assignment
    `ACCEPTED → CANCELLED`, assesses the same decline-penalty calculation into
    `penalty_assessed_points`, adds it to `SeasonLedger.penalty_points`, returns the
    slot to `VACANT`, recomputes `crew_filled_count`, and may bubble the game
    `STAFFED → OPEN`."

    Design: Difficulty/non_linear_state_machine/game_parallel_dimensions_staffed_bubbles_open_on_withdraw
    """
    ctx = setup_accepted_assignment()  # ROOKIE on ASSISTANT, game auto-STAFFED
    assert ctx["game"]["status"] == "STAFFED"
    validate_success(api.withdraw_assignment(
        ctx["assignment"]["id"], make_official_headers(ctx["official"]["id"])), 200)
    game_after = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert game_after["status"] == "OPEN"
    assert game_after["crew_filled_count"] == 0
    slot_after = validate_success(api.get_crew_slot(ctx["slot"]["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "VACANT"
    asg_after = validate_success(api.get_assignment(ctx["assignment"]["id"], ASSIGNOR), 200)
    assert asg_after["status"] == "CANCELLED"


# ─── Transitive cascades (Difficulty) ────────────────────────────────────────

def test_noshow_cascade_depth3(api):
    """PRD §3.7: "A no-show advances the assignment `ACCEPTED → NO_SHOW`, computes a
    no-show penalty into `penalty_assessed_points` (see §3.9), adds it to
    `SeasonLedger.penalty_points`, and recomputes the official's `noshow_count`,
    `penalty_points`, and `reliability_score`."
    PRD §3.7: "The slot returns to `VACANT` and `crew_filled_count` is recomputed; if
    the game was `STAFFED` it may bubble back to `OPEN`, whereas a `LOCKED` game
    simply remains `LOCKED` carrying a now-vacant slot."
    PRD §3.8: "The **no-show penalty** (applied when an accepted assignment becomes
    a no-show) starts from a base of 15 points."

    Design: Difficulty/transitive_cascade/noshow_cascade_assignment_slot_game_depth3
    """
    ctx = setup_accepted_assignment(game_overrides={"start_utc": "2026-06-20T18:00:00Z"})
    set_clock("2026-06-20T19:00:00Z")  # past start so no-show is permitted
    no_show = validate_success(api.no_show_assignment(ctx["assignment"]["id"], ASSIGNOR), 200)
    assert no_show["status"] == "NO_SHOW"
    assert no_show["penalty_assessed_points"] == 15  # base 15, no prior, regular game
    slot_after = validate_success(api.get_crew_slot(ctx["slot"]["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "VACANT"
    game_after = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert game_after["status"] == "OPEN"
    assert game_after["crew_filled_count"] == 0


def test_game_cancel_cascade_depth2(api):
    """PRD §3.10: "Cancellation drives the game to `CANCELLED`, moves every
    non-terminal assignment on the game to `CANCELLED` with no penalty assessed,
    releases every crew slot to `RELEASED`, and increments the game's `version` by
    one."

    Design: Difficulty/transitive_cascade/game_cancel_cascade_slot_and_assignment_depth2
    """
    ctx = setup_accepted_assignment()  # game STAFFED with a FILLED slot
    cancelled = validate_success(api.cancel_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert cancelled["status"] == "CANCELLED"
    slot_after = validate_success(api.get_crew_slot(ctx["slot"]["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "RELEASED"
    asg_after = validate_success(api.get_assignment(ctx["assignment"]["id"], ASSIGNOR), 200)
    assert asg_after["status"] == "CANCELLED"
    assert asg_after["penalty_assessed_points"] == 0  # no penalty on cancel


# ─── Compensating invariants (Difficulty) ────────────────────────────────────

def test_decline_then_reoffer_accept_conserves_crew_count(api):
    """PRD §2.5: "When an official accepts an offer, the slot becomes filled, the
    owning game's `crew_filled_count` is recomputed, and — if that count reaches the
    game's `required_crew_size` — the game automatically advances from `OPEN` to
    `STAFFED`".
    PRD §3.6: "The slot then returns from `OFFERED` to `VACANT`, its
    `current_assignment_id` is cleared, and it becomes offerable again".

    Design: Difficulty/compensating_invariant/decline_then_reoffer_accept_conserves_crew_count
    """
    league = create_league(sport="BASKETBALL")
    oa = create_official(league["id"], full_name="A", rank="ROOKIE")
    ob = create_official(league["id"], full_name="B", rank="ROOKIE")
    create_wide_availability(oa["id"])
    create_wide_availability(ob["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    a1 = offer_slot(slot["id"], oa["id"], game["id"])
    decline_assignment(a1["id"], oa["id"])  # crew_filled_count stays 0
    a2 = offer_slot(slot["id"], ob["id"], game["id"])
    accept_assignment(a2["id"], ob["id"], game["id"])  # back to required_crew_size
    game_after = validate_success(api.get_game(game["id"], ASSIGNOR), 200)
    assert game_after["crew_filled_count"] == 1
    assert game_after["status"] == "STAFFED"
    slot_after = validate_success(api.get_crew_slot(slot["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "FILLED"


def test_settle_conserves_pay_ledger(api):
    """PRD §3.9: "It advances the game `LOCKED → COMPLETED`, drives each filled
    slot's `ACCEPTED` assignment to `COMPLETED` with its `final_pay_cents` computed,
    accrues those amounts into the season ledgers, recomputes the game's
    `settlement_total_cents`".
    PRD §3.9: "each official's `SeasonLedger.total_pay_accrued_cents` increases by
    the sum of their settled `final_pay_cents`".

    Design: Difficulty/compensating_invariant/settle_conserves_pay_ledger_equals_sum_of_final_pay
    """
    league = create_league(sport="HOCKEY", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=0)
    official = create_official(league["id"], rank="SENIOR")
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    accept_assignment(asg["id"], official["id"], game["id"])
    lock_game(game["id"])
    set_clock("2026-06-20T19:00:00Z")
    gv = current_game_version(game["id"])
    settled_game = validate_success(api.settle_game(
        game["id"], {"expected_game_version": gv}, ASSIGNOR), 200)
    settled_asg = validate_success(api.get_assignment(asg["id"], ASSIGNOR), 200)
    assert settled_asg["final_pay_cents"] == 15000  # SENIOR base 15000, mileage 0
    assert settled_game["settlement_total_cents"] == 15000
    ledger = get_season_ledger(league["id"], official["id"])
    assert ledger["total_pay_accrued_cents"] == 15000


def test_appeal_upheld_conserves_penalty_points(api):
    """PRD §3.13: "Upholding sets `reversed_points` to the appealed assignment's
    `penalty_assessed_points`, subtracts that figure from the official's
    `SeasonLedger.penalty_points` (floored at 0), and recomputes the official's
    `penalty_points` and `reliability_score`."
    PRD §3.7: "It is 100 minus the season ledger's `penalty_points`, floored at 0".

    Design: Difficulty/compensating_invariant/appeal_upheld_conserves_penalty_points_ledger
    """
    league = create_league(sport="BASKETBALL")
    official = create_official(league["id"], rank="ROOKIE")
    create_wide_availability(official["id"])
    set_clock("2026-06-20T16:00:00Z")  # 2h before start => late tier => penalty 8
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-20T18:00:00Z"), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    declined = decline_assignment(asg["id"], official["id"])
    assert declined["penalty_assessed_points"] == 8
    appeal = validate_success(api.create_appeal(
        asg["id"], create_appeal_payload(reason="venue double-booked by league error"),
        make_official_headers(official["id"])), 201)
    upheld = validate_success(api.uphold_appeal(appeal["id"], ADMIN), 200)
    assert upheld["status"] == "UPHELD"
    assert upheld["reversed_points"] == 8
    ledger = get_season_ledger(league["id"], official["id"])
    assert ledger["penalty_points"] == 0
    official_after = validate_success(api.get_official(official["id"], ADMIN), 200)
    assert official_after["reliability_score"] == 100
