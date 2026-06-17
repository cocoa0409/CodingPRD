"""Food-and-beverage minimum/shortfall boundary behaviour and queue play_order
ordering (priority then created_at tie-break).

Covers difficulty queue boundary_precision_check (fb side) and the corner
calculations section.
"""
from test_helpers import (
    validate_paginated,
    setup_base, create_checked_in_reservation, add_fb_order, void_fb_order,
    close_reservation, create_song, queue_song,
    make_front_desk_headers,
)

FD = make_front_desk_headers()


def test_fb_minimum_exact_boundary_no_shortfall(api):
    """PRD §3.4: "The shortfall is charged only when the effective figure is strictly
    below the required floor: when the effective figure is below the floor,
    `fb_shortfall_cents` is the floor minus the effective figure; when the effective
    figure equals or exceeds the floor, `fb_shortfall_cents` is 0."
    PRD §3.4: "An effective figure exactly equal to the floor means the minimum is
    precisely met and the shortfall is 0."

    fb_minimum 5000, consumed exactly 5000 (2500 x 2) -> fb_shortfall_cents == 0.

    Design: Difficulty/boundary_precision_check/fb_minimum_exact_boundary_no_shortfall
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 5000},
        clock_utc="2026-07-16T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-07-16T20:00:00.000Z", "2026-07-16T22:00:00.000Z",
        checkin_clock_utc="2026-07-16T20:00:00.000Z",
    )
    add_fb_order(res, customer, unit_price_cents=2500, quantity=2, description="2x Combo")
    closed = close_reservation(res, "2026-07-16T21:00:00.000Z")
    assert closed["fb_consumed_cents"] == 5000
    assert closed["fb_shortfall_cents"] == 0


def test_fb_minimum_just_below_boundary_shortfall_one(api):
    """PRD §3.4: "when the effective figure is below the floor, `fb_shortfall_cents` is
    the floor minus the effective figure".

    fb_minimum 5000, consumed 4999 (one cent under) -> fb_shortfall_cents == 1.

    Design: Corner/calculations/fb_minimum_just_below_boundary_shortfall_one
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 5000},
        clock_utc="2026-08-10T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-08-10T20:00:00.000Z", "2026-08-10T22:00:00.000Z",
        checkin_clock_utc="2026-08-10T20:00:00.000Z",
    )
    add_fb_order(res, customer, unit_price_cents=4999, quantity=1, description="One under")
    closed = close_reservation(res, "2026-08-10T21:00:00.000Z")
    assert closed["fb_shortfall_cents"] == 1


def test_fb_consumed_excludes_voided_orders(api):
    """PRD §3.4: "The consumed amount `fb_consumed_cents` is the sum of `line_total_cents`
    across the reservation's food-and-beverage orders that are still `PLACED` (voided
    lines are excluded)."

    2000 PLACED + 5000 voided -> fb_consumed_cents == 2000.

    Design: Corner/calculations/fb_consumed_excludes_voided_orders
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-08-09T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-08-09T20:00:00.000Z", "2026-08-09T22:00:00.000Z",
        checkin_clock_utc="2026-08-09T20:00:00.000Z",
    )
    add_fb_order(res, customer, unit_price_cents=1000, quantity=2, description="Keep")
    drop = add_fb_order(res, customer, unit_price_cents=5000, quantity=1, description="Drop")
    void_fb_order(drop["id"])
    closed = close_reservation(res, "2026-08-09T21:00:00.000Z")
    assert closed["fb_consumed_cents"] == 2000


def test_queue_play_order_priority_then_created_at_tiebreak(api):
    """PRD §3.6: "among all `PENDING` entries on the reservation, the entries are sorted
    by `priority` ascending and then, for entries of equal priority, by `created_at`
    ascending — the creation timestamp is the deterministic tie-break, never the `id` —
    and positions 1, 2, 3, and so on are assigned in that order."

    Two entries at equal priority 50, A created before B: A gets play_order 1, B gets 2.

    Design: Corner/calculations/queue_play_order_priority_then_created_at_tiebreak
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-11T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song_a = create_song(venue["id"], title="A", artist="A")
    song_b = create_song(venue["id"], title="B", artist="B")
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-08-11T20:00:00.000Z", "2026-08-11T22:00:00.000Z",
        checkin_clock_utc="2026-08-11T20:00:00.000Z",
    )
    qa = queue_song(res, customer, song_a["id"], priority=50)
    qb = queue_song(res, customer, song_b["id"], priority=50)

    data, _meta = validate_paginated(
        api.list_queue_entries(FD, params={"reservation_id": res["id"], "status": "PENDING"})
    )
    by_id = {e["id"]: e for e in data}
    assert by_id[qa["id"]]["play_order"] == 1
    assert by_id[qb["id"]]["play_order"] == 2
