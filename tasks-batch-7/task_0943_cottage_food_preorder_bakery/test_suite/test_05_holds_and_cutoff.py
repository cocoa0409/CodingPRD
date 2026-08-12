"""The 45-minute hold, the administrative sweep, the re-entry loop, and the two
strictly-exclusive temporal boundaries around them."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    CLOCK_HOLD_LAPSE_TIME,
    CLOCK_ORDERING_TIME,
    add_line,
    api_client,
    assert_same_instant,
    instant_plus,
    lines_of,
    open_order,
    read_capacity,
    read_line,
    read_order,
    read_window,
    set_clock,
    setup_held_order,
    setup_storefront,
    sweep_holds,
    validate_error,
    validate_success,
    window_version,
)


def test_the_hold_sweep_expires_the_order_and_releases_its_line(api):
    """PRD §3.5: "An administrative sweep releases every order whose hold is due —
    that is, whose `hold_expires_at` is at or before the current instant — and it
    may be narrowed to a single window by supplying an `offer_window_id`."
    PRD §3.5: "For each due hold, the order moves from `PENDING_HOLD` to
    `EXPIRED_HOLD`, each of its `PENDING` lines moves to `RELEASED`, the released
    units are subtracted from the window's `held_units`, `hold_expires_at` is
    cleared to null, `capacity_posture` is recomputed — which may move it back
    toward `OPEN_CAPACITY` — and the order's and window's versions are bumped."
    PRD §3.5: "The sweep answers with `expired_order_count`, `released_line_count`,
    `released_units`, and the resulting `capacity_posture`."

    Design: Difficulty/non_linear_state_machine/order_hold_expiry_reentry_loop_restores_pending_hold
    """
    s = setup_held_order(quantity=13)
    assert_same_instant(
        read_order(s.order_id, s.ch)["hold_expires_at"],
        instant_plus(CLOCK_ORDERING_TIME, minutes=45),
        "hold_expires_at",
    )

    set_clock(CLOCK_HOLD_LAPSE_TIME)
    result = validate_success(
        api.expire_due_holds(ADMIN, {"offer_window_id": s.window_id})
    )
    assert result["expired_order_count"] == 1
    assert result["released_line_count"] == 1
    assert result["released_units"] == 13
    assert result["capacity_posture"] == "OPEN_CAPACITY"

    order = read_order(s.order_id, s.ch)
    assert order["order_status"] == "EXPIRED_HOLD"
    assert order["hold_expires_at"] is None
    assert read_line(s.line_id, s.ch)["line_status"] == "RELEASED"
    assert read_window(s.window_id, s.ch)["held_units"] == 0


def test_adding_a_line_to_an_expired_hold_order_reopens_the_hold(api):
    """PRD §3.5: "An expired order is not dead: adding another line to an
    `EXPIRED_HOLD` order, while the window is still `OPEN` and the cutoff still
    ahead, returns it to `PENDING_HOLD` with a fresh `placed_at` and a fresh
    45-minute `hold_expires_at`."
    PRD §3.5: "The lines released earlier stay `RELEASED` forever and never
    re-enter pricing."

    Design: Difficulty/non_linear_state_machine/order_hold_expiry_reentry_loop_restores_pending_hold
    """
    s = setup_held_order(quantity=13)
    set_clock(CLOCK_HOLD_LAPSE_TIME)
    sweep_holds(s.window_id)

    second = add_line(s.order_id, s.cookie_id, 5, s.customer_id, s.window_id)
    order = read_order(s.order_id, s.ch)
    assert order["order_status"] == "PENDING_HOLD"
    assert_same_instant(
        order["hold_expires_at"],
        instant_plus(CLOCK_HOLD_LAPSE_TIME, minutes=45),
        "refreshed hold_expires_at",
    )
    assert_same_instant(order["placed_at"], CLOCK_HOLD_LAPSE_TIME, "refreshed placed_at")

    assert read_line(s.line_id, s.ch)["line_status"] == "RELEASED"
    reopened = read_line(second["id"], s.ch)
    assert reopened["line_status"] == "PENDING"
    assert reopened["quantity"] == 5
    assert read_window(s.window_id, s.ch)["held_units"] == 5, (
        "only the new line's units are held; the RELEASED line never re-enters"
    )


def test_a_line_added_one_second_before_the_cutoff_is_accepted(api):
    """PRD §2.6: "Rung 17: the current instant is strictly before the window's
    `order_cutoff_at`; an instant exactly equal to the cutoff is already past it,
    and the rejection is `ERR_CUTOFF_PASSED` (409)."
    PRD §3.5: "Adding the first line to a `DRAFT` order moves the order to
    `PENDING_HOLD`, sets `placed_at` to the current instant, sets `hold_expires_at`
    to `placed_at` plus **45 minutes**, adds the line's units to the window's
    `held_units`, recomputes `capacity_posture`, and bumps both the order's and the
    window's `version`."

    Design: Difficulty/boundary_precision_check/cutoff_instant_is_strictly_exclusive_on_line_add
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    set_clock("2026-05-06T11:59:59Z")

    line = add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)
    assert line["line_status"] == "PENDING"
    assert line["line_total_cents"] == 4600
    reread = read_order(order["id"], s.ch)
    assert reread["order_status"] == "PENDING_HOLD"
    assert_same_instant(
        reread["hold_expires_at"],
        instant_plus("2026-05-06T11:59:59Z", minutes=45),
        "hold_expires_at one second before the cutoff",
    )


