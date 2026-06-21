"""Move-out cascade: proration recompute, conservation, and terminal lockdown.

Translates queue-A transitive_cascade (move-out -> proration -> splits -> net
balances -> ledger_sum stays 0). Per-member prorated shares and occupied-day
counts depend on move_in_date / planned_move_out_date provenance, which the PRD
does not pin to a single value a PRD-only reader could derive; those assertions
are therefore omitted and only the PRD-guaranteed conserved quantities are
checked. Also translates the queue-B terminal-state lockdown corner instance.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_roommate_headers,
    build_household_with_members,
    issue_rent_bill,
    set_clock,
    assert_ledger_conserved,
)

api = api_client


def test_moveout_recomputes_splits_keeping_bill_total_conserved():
    """PRD §3.5: "Throughout, the bill's `total_amount_cents` continues to equal the sum
    of all `share_cents`."

    Design: Difficulty/transitive_cascade/moveout_cascade_proration_splits_balances
    """
    env = build_household_with_members(
        api, [{"full_name": "M1.7"}, {"full_name": "M2.7"}],
        listing_overrides={"split_policy": "EQUAL", "capacity": 3},
        clock="2026-06-01T00:00:00.000Z",
    )
    lh = make_roommate_headers(env["lister"]["id"])
    m2 = env["members"][1]
    mem2 = env["memberships"][1]
    bill = issue_rent_bill(api, env, total_amount_cents=200_000)

    set_clock(api, "2026-06-15T00:00:00.000Z")
    moved = validate_success(api.move_out_membership(mem2["id"], make_roommate_headers(m2["id"])))
    assert moved["status"] == "MOVED_OUT"

    splits = validate_success(api.list_bill_splits(bill["id"], lh))
    assert sum(s["share_cents"] for s in splits) == 200_000


def test_moveout_cascade_keeps_ledger_sum_zero():
    """PRD §3.5: "Once the splits are settled, every member's `net_balance_cents` is
    recomputed and the household's `ledger_sum_cents` is confirmed to remain zero."
    PRD §2.6: "After every ledger-mutating operation — logging or voting an expense,
    confirming a settlement, resolving a dispute that adjusts an expense, or moving a
    member out — `ledger_sum_cents` must come back to exactly zero."

    Design: Difficulty/transitive_cascade/moveout_cascade_proration_splits_balances
    """
    env = build_household_with_members(
        api, [{"full_name": "C1"}, {"full_name": "C2"}],
        listing_overrides={"split_policy": "EQUAL", "capacity": 3},
        clock="2026-06-01T00:00:00.000Z",
    )
    lh = make_roommate_headers(env["lister"]["id"])
    m2 = env["members"][1]
    mem2 = env["memberships"][1]
    issue_rent_bill(api, env, total_amount_cents=200_000)

    set_clock(api, "2026-06-15T00:00:00.000Z")
    validate_success(api.move_out_membership(mem2["id"], make_roommate_headers(m2["id"])))

    assert_ledger_conserved(validate_success(api.get_household(env["household"]["id"], lh)))


def test_second_moveout_on_moved_out_membership_is_invalid_state():
    """PRD §3.3: "a `status` of `PENDING`, `ACTIVE`, or `MOVED_OUT`, where `PENDING` is
    the entry state and `MOVED_OUT` is terminal."
    PRD §3.2: "an action requested from a state where it is not defined is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/move_out_already_moved_out_terminal_lockdown
    """
    env = build_household_with_members(
        api, [{"full_name": "TermM"}],
        listing_overrides={"capacity": 3},
        clock="2026-06-01T00:00:00.000Z",
    )
    m1 = env["members"][0]
    mem1 = env["memberships"][0]
    set_clock(api, "2026-06-15T00:00:00.000Z")
    validate_success(api.move_out_membership(mem1["id"], make_roommate_headers(m1["id"])))

    resp = api.move_out_membership(mem1["id"], make_roommate_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
