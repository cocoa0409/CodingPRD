"""The bread-and-cookie club: the reserved share cap, the pause cap, the skip
deadline, the arrears loop and the cycle-confirmation OCC."""
from test_helpers import (
    ApiErrorId,
    CLOCK_ORDERING_TIME,
    api_client,
    assert_rejected,
    assert_same_instant,
    assert_subscription_cycle,
    generate_cycle,
    instant_plus,
    lock_window,
    read_capacity,
    read_cycle,
    read_order,
    read_subscription,
    read_window,
    set_clock,
    setup_active_club,
    setup_reserved_cycle,
    subscription_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_third_club_cycle_lands_exactly_on_the_share_cap(api):
    """PRD §3.6: "Reservation is bounded by a **club share cap** of 30 percent of the
    window's `capacity_units`, rounded **down** to a whole unit: with the default
    capacity of 240 units the cap is 72, so a third weekly cycle of 24 units lands
    exactly on 72 and is admitted, while a fourth is refused at rung 52 with
    `ERR_SUBSCRIPTION_RESERVE_SHARE_EXCEEDED` — the comparison is strictly greater,
    so landing exactly on the cap is legal."
    PRD §3.6: "The reservation sets the cycle's `reserved_units` to the full
    `units_per_cycle`, its `cycle_price_cents`, and its `skip_deadline_at`, which is
    the window's `order_cutoff_at` less **24 hours**; it adds the reserved units to
    the window's `reserved_units`, recomputes `capacity_posture`, and bumps the
    window's `version`."

    Design: Difficulty/boundary_precision_check/subscription_reserve_share_admits_exactly_the_cap
    """
    s = setup_active_club(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    first = generate_cycle(s, 1)
    second = generate_cycle(s, 2)
    third = generate_cycle(s, 3)

    assert_subscription_cycle(first)
    assert first["reserved_units"] == 24
    assert first["cycle_price_cents"] == 9550, (
        "24 units under the baker's-dozen basis: 4600 plus eleven units at 450"
    )
    for cycle in (first, second, third):
        assert read_cycle(cycle["id"], s.bh)["cycle_status"] == "RESERVED"

    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["reserved_units"] == 72, "exactly floor(240 * 0.30)"
    assert capacity["units_remaining"] == 168
    assert capacity["capacity_posture"] == "OPEN_CAPACITY", (
        "72/240 == 0.30 is below the 0.80 threshold"
    )
    _, meta = validate_paginated(
        api.list_subscription_cycles(s.bh, {"subscription_id": s.subscription_id})
    )
    assert meta["total_count"] == 3


def test_a_fourth_club_cycle_exceeds_the_share_cap(api):
    """PRD §2.6: "Rung 52: the window's `reserved_units` plus the subscription's
    `units_per_cycle` does not exceed the club's share cap, which is the window's
    `capacity_units` multiplied by 0.30 and rounded **down** to a whole unit,
    otherwise `ERR_SUBSCRIPTION_RESERVE_SHARE_EXCEEDED` (422) on club-cycle
    generation."
    PRD §3.6: "with the default capacity of 240 units the cap is 72, so a third
    weekly cycle of 24 units lands exactly on 72 and is admitted, while a fourth is
    refused at rung 52 with `ERR_SUBSCRIPTION_RESERVE_SHARE_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/subscription_reserve_share_admits_exactly_the_cap
    """
    s = setup_active_club(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    generate_cycle(s, 1)
    generate_cycle(s, 2)
    generate_cycle(s, 3)

    rejected = api.generate_cycle(
        s.subscription_id, {"offer_window_id": s.window_id, "sequence_number": 4}, s.bh
    )
    validate_error(rejected, ApiErrorId.ERR_SUBSCRIPTION_RESERVE_SHARE_EXCEEDED)

    _, meta = validate_paginated(
        api.list_subscription_cycles(s.bh, {"subscription_id": s.subscription_id})
    )
    assert meta["total_count"] == 3
    assert read_capacity(s.window_id, s.bh)["reserved_units"] == 72


def test_locking_the_window_releases_a_reserved_club_cycle(api):
    """PRD §3.4: "**Locking is the system's largest single sweep.** Every order on
    the window sitting in `PENDING_HOLD` moves to `EXPIRED_HOLD` and each of its
    `PENDING` lines moves to `RELEASED`; every club cycle on the window sitting in
    `RESERVED` moves to `RELEASED` with its `reserved_units` dropping to 0;
    `held_units`, `reserved_units`, and `capacity_posture` are all recomputed; and
    the window's `version` is bumped."

    Design: Corner/state_machines/window_lock_releases_reserved_subscription_cycles
    """
    s = setup_reserved_cycle(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    assert s.cycle["reserved_units"] == 24
    assert read_window(s.window_id, s.bh)["reserved_units"] == 24

    locked = lock_window(s)
    assert locked["reserved_units"] == 0

    cycle = read_cycle(s.cycle_id, s.bh)
    assert cycle["cycle_status"] == "RELEASED"
    assert cycle["reserved_units"] == 0
    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["units_remaining"] == 240
    assert capacity["reserved_units"] == 0


def test_a_third_pause_exceeds_the_club_pause_cap(api):
    """PRD §2.6: "Rung 43: the subscription's `pause_count` is below the pause cap of
    2, otherwise `ERR_PAUSE_CAP_EXCEEDED` (409) on a status change to `PAUSED`."
    PRD §3.6: "An `ACTIVE` membership may be paused only while `pause_count` is
    below **2**; the pause increments `pause_count`, moves every cycle of this
    membership that is `RESERVED` to `RELEASED` — dropping the corresponding units
    out of the window's `reserved_units` — and bumps the `version`."
    PRD §3.6: "A third pause attempt is refused at rung 43 with
    `ERR_PAUSE_CAP_EXCEEDED`."

    Design: Corner/state_machines/subscription_pause_cap_exceeded_on_third_pause
    """
    s = setup_active_club(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    validate_success(
        api.set_subscription_status(s.subscription_id, {"to_status": "PAUSED"}, s.ch)
    )
    validate_success(
        api.set_subscription_status(s.subscription_id, {"to_status": "ACTIVE"}, s.ch)
    )
    second_pause = validate_success(
        api.set_subscription_status(s.subscription_id, {"to_status": "PAUSED"}, s.ch)
    )
    assert second_pause["pause_count"] == 2
    validate_success(
        api.set_subscription_status(s.subscription_id, {"to_status": "ACTIVE"}, s.ch)
    )

    rejected = api.set_subscription_status(
        s.subscription_id, {"to_status": "PAUSED"}, s.ch
    )
    validate_error(rejected, ApiErrorId.ERR_PAUSE_CAP_EXCEEDED)

    after = read_subscription(s.subscription_id, s.ch)
    assert after["sub_status"] == "ACTIVE"
    assert after["pause_count"] == 2


def test_skipping_at_the_skip_deadline_instant_is_refused(api):
    """PRD §2.6: "Rung 40: the current instant is strictly before the cycle's
    `skip_deadline_at`, otherwise `ERR_SKIP_DEADLINE_PASSED` (409) on a cycle skip."
    PRD §3.6: "A buyer may skip a `RESERVED` cycle while the current instant is
    strictly before its `skip_deadline_at`; the skip releases `reserved_units` back
    to the window, recomputes the window's `reserved_units` and `capacity_posture`,
    and bumps the cycle's `version`."
    PRD §3.6: "its `skip_deadline_at`, which is the window's `order_cutoff_at` less
    **24 hours**"

    Design: Corner/validations/skipping_after_the_skip_deadline_is_rejected
    """
    s = setup_reserved_cycle(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    assert_same_instant(
        s.cycle["skip_deadline_at"],
        instant_plus("2026-05-06T12:00:00Z", hours=-24),
        "skip_deadline_at",
    )

    set_clock("2026-05-05T12:00:00Z")
    rejected = api.skip_cycle(s.cycle_id, s.ch)
    validate_error(rejected, ApiErrorId.ERR_SKIP_DEADLINE_PASSED)

    cycle = read_cycle(s.cycle_id, s.ch)
    assert cycle["cycle_status"] == "RESERVED"
    assert cycle["reserved_units"] == 24
    assert read_window(s.window_id, s.bh)["reserved_units"] == 24


def test_a_stale_subscription_version_blocks_the_cycle_confirmation(api):
    """PRD §2.7: "`POST /bakery/subscription-cycles/{subscription_cycle_id}/confirm`
    requires `expected_subscription_version`, carrying the client's last observed
    `version` of the owning `Subscription`. A mismatch is rejected with
    `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."
    PRD §3.6: "The confirmation moves the cycle to `CONFIRMED` and then, at the end
    of the same request, on to `ORDER_PLACED`, creating along the way a club order:
    `source` `SUBSCRIPTION_CLUB`, `prepaid` set from whether the membership's billing
    mode is `PREPAID`, `handoff_mode` inherited from the membership, `order_status`
    `CONFIRMED`, and exactly one order line of `units_per_cycle` units in `PENDING`."
    PRD §3.6: "The reserved units move out of the window's `reserved_units` and into
    its `confirmed_units`"

    Design: Corner/cross_cutting_layers/stale_subscription_version_blocks_cycle_confirmation
    """
    s = setup_reserved_cycle(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    fresh = subscription_version(s.subscription_id, s.ch)

    rejected = api.confirm_cycle(
        s.cycle_id, {"expected_subscription_version": fresh - 1}, s.ch
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION)

    accepted = validate_success(
        api.confirm_cycle(s.cycle_id, {"expected_subscription_version": fresh}, s.ch)
    )
    assert accepted["cycle_status"] == "ORDER_PLACED"

    orders, meta = validate_paginated(
        api.list_orders(s.ch, {"subscription_cycle_id": s.cycle_id})
    )
    assert meta["total_count"] == 1
    assert orders[0]["source"] == "SUBSCRIPTION_CLUB"
    assert orders[0]["order_status"] == "CONFIRMED"

    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["reserved_units"] == 0
    assert capacity["confirmed_units"] == 24


def test_a_cycle_confirm_is_refused_while_the_membership_is_past_due(api):
    """PRD §3.6: "Confirming a `RESERVED` cycle is the buyer's commitment, and it
    requires the membership to be `ACTIVE`, the window to be `OPEN`, the cutoff still
    ahead, and the echoed `expected_subscription_version` to match."
    PRD §2.6: "All of these are genuine, enforced preconditions: a request that
    fails one is rejected and nothing is mutated."

    The specification does not settle which identifier such a rejection carries, so
    only the rejection and the absence of any mutation are asserted here.

    Design: Difficulty/cross_entity_state_dependency/cycle_confirm_blocked_by_subscription_in_past_due
    """
    s = setup_reserved_cycle(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    first = validate_success(
        api.confirm_cycle(
            s.cycle_id,
            {"expected_subscription_version": subscription_version(s.subscription_id, s.ch)},
            s.ch,
        )
    )
    assert first["cycle_status"] == "ORDER_PLACED"
    second_cycle = generate_cycle(s, 2)
    validate_success(
        api.set_subscription_status(s.subscription_id, {"to_status": "PAST_DUE"}, s.bh)
    )

    rejected = api.confirm_cycle(
        second_cycle["id"],
        {"expected_subscription_version": subscription_version(s.subscription_id, s.ch)},
        s.ch,
    )
    assert_rejected(rejected, "confirming a cycle of a PAST_DUE membership")

    assert read_cycle(second_cycle["id"], s.ch)["cycle_status"] == "RESERVED"
    _, meta = validate_paginated(
        api.list_orders(s.ch, {"subscription_cycle_id": second_cycle["id"]})
    )
    assert meta["total_count"] == 0


def test_the_arrears_loop_latches_past_due_on_an_unpaid_placed_cycle(api):
    """PRD §3.6: "The operator moves an `ACTIVE` membership to `PAST_DUE` when at
    least one of its cycles sitting in `ORDER_PLACED` has a generated order still at
    `payment_status` `UNPAID`; this sets `past_due_since` to the current instant."
    PRD §3.6: "Under `PAY_PER_CYCLE` the price is that base unchanged, and the
    generated order must be paid for like any other, so a missed payment is what
    drives the membership into arrears."

    Design: Difficulty/cross_entity_state_dependency/cycle_confirm_blocked_by_subscription_in_past_due
    """
    s = setup_reserved_cycle(billing_mode="PAY_PER_CYCLE", units_per_cycle=24)
    confirmed = validate_success(
        api.confirm_cycle(
            s.cycle_id,
            {"expected_subscription_version": subscription_version(s.subscription_id, s.ch)},
            s.ch,
        )
    )
    assert confirmed["cycle_status"] == "ORDER_PLACED"
    club_orders, _ = validate_paginated(
        api.list_orders(s.ch, {"subscription_cycle_id": s.cycle_id})
    )
    assert club_orders[0]["payment_status"] == "UNPAID"

    second_cycle = generate_cycle(s, 2)
    past_due = validate_success(
        api.set_subscription_status(s.subscription_id, {"to_status": "PAST_DUE"}, s.bh)
    )
    assert past_due["sub_status"] == "PAST_DUE"
    assert_same_instant(past_due["past_due_since"], CLOCK_ORDERING_TIME, "past_due_since")

    api.confirm_cycle(
        second_cycle["id"],
        {"expected_subscription_version": subscription_version(s.subscription_id, s.ch)},
        s.ch,
    )
    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["reserved_units"] == 24
    assert capacity["confirmed_units"] == 24
