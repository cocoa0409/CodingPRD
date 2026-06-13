"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: the Customer role is entity-backed, so any ownership-gated
Customer call uses make_customer_headers(customer["id"]). Fixtures created by
FrontDesk operators use the opaque FrontDesk constant, which is valid for any
reservation because the desk acts on behalf of the center (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_rate_card_payload,
    create_lane_payload,
    create_bay_payload,
    create_customer_payload,
    create_party_package_payload,
    create_food_item_payload,
    create_rental_item_payload,
    create_reservation_payload,
    create_rental_line_payload,
    create_league_payload,
    create_league_night_payload,
)
from .test_users import TEST_USERS, make_customer_headers

CM = TEST_USERS["center_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
LA = TEST_USERS["league_admin_headers"]


# --- Tier 0: atomic config creators ---------------------------------------
def create_rate_card(**overrides):
    return get_success_data(api_client.create_rate_card(create_rate_card_payload(**overrides), CM))


def create_lane(**overrides):
    return get_success_data(api_client.create_lane(create_lane_payload(**overrides), CM))


def create_bay(**overrides):
    return get_success_data(api_client.create_bay(create_bay_payload(**overrides), CM))


def create_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), FD))


def create_party_package(**overrides):
    return get_success_data(api_client.create_party_package(create_party_package_payload(**overrides), CM))


def create_food_item(**overrides):
    return get_success_data(api_client.create_food_item(create_food_item_payload(**overrides), CM))


def create_rental_item(**overrides):
    return get_success_data(api_client.create_rental_item(create_rental_item_payload(**overrides), CM))


def set_clock(now_utc: str):
    api_client.clock_set({"now_utc": now_utc}, FD)


def advance_clock(minutes: int):
    return api_client.clock_advance({"minutes": minutes}, FD)


