"""Seat pricing (pinned rounding, load tiers, weekend) and season windows."""
from test_helpers import (
    ApiErrorId,
    create_booking,
    create_flight,
    create_season,
    is_valid_uuid,
    passenger_entry,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_season_payload
from test_helpers.fixtures import create_base

OPS = TEST_USERS["ops_admin_headers"]
AGENT = TEST_USERS["booking_agent_headers"]


def _env_with_priced_route(api, base_price_cents, seat_capacity=4,
                           clock="2026-08-10T00:00:00Z"):
    env = setup_ops_env(
        clock=clock,
        route_overrides={
            "route_code": "RX",
            "tier": "STANDARD",
            "duration_minutes": 50,
            "base_seat_price_cents": base_price_cents,
            "fuel_required_lb": 450,
        },
    )
    return env


def test_season_adjacent_windows_allowed_overlap_rejected(api):
    """PRD §2.8: "A pricing season covers dates from `start_date` inclusive
    to `end_date` exclusive, and two seasons may touch — one ending exactly
    when another begins — without overlapping."
    PRD §3.1: "Creation rejects a window that overlaps any PUBLISHED season —
    adjacency, where one season's `end_date` equals another's `start_date`,
    is allowed — or whose end is not after its start, with
    `ERR_SEASON_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/season_half_open_adjacency_and_end_exclusive_pricing
    """
    set_clock("2026-08-10T00:00:00Z")
    create_base()
    s1 = create_season(label="S1", start_date="2026-06-01",
                       end_date="2026-09-01", multiplier_bps=12000)
    assert is_valid_uuid(s1["id"])

    # Adjacency: S2 starts exactly at S1's end_date — legal under half-open.
    s2 = validate_success(
        api.create_season(
            create_season_payload(label="S2", start_date="2026-09-01",
                                  end_date="2026-12-01", multiplier_bps=11200),
            OPS,
        ),
        expected_status=201,
    )
    assert is_valid_uuid(s2["id"])

    # One day earlier collides with S1's still-covered 2026-08-31.
    resp = api.create_season(
        create_season_payload(label="S3", start_date="2026-08-31",
                              end_date="2026-10-01", multiplier_bps=10000),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_SEASON_OVERLAP)


def test_departure_on_season_end_date_prices_under_successor(api):
    """PRD §2.8: "A pricing season covers dates from `start_date` inclusive
    to `end_date` exclusive, and two seasons may touch — one ending exactly
    when another begins — without overlapping."
    PRD §3.5: "First comes the seasonal multiplier: the `multiplier_bps` of
    the PUBLISHED season whose window covers the departure date, ten thousand
    basis points when no PUBLISHED season covers it (RETIRED seasons are
    invisible to this selection), and the covering season's `id` is
    remembered on the booking as `season_id` — null in the fallback case."

    Design: Difficulty/resource_temporal_overlap/season_half_open_adjacency_and_end_exclusive_pricing
    """
    env = setup_ops_env(clock="2026-08-10T00:00:00Z")
    s1 = create_season(label="S1", start_date="2026-06-01",
                       end_date="2026-09-01", multiplier_bps=12000)
    s2 = create_season(label="S2", start_date="2026-09-01",
                       end_date="2026-12-01", multiplier_bps=11200)
    flight = create_flight(env, "2026-09-01T14:30:00Z")

    booking = create_booking(flight["id"], [passenger_entry("P0", 100)])
    # 2026-09-01 belongs to S2 (S1's end_date is exclusive):
    # round_half_up(25000 * 1.12) == 28000; load 0% -> parity; Tuesday.
    assert booking["quoted_per_seat_cents"] == 28000
    assert booking["season_id"] == s2["id"]


def test_quote_nested_rounding_order_pinned(api):
    """PRD §3.5: "The quote starts from the route's `base_seat_price_cents`
    and applies three multipliers in a pinned order, each in basis points and
    each multiplication rounded half-up to whole cents before the next is
    applied."
    PRD §3.5: "Second comes the load multiplier, driven by how full the
    flight already is before this booking's seats are added: the load
    percentage is the whole-number floor of `seats_booked` times one hundred
    divided by `seat_capacity`; below fifty percent the multiplier is parity,
    from fifty percent up to but not including eighty percent it is 1.10x,
    and at eighty percent or above it is 1.25x."

    Design: Difficulty/combinatorial_formula/seat_price_nested_rounding_order_pinned
    """
    env = _env_with_priced_route(api, 9950)
    create_season(label="SP", start_date="2026-06-01", end_date="2026-12-31",
                  multiplier_bps=11500)
    # Saturday departure -> weekend multiplier 1.10x applies.
    flight = create_flight(env, "2026-08-15T14:00:00Z")
    create_booking(flight["id"], [passenger_entry("P0", 150),
                                  passenger_entry("P1", 150)],
                   contact_name="A", contact_email="a@x.com")

    # Second booking sees load floor(2*100/4) == 50 -> 11000 bps tier.
    b2 = create_booking(flight["id"], [passenger_entry("P9", 150)],
                        contact_name="B", contact_email="b@x.com")
    # Pinned per-step: round_half_up(9950*1.15)=11443;
    # round_half_up(11443*1.10)=12587; round_half_up(12587*1.10)=13846.
    assert b2["quoted_per_seat_cents"] == 13846
    # Single-shot rounding of 9950*1.15*1.10*1.10 would yield 13845.
    assert b2["quoted_per_seat_cents"] != 13845


def test_quote_total_multiplied_after_per_seat_rounding(api):
    """PRD §3.5: "The per-seat figure after the third rounding is
    `quoted_per_seat_cents`, and `quoted_total_cents` is that per-seat figure
    multiplied by `seat_count` — the multiplication happens only after
    per-seat rounding, never before."
    PRD §3.5: "Third comes the weekend multiplier: 1.10x when the UTC
    day-of-week of `scheduled_departure_utc` is Saturday or Sunday, parity
    otherwise."

    Design: Difficulty/combinatorial_formula/seat_price_nested_rounding_order_pinned
    """
    env = _env_with_priced_route(api, 9950)
    create_season(label="SP", start_date="2026-06-01", end_date="2026-12-31",
                  multiplier_bps=11500)
    flight = create_flight(env, "2026-08-15T14:00:00Z")  # Saturday

    # B1 at load 0%: per-seat round_half_up(9950*1.15)=11443, then parity,
    # then round_half_up(11443*1.10)=12587; total multiplies AFTER rounding.
    b1 = create_booking(flight["id"], [passenger_entry("P0", 150),
                                       passenger_entry("P1", 150)],
                        contact_name="A", contact_email="a@x.com")
    assert b1["quoted_per_seat_cents"] == 12587
    assert b1["quoted_total_cents"] == 12587 * 2

    b2 = create_booking(flight["id"], [passenger_entry("P9", 150)],
                        contact_name="B", contact_email="b@x.com")
    assert b2["quoted_per_seat_cents"] == 13846
    assert b2["quoted_total_cents"] == 13846 * 1


def test_seat_price_load_tiers_applied(api):
    """PRD §3.5: "Second comes the load multiplier, driven by how full the
    flight already is before this booking's seats are added: the load
    percentage is the whole-number floor of `seats_booked` times one hundred
    divided by `seat_capacity`; below fifty percent the multiplier is parity,
    from fifty percent up to but not including eighty percent it is 1.10x,
    and at eighty percent or above it is 1.25x."

    Design: Corner/calculations/seat_price_load_tiers_applied
    """
    env = setup_ops_env(
        route_overrides={"route_code": "RX", "base_seat_price_cents": 20000},
        aircraft_overrides={"seat_capacity": 5,
                            "seat_arms_inches": [40, 40, 40, 80, 80]},
    )
    # Monday departure, no season -> only the load multiplier moves.
    flight = create_flight(env, "2026-08-03T14:00:00Z")

    q1 = create_booking(flight["id"], [passenger_entry("P0", 100)],
                        contact_name="A", contact_email="a@x.com")
    assert q1["quoted_per_seat_cents"] == 20000   # load 0% -> parity

    q2 = create_booking(flight["id"], [passenger_entry("P1", 100),
                                       passenger_entry("P2", 100)],
                        contact_name="B", contact_email="b@x.com")
    assert q2["quoted_per_seat_cents"] == 20000   # floor(1*100/5)==20 -> parity

    q3 = create_booking(flight["id"], [passenger_entry("P3", 100)],
                        contact_name="C", contact_email="c@x.com")
    assert q3["quoted_per_seat_cents"] == 22000   # floor(3*100/5)==60 -> 1.10x

    q4 = create_booking(flight["id"], [passenger_entry("P4", 100)],
                        contact_name="D", contact_email="d@x.com")
    assert q4["quoted_per_seat_cents"] == 25000   # floor(4*100/5)==80 -> 1.25x


def test_season_retire_excludes_from_pricing(api):
    """PRD §3.1: "A season is created PUBLISHED; retiring it moves it to the
    terminal RETIRED state, after which it is invisible to pricing selection
    and to the overlap check."
    PRD §3.5: "Every seat price is computed by the quote algorithm, which
    runs at booking creation — where the result locks — and again when a
    booking is moved, where it recomputes and relocks."

    Design: Corner/state_machines/season_retire_excludes_from_pricing
    """
    env = setup_ops_env()
    s1 = create_season(label="S1", start_date="2026-08-01",
                       end_date="2026-09-01", multiplier_bps=12000)
    flight = create_flight(env, "2026-08-10T14:00:00Z")  # Monday

    b1 = create_booking(flight["id"], [passenger_entry("P0", 150)],
                        contact_name="A", contact_email="a@x.com")
    assert b1["quoted_per_seat_cents"] == 30000  # 25000 * 1.20

    retired = validate_success(
        api.season_event(s1["id"], {"event_type": "RETIRE"}, OPS)
    )
    assert retired["status"] == "RETIRED"

    b2 = create_booking(flight["id"], [passenger_entry("P1", 150)],
                        contact_name="B", contact_email="b@x.com")
    # RETIRED seasons are invisible: parity fallback, season_id null.
    assert b2["quoted_per_seat_cents"] == 25000
    assert b2["season_id"] is None

    # The earlier booking keeps its locked quote.
    from test_helpers.fixtures import get_booking
    assert get_booking(b1["id"])["quoted_per_seat_cents"] == 30000
