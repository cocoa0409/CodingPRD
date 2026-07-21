"""Tournaments: qualifying-entry gate on finalize, ranking + prize award, the
IN_PROGRESS dependency for entry check-in, and duplicate-entry rejection.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    set_clock, new_customer, new_tournament, register_open_entry, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _zero_qualified_setup(api):
    """One entry CHECKED_IN with a single sub-threshold (non-qualifying) weigh-in."""
    set_clock("2026-07-20T08:00:00Z")
    cust = new_customer()
    t = new_tournament(species="BASS", start_at="2026-07-20T06:00:00Z",
                       end_at="2026-07-20T18:00:00Z", min_qualifying_weight_grams=1000)
    validate_success(api.set_tournament_status(t["id"], {"status": "OPEN"}, MANAGER), 200)
    entry = register_open_entry(t["id"], cust["id"])
    validate_success(api.set_tournament_status(t["id"], {"status": "IN_PROGRESS"}, MANAGER), 200)
    validate_success(api.set_entry_status(entry["id"], {"status": "CHECKED_IN"}, CLERK), 200)
    validate_success(api.weigh_in(entry["id"], {"species": "BASS", "weight_grams": 999}, CLERK), 200)
    return t, entry


# ─── Difficulty: boundary_precision_check / tournament_finalize_zero_qualified_entries_empty_set
def test_finalize_zero_qualified_rejected(api):
    """PRD §3.7: "Finalizing a tournament (IN_PROGRESS → FINALIZED) requires at least one
    qualifying entry — an entry in CHECKED_IN or WEIGHED whose best_weight_grams is at least
    the tournament's min_qualifying_weight_grams. If no entry qualifies, finalize is refused
    with ERR_NO_QUALIFIED_ENTRIES (HTTP 409)."

    Design: Difficulty/boundary_precision_check/tournament_finalize_zero_qualified_entries_empty_set
    """
    t, _ = _zero_qualified_setup(api)
    res = api.set_tournament_status(t["id"], {"status": "FINALIZED"}, MANAGER)
    validate_error(res, "ERR_NO_QUALIFIED_ENTRIES", 409)


def test_finalize_zero_qualified_leaves_tournament_in_progress(api):
    """PRD §3.7: "The best_weight_grams of an entry is the maximum weight among its weigh-ins
    that match the tournament's species, are at least the tournament's
    min_qualifying_weight_grams, and whose recorded_at falls at or after the tournament
    start_at and at or before its end_at; if none qualify, best_weight_grams is zero."

    Design: Difficulty/boundary_precision_check/tournament_finalize_zero_qualified_entries_empty_set
    """
    t, _ = _zero_qualified_setup(api)
    api.set_tournament_status(t["id"], {"status": "FINALIZED"}, MANAGER)
    refreshed = get_success_data(api.get_tournament(t["id"], MANAGER))
    assert refreshed["status"] == "IN_PROGRESS"


# ─── Difficulty: cross_entity_state_dependency / entry_checkin_requires_tournament_in_progress
def test_entry_checkin_while_open_rejected(api):
    """PRD §3.7: "An angler or clerk checks an entry in (REGISTERED → CHECKED_IN), which is
    only permitted while the tournament is IN_PROGRESS; attempting it otherwise yields
    ERR_TOURNAMENT_NOT_IN_PROGRESS."

    Design: Difficulty/cross_entity_state_dependency/entry_checkin_requires_tournament_in_progress
    """
    cust = new_customer()
    t = new_tournament(species="CRAPPIE", start_at="2026-07-25T06:00:00Z",
                       end_at="2026-07-25T18:00:00Z", min_qualifying_weight_grams=500)
    validate_success(api.set_tournament_status(t["id"], {"status": "OPEN"}, MANAGER), 200)
    entry = register_open_entry(t["id"], cust["id"])
    res = api.set_entry_status(entry["id"], {"status": "CHECKED_IN"}, CLERK)
    validate_error(res, "ERR_TOURNAMENT_NOT_IN_PROGRESS", 409)


def test_entry_checkin_succeeds_once_in_progress(api):
    """PRD §3.7: "An angler or clerk checks an entry in (REGISTERED → CHECKED_IN), which is
    only permitted while the tournament is IN_PROGRESS; attempting it otherwise yields
    ERR_TOURNAMENT_NOT_IN_PROGRESS."

    Design: Difficulty/cross_entity_state_dependency/entry_checkin_requires_tournament_in_progress
    """
    cust = new_customer()
    t = new_tournament(species="CRAPPIE", start_at="2026-07-25T06:00:00Z",
                       end_at="2026-07-25T18:00:00Z", min_qualifying_weight_grams=500)
    validate_success(api.set_tournament_status(t["id"], {"status": "OPEN"}, MANAGER), 200)
    entry = register_open_entry(t["id"], cust["id"])
    validate_success(api.set_tournament_status(t["id"], {"status": "IN_PROGRESS"}, MANAGER), 200)
    checked = validate_success(api.set_entry_status(entry["id"], {"status": "CHECKED_IN"}, CLERK), 200)
    assert checked["status"] == "CHECKED_IN"


# ─── Corner: state_machines / tournament_finalize_ranks_winner_and_awards_prize_points
def test_finalize_ranks_winner_and_awards_prize(api):
    """PRD §3.7: "On finalize, the qualifying entries are ranked and each is assigned a
    one-based final_rank: primarily by best_weight_grams descending... The rank-one entry
    advances WEIGHED → WINNER, and its customer is awarded the tournament's prize_points:
    those points are added to the customer's loyalty_points_balance and to their
    lifetime_points_earned, and the tier is recomputed."

    Design: Corner/state_machines/tournament_finalize_ranks_winner_and_awards_prize_points
    """
    set_clock("2026-07-22T08:00:00Z")
    c1 = new_customer(date_of_birth="1990-01-01")
    c2 = new_customer(date_of_birth="1991-01-01")
    t = new_tournament(name="Bass Blitz", species="BASS", start_at="2026-07-22T06:00:00Z",
                       end_at="2026-07-22T18:00:00Z", min_qualifying_weight_grams=1000,
                       prize_points=300)
    validate_success(api.set_tournament_status(t["id"], {"status": "OPEN"}, MANAGER), 200)
    e1 = register_open_entry(t["id"], c1["id"])
    e2 = register_open_entry(t["id"], c2["id"])
    validate_success(api.set_tournament_status(t["id"], {"status": "IN_PROGRESS"}, MANAGER), 200)
    validate_success(api.set_entry_status(e1["id"], {"status": "CHECKED_IN"}, CLERK), 200)
    validate_success(api.set_entry_status(e2["id"], {"status": "CHECKED_IN"}, CLERK), 200)
    validate_success(api.weigh_in(e1["id"], {"species": "BASS", "weight_grams": 5000}, CLERK), 200)
    validate_success(api.weigh_in(e2["id"], {"species": "BASS", "weight_grams": 4000}, CLERK), 200)
    validate_success(api.set_tournament_status(t["id"], {"status": "FINALIZED"}, MANAGER), 200)

    e1_final = get_success_data(api.get_entry(e1["id"], MANAGER))
    e2_final = get_success_data(api.get_entry(e2["id"], MANAGER))
    assert e1_final["final_rank"] == 1
    assert e1_final["status"] == "WINNER"
    assert e2_final["final_rank"] == 2
    assert get_success_data(api.get_customer(c1["id"], MANAGER))["loyalty_points_balance"] == 300


# ─── Corner: state_machines / duplicate_tournament_entry_rejected
def test_duplicate_entry_rejected(api):
    """PRD §3.7: "A customer may not hold two live entries in the same tournament — if they
    already have an entry in REGISTERED, CHECKED_IN, WEIGHED, or WINNER, a second registration
    is refused with ERR_DUPLICATE_ENTRY (HTTP 409)."

    Design: Corner/state_machines/duplicate_tournament_entry_rejected
    """
    cust = new_customer()
    t = new_tournament(species="BASS", start_at="2026-07-26T06:00:00Z",
                       end_at="2026-07-26T18:00:00Z", min_qualifying_weight_grams=500)
    validate_success(api.set_tournament_status(t["id"], {"status": "OPEN"}, MANAGER), 200)
    register_open_entry(t["id"], cust["id"])
    res = api.create_entry({"tournament_id": t["id"], "customer_id": cust["id"]}, CLERK)
    validate_error(res, "ERR_DUPLICATE_ENTRY", 409)
