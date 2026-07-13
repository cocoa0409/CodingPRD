"""Event lifecycle, tip-pool distribution at close, and revenue reconciliation."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    setup_two_shift_event, setup_checked_in_ticket, setup_settled_ticket,
    create_venue, create_active_event,
)

SUP = TEST_USERS["supervisor_headers"]


def test_weighted_split_first_shift_share(api):
    """PRD §3.4: "Under the `WEIGHTED` split mode, each shift's provisional share is the pool
    multiplied by that shift's hours and divided by the total hours across all the shifts, then
    rounded down to a whole cent, where a shift's hours is its duration from `start_at` to
    `end_at` expressed in hours (seconds elapsed divided by 3600 seconds per hour)."
    PRD §3.4: "the remainder ... is distributed one cent at a time to the shifts in `created_at`
    ascending order, so the earliest-created shifts each receive one extra cent".

    Design: Difficulty/dual_variant_calc/tip_split_weighted_vs_equal_on_shift
    """
    # pool 1501 over 4h/6h: floor(1501*4/10)=600, floor(1501*6/10)=900, remainder 1 → s1=601.
    env = setup_two_shift_event("WEIGHTED", "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z", 700, 801)
    validate_success(api.close_event(env["event"]["id"], SUP), 200)
    s1 = validate_success(api.get_shift(env["s1"]["id"], SUP), 200)
    assert s1["allocated_tip_cents"] == 601


def test_weighted_split_second_shift_share(api):
    """PRD §3.4: "Under the `WEIGHTED` split mode, each shift's provisional share is the pool
    multiplied by that shift's hours and divided by the total hours across all the shifts, then
    rounded down to a whole cent, where a shift's hours is its duration from `start_at` to
    `end_at` expressed in hours (seconds elapsed divided by 3600 seconds per hour)."

    Design: Difficulty/dual_variant_calc/tip_split_weighted_vs_equal_on_shift
    """
    # pool 1501 over 4h/6h: floor(1501*6/10)=900 (remainder cent goes to the earlier shift).
    env = setup_two_shift_event("WEIGHTED", "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z", 700, 801)
    validate_success(api.close_event(env["event"]["id"], SUP), 200)
    s2 = validate_success(api.get_shift(env["s2"]["id"], SUP), 200)
    assert s2["allocated_tip_cents"] == 900


def test_equal_split_gives_remainder_to_earliest_shift(api):
    """PRD §3.4: "Under the `EQUAL` split mode, each of the n shifts receives the pool divided
    by n and rounded down to a whole cent."
    PRD §3.4: "the remainder — the pool minus the sum of the floored shares, which is never
    negative — is distributed one cent at a time to the shifts in `created_at` ascending order,
    so the earliest-created shifts each receive one extra cent until the remainder is exhausted".

    Design: Difficulty/combinatorial_formula/tip_remainder_floor_then_created_at_mode_b
    """
    # pool 1501 EQUAL over 2 shifts: floor(1501/2)=750 each, remainder 1 → earliest s1=751.
    env = setup_two_shift_event("EQUAL", "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z", 700, 801)
    validate_success(api.close_event(env["event"]["id"], SUP), 200)
    s1 = validate_success(api.get_shift(env["s1"]["id"], SUP), 200)
    assert s1["allocated_tip_cents"] == 751


def test_equal_split_later_shift_gets_floor(api):
    """PRD §3.4: "Under the `EQUAL` split mode, each of the n shifts receives the pool divided
    by n and rounded down to a whole cent."

    Design: Difficulty/combinatorial_formula/tip_remainder_floor_then_created_at_mode_b
    """
    # pool 1501 EQUAL over 2 shifts: floor(1501/2)=750; the later-created shift keeps the floor.
    env = setup_two_shift_event("EQUAL", "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z", 700, 801)
    validate_success(api.close_event(env["event"]["id"], SUP), 200)
    s2 = validate_success(api.get_shift(env["s2"]["id"], SUP), 200)
    assert s2["allocated_tip_cents"] == 750


def test_activate_already_active_event_rejected(api):
    """PRD §3.1: "Activation advances the event from `SCHEDULED` to `ACTIVE`, which opens it
    for check-ins; activation attempted on an event not in `SCHEDULED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_event_returns_invalid_state
    """
    venue = create_venue()
    event = create_active_event(venue["id"])
    res = api.activate_event(event["id"], SUP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_close_event_with_parked_ticket_rejected(api):
    """PRD §3.1: "Closing has two preconditions: the event must currently be `ACTIVE`, and no
    ticket of the event may still be physically on the floor — that is, no ticket may have
    `park_status` of `PARKED` or `RETRIEVED`. If either precondition fails, the close is
    rejected with `ERR_EVENT_NOT_CLOSABLE`."

    Design: Corner/state_machines/close_event_with_parked_ticket_returns_not_closable
    """
    env = setup_checked_in_ticket()  # ticket PARKED
    res = api.close_event(env["event"]["id"], SUP)
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_CLOSABLE)


def test_reconciliation_expected_revenue_and_variance(api):
    """PRD §3.9: "The `expected_revenue_cents` is the sum of `net_charge_cents` across the
    event's tickets whose `settlement_status` is `SETTLED`."
    PRD §3.9: "fixes the `variance_cents` as the declared cash minus the difference of expected
    revenue and the liability adjustment — that is, `declared_cash_cents` minus the quantity
    (`expected_revenue_cents` minus `liability_adjustment_cents`)."

    Design: Corner/calculations/reconciliation_expected_revenue_and_variance
    """
    env = setup_settled_ticket()  # one ticket checked out at 12:30, net 2900, SETTLED
    validate_success(api.close_event(env["event"]["id"], SUP), 200)
    report = validate_success(api.create_reconciliation_report(
        {"event_id": env["event"]["id"]}, SUP), 201)
    assert report["expected_revenue_cents"] == 2900
    final = validate_success(api.finalize_reconciliation_report(
        report["id"], {"declared_cash_cents": 3000}, SUP), 200)
    assert final["variance_cents"] == 100  # 3000 - (2900 - 0)