# --- Tier 1: base scenario (rate card + lane + customer) ------------------
def setup_lane_scenario(rate_card_overrides=None, lane_overrides=None, customer_overrides=None):
    """Active customer + IN_SERVICE lane + rate card. Returns dict context."""
    rc = create_rate_card(**(rate_card_overrides or {}))
    lane = create_lane(**(lane_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    return {"rate_card": rc, "lane": lane, "customer": customer}


def setup_bay_scenario(rate_card_overrides=None, bay_overrides=None, customer_overrides=None):
    """Active customer + IN_SERVICE bay + rate card. Returns dict context."""
    rc = create_rate_card(**(rate_card_overrides or {}))
    bay = create_bay(**(bay_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    return {"rate_card": rc, "bay": bay, "customer": customer}


# --- Tier 2: draft / held / confirmed lane reservations -------------------
def create_draft_lane_reservation(ctx=None, reservation_overrides=None, **scenario_overrides):
    """rc + lane + customer + a DRAFT reservation on the lane. Returns (ctx, reservation)."""
    if ctx is None:
        ctx = setup_lane_scenario(**scenario_overrides)
    payload = create_reservation_payload(
        ctx["customer"]["id"], ctx["rate_card"]["id"],
        resource_kind="LANE", lane_id=ctx["lane"]["id"],
        **(reservation_overrides or {}),
    )
    res = get_success_data(api_client.create_reservation(payload, FD))
    return ctx, res


def create_held_lane_reservation(ctx=None, reservation_overrides=None, **scenario_overrides):
    """As create_draft_lane_reservation, then hold. Returns (ctx, held_reservation)."""
    ctx, res = create_draft_lane_reservation(ctx, reservation_overrides, **scenario_overrides)
    held = get_success_data(api_client.hold_reservation(res["id"], FD))
    return ctx, held


def create_confirmed_lane_reservation(ctx=None, reservation_overrides=None, **scenario_overrides):
    """Held then confirmed. Returns (ctx, confirmed_reservation)."""
    ctx, held = create_held_lane_reservation(ctx, reservation_overrides, **scenario_overrides)
    confirmed = get_success_data(
        api_client.confirm_reservation(
            held["id"], {"expected_reservation_version": held["version"]}, FD
        )
    )
    return ctx, confirmed


def create_draft_bay_reservation(ctx=None, reservation_overrides=None, **scenario_overrides):
    """rc + bay + customer + a DRAFT bay reservation. Returns (ctx, reservation)."""
    if ctx is None:
        ctx = setup_bay_scenario(**scenario_overrides)
    payload = create_reservation_payload(
        ctx["customer"]["id"], ctx["rate_card"]["id"],
        resource_kind="BAY", bay_id=ctx["bay"]["id"],
        pricing_mode="PER_HOUR",
        **(reservation_overrides or {}),
    )
    res = get_success_data(api_client.create_reservation(payload, FD))
    return ctx, res


def create_held_bay_reservation(ctx=None, reservation_overrides=None, **scenario_overrides):
    """As create_draft_bay_reservation, then hold. Returns (ctx, held_reservation)."""
    ctx, res = create_draft_bay_reservation(ctx, reservation_overrides, **scenario_overrides)
    held = get_success_data(api_client.hold_reservation(res["id"], FD))
    return ctx, held


# --- Tier 3: rentals on a reservation -------------------------------------
def take_rental(reservation_id, rental_item_id, quantity=1):
    """Create an OPEN rental line. Returns the rental line."""
    return get_success_data(
        api_client.create_rental_line(
            create_rental_line_payload(reservation_id, rental_item_id, quantity), FD
        )
    )


# --- Tier 4: leagues with scheduled nights --------------------------------
def setup_league_with_nights(num_nights, lanes_per_night=1, weekly_fee_cents=5000,
                             season_night_count=None, night_windows=None):
    """Create a DRAFT league with `num_nights` scheduled nights, plus enough
    IN_SERVICE lanes to satisfy reservations. Returns dict context with
    rate_card, lanes, league, nights (list).

    night_windows: optional list of (start_at, end_at) tuples, one per night.
    """
    rc = create_rate_card(per_game_cents=0, per_hour_cents=0)
    lanes = [create_lane() for _ in range(lanes_per_night)]
    if season_night_count is None:
        season_night_count = num_nights
    league = get_success_data(
        api_client.create_league(
            create_league_payload(
                rc["id"], season_night_count=season_night_count,
                lanes_per_night=lanes_per_night, weekly_fee_cents=weekly_fee_cents,
            ),
            LA,
        )
    )
    default_windows = [
        ("2026-07-02T18:00:00.000Z", "2026-07-02T20:00:00.000Z"),
        ("2026-07-09T18:00:00.000Z", "2026-07-09T20:00:00.000Z"),
        ("2026-07-16T18:00:00.000Z", "2026-07-16T20:00:00.000Z"),
        ("2026-07-23T18:00:00.000Z", "2026-07-23T20:00:00.000Z"),
    ]
    windows = night_windows or default_windows
    nights = []
    for i in range(num_nights):
        start_at, end_at = windows[i]
        night = get_success_data(
            api_client.create_league_night(
                create_league_night_payload(
                    league["id"], night_index=i + 1, start_at=start_at, end_at=end_at
                ),
                LA,
            )
        )
        nights.append(night)
    return {"rate_card": rc, "lanes": lanes, "league": league, "nights": nights}


def setup_active_league_with_nights(num_nights, **kwargs):
    """As setup_league_with_nights, then activate the league. Returns context with
    the activated league replacing the DRAFT one."""
    ctx = setup_league_with_nights(num_nights, **kwargs)
    activated = get_success_data(api_client.activate_league(ctx["league"]["id"], LA))
    ctx["league"] = activated
    return ctx


# --- Tier 5: waitlist contention -----------------------------------------
def setup_held_and_waitlisted_on_same_lane(window_start, window_end,
                                           rate_card_overrides=None, lane_overrides=None):
    """A HELD reservation (customer C1) blocks a lane window, and a second
    reservation (customer C2) is WAITLISTED on the same lane+window. Returns
    dict context with rate_card, lane, c1, c2, held (R1), waitlisted (R2)."""
    rc = create_rate_card(**(rate_card_overrides or {"per_game_cents": 1000, "per_hour_cents": 0}))
    lane = create_lane(**(lane_overrides or {}))
    c1 = create_customer()
    c2 = create_customer()

    r1 = get_success_data(api_client.create_reservation(
        create_reservation_payload(
            c1["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
            pricing_mode="PER_GAME", start_at=window_start, end_at=window_end,
            bowler_count=2, game_count=3,
        ), FD))
    held = get_success_data(api_client.hold_reservation(r1["id"], FD))

    r2 = get_success_data(api_client.create_reservation(
        create_reservation_payload(
            c2["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
            pricing_mode="PER_GAME", start_at=window_start, end_at=window_end,
            bowler_count=2, game_count=3,
        ), FD))
    waitlisted = get_success_data(api_client.waitlist_reservation(r2["id"], FD))

    return {
        "rate_card": rc, "lane": lane,
        "c1": c1, "c2": c2,
        "held": held, "waitlisted": waitlisted,
    }


__all__ = [
    "CM", "FD", "LA",
    "create_rate_card", "create_lane", "create_bay", "create_customer",
    "create_party_package", "create_food_item", "create_rental_item",
    "set_clock", "advance_clock",
    "setup_lane_scenario", "setup_bay_scenario",
    "create_draft_lane_reservation", "create_held_lane_reservation",
    "create_confirmed_lane_reservation",
    "create_draft_bay_reservation", "create_held_bay_reservation",
    "take_rental",
    "setup_league_with_nights", "setup_active_league_with_nights",
    "setup_held_and_waitlisted_on_same_lane",
    "make_customer_headers",
]