def test_a_line_added_exactly_at_the_cutoff_is_rejected(api):
    """PRD §2.6: "Rung 17: the current instant is strictly before the window's
    `order_cutoff_at`; an instant exactly equal to the cutoff is already past it,
    and the rejection is `ERR_CUTOFF_PASSED` (409)."
    PRD §3.4: "`order_cutoff_at`, after which they may not"

    Design: Difficulty/boundary_precision_check/cutoff_instant_is_strictly_exclusive_on_line_add
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    set_clock("2026-05-06T11:59:59Z")
    add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)

    set_clock("2026-05-06T12:00:00Z")
    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 1,
            "expected_offer_window_version": window_version(s.window_id, s.ch),
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_CUTOFF_PASSED)
    assert len(lines_of(order["id"], s.ch)) == 1


def test_a_live_hold_blocks_a_colliding_line_and_constrains_the_posture(api):
    """PRD §2.9: "Remaining orderable units are the window's `capacity_units` less
    confirmed units, less held units, less reserved units."
    PRD §2.6: "Rung 53: the window's remaining orderable units are at least the unit
    delta the request asks for, otherwise `ERR_UNITS_CAPACITY_EXCEEDED` (422); this
    applies to line addition, line patching, and club-cycle generation."
    PRD §2.9: "the posture is `CONSTRAINED` when the greatest of those three
    utilisations is at or above 0.80 — the comparison is inclusive — and
    `OPEN_CAPACITY` otherwise."

    Design: Difficulty/resource_temporal_overlap/hold_occupancy_interval_is_right_open_so_expiry_frees_units
    """
    s = setup_storefront(
        window_overrides={
            "label": "Twenty units",
            "capacity_units": 20,
            "capacity_batch_slots": 12,
            "capacity_oven_hours": 18.0,
        }
    )
    order_a = open_order(s.customer_id, s.window_id)
    order_b = open_order(s.customer_id, s.window_id)
    add_line(order_a["id"], s.cookie_id, 16, s.customer_id, s.window_id)

    window = read_window(s.window_id, s.ch)
    assert window["held_units"] == 16
    assert window["capacity_posture"] == "CONSTRAINED", (
        "16 of 20 units is exactly 0.80 utilisation and the comparison is inclusive"
    )

    rejected = api.add_order_line(
        order_b["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 8,
            "expected_offer_window_version": window_version(s.window_id, s.ch),
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_UNITS_CAPACITY_EXCEEDED)
    assert read_capacity(s.window_id, s.bh)["units_remaining"] == 4


def test_the_hold_frees_its_units_at_exactly_its_expiry_instant(api):
    """PRD §2.9: "**held units** are the summed `quantity` of every line that is
    `PENDING` whose owning order is `PENDING_HOLD` and whose `hold_expires_at` is
    strictly in the future — a hold whose expiry instant equals the current instant
    no longer counts"
    PRD §3.5: "An administrative sweep releases every order whose hold is due —
    that is, whose `hold_expires_at` is at or before the current instant — and it
    may be narrowed to a single window by supplying an `offer_window_id`."

    Design: Difficulty/resource_temporal_overlap/hold_occupancy_interval_is_right_open_so_expiry_frees_units
    """
    s = setup_storefront(
        window_overrides={
            "label": "Twenty units",
            "capacity_units": 20,
            "capacity_batch_slots": 12,
            "capacity_oven_hours": 18.0,
        }
    )
    order_a = open_order(s.customer_id, s.window_id)
    order_b = open_order(s.customer_id, s.window_id)
    line_a = add_line(order_a["id"], s.cookie_id, 16, s.customer_id, s.window_id)
    assert_same_instant(
        read_order(order_a["id"], s.ch)["hold_expires_at"],
        instant_plus(CLOCK_ORDERING_TIME, minutes=45),
        "order A hold_expires_at",
    )

    set_clock(CLOCK_HOLD_LAPSE_TIME)
    result = sweep_holds(s.window_id)
    assert result["released_units"] == 16
    assert read_line(line_a["id"], s.ch)["line_status"] == "RELEASED"
    assert read_order(order_a["id"], s.ch)["order_status"] == "EXPIRED_HOLD"

    line_b = add_line(order_b["id"], s.cookie_id, 8, s.customer_id, s.window_id)
    assert line_b["line_status"] == "PENDING"
    assert line_b["quantity"] == 8
    window = read_window(s.window_id, s.ch)
    assert window["held_units"] == 8
    assert window["capacity_posture"] == "OPEN_CAPACITY"


def test_confirming_after_the_hold_lapses_is_rejected(api):
    """PRD §2.6: "Rung 38: the current instant is strictly before the order's
    `hold_expires_at`, otherwise `ERR_HOLD_EXPIRED` (409); this applies to order
    confirmation and line patching, but deliberately not to line addition, since
    adding a line to an order whose hold lapsed is how a buyer re-opens it."

    Design: Corner/validations/confirming_after_the_hold_expires_returns_hold_expired
    """
    s = setup_held_order(quantity=13)
    set_clock(CLOCK_HOLD_LAPSE_TIME)

    rejected = api.confirm_order(s.order_id, s.ch, {})
    error = validate_error(rejected, ApiErrorId.ERR_HOLD_EXPIRED)
    assert error["error_id"] != "ERR_CUTOFF_PASSED", (
        "the window cutoff is two days later, so only the hold rung can fire"
    )
    order = read_order(s.order_id, s.ch)
    assert order["order_status"] == "PENDING_HOLD"
    assert order["subtotal_cents"] == 0
    assert read_window(s.window_id, s.bh)["confirmed_units"] == 0
