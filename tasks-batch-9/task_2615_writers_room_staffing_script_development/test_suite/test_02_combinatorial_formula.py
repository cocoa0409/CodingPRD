"""Money formulas whose inputs live on several entities at once.

The seat floor, the prorated commitment and the room burn each combine values
drawn from the agreement, the room, the seat and the writer, and each pins an
order of operations that a factor-by-factor implementation gets wrong.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import fixtures as X
from test_helpers.test_users import GUILD_ADMINISTRATOR_HEADERS

MINI_ROOM = {
    "name": "Mini Room B",
    "format": "MINI_ROOM",
    "seat_capacity": 2,
    "duration_weeks_committed": 12,
    "start_date": "2026-09-01T00:00:00Z",
    "end_date": "2026-11-24T00:00:00Z",
}

REMOTE_ROOM = {
    "name": "Remote Satellite",
    "format": "REMOTE",
    "seat_capacity": 3,
    "duration_weeks_committed": 26,
}


def _mini_room_seat(api):
    """Offer the diversity-programme writer a thin seat in a short mini room."""
    world = X.build_staffing_room_world(api, room_overrides=MINI_ROOM)
    world["seat"] = X.seed_seat(
        api,
        world["room_id"],
        world["w8_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        level_at_hire="STAFF_WRITER",
        offered_weekly_compensation_cents=500000,
        start_date="2026-09-01T00:00:00Z",
        end_date="2026-11-24T00:00:00Z",
        episodic_guarantee_count=1,
        diversity_program_funded=True,
    )
    return world


def _short_seat(api):
    """Offer a 17-day seat at a weekly rate that is not a multiple of seven cents."""
    world = X.build_staffing_room_world(api)
    X.seed_window(api, world["w3_id"], "NON_EXCLUSIVE")
    world["seat"] = X.seed_seat(
        api,
        world["room_id"],
        world["w3_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        level_at_hire="STAFF_WRITER",
        offered_weekly_compensation_cents=450000,
        exclusivity="NON_EXCLUSIVE",
        start_date="2026-09-01T00:00:00Z",
        end_date="2026-09-18T00:00:00Z",
        episodic_guarantee_count=0,
    )
    return world


def _tier_boundary_room(api):
    """A REMOTE room whose two offers sum to exactly the tier-one ceiling."""
    world = X.build_staffing_room_world(api, room_overrides=REMOTE_ROOM)
    validate_success(
        api.add_credit_history(
            world["w2_id"],
            {"episodic_credits_awarded": 4, "agreement_id": world["agreement_id"]},
            GUILD_ADMINISTRATOR_HEADERS,
        )
    )
    s1 = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        level_at_hire="STORY_EDITOR",
        offered_weekly_compensation_cents=600000,
        episodic_guarantee_count=0,
    )
    world["s1_id"] = s1["id"]
    s2 = X.seed_seat(
        api,
        world["room_id"],
        world["w2_id"],
        world["sr_headers"],
        level_at_hire="CO_PRODUCER",
        offered_weekly_compensation_cents=900000,
        exclusivity="NON_EXCLUSIVE",
        episodic_guarantee_count=0,
    )
    world["s2_id"] = s2["id"]
    world["s1"] = X.accept_seat(api, s1["id"], world["w1_id"])
    return world


def test_mini_room_floor_is_one_rounded_product_that_lifts_a_thin_offer(api):
    """A 12-week mini room lifts a 500,000 offer to a floor of 594,000.

    PRD: "Rounding happens exactly once, on the single product of level minimum, format multiplier and the uplift factor, and the rounded result is the seat's `guild_floor_weekly_cents`."

    PRD: "The seat's `weekly_compensation_cents` is then the greater of the studio's `offered_weekly_compensation_cents` and that floor, so a generous offer stands and a thin one is lifted to the floor."

    Design: Difficulty/combinatorial_formula/mode_a_seat_weekly_compensation_five_input_nested_max_min
    """
    world = _mini_room_seat(api)
    seat = world["seat"]

    A.assert_cents(seat["guild_floor_weekly_cents"], 594000, "guild_floor_weekly_cents")
    A.assert_cents(
        seat["weekly_compensation_cents"], 594000, "weekly_compensation_cents"
    )
    A.assert_field_values(seat, level_at_hire="STAFF_WRITER", status="OFFERED")
    A.assert_common_fields(seat)


def test_diversity_subsidy_is_capped_before_the_studio_charge_is_taken(api):
    """The raw half-share of 297,000 is cut to the 250,000 cap, so the studio bears 344,000.

    PRD: "When the seat is `diversity_program_funded` and the writer is a `diversity_program_participant`, the seat's `diversity_subsidy_weekly_cents` is the lesser of two figures: the seat's weekly compensation multiplied by the agreement's `diversity_subsidy_pct` and rounded to whole cents, and the agreement's `diversity_subsidy_cap_weekly_cents`."

    PRD: "The seat's `studio_charge_weekly_cents` is its weekly compensation minus that subsidy, and it is the figure the studio actually bears — though note that the room's burn and the season's staffing commitment are built from full weekly compensation, not from the studio charge."

    Design: Difficulty/combinatorial_formula/mode_a_seat_weekly_compensation_five_input_nested_max_min
    """
    world = _mini_room_seat(api)
    seat = world["seat"]

    A.assert_seat_pricing(seat, 594000, 594000, 250000, 344000, 7128000)
    A.assert_field_values(
        seat, guarantee_slots_consumed=0, guarantee_slots_remaining=1
    )
    A.assert_guarantee_slots_conserved(seat)


def test_prorated_commitment_rounds_the_daily_rate_before_multiplying(api):
    """Seventeen days at 450,000 a week come to 1,092,858 cents, not 1,092,857.

    PRD: "Round the weekly compensation divided by 7 to whole cents **first** to obtain a daily rate, then multiply that rounded daily rate by the residual days, and add the product of the full weeks and the full weekly compensation."

    PRD: "Deriving the residual by multiplying the weekly rate by the residual days and rounding at the end is a different computation and must not be used: on a seat paying 450,000 cents a week with three residual days, the pinned order yields three times 64,286, or 192,858 cents, while the rejected order yields 192,857 — a one-cent divergence on every seat whose weekly rate is not a multiple of seven cents."

    Design: Difficulty/combinatorial_formula/mode_b_seat_prorated_commitment_pinned_rounding_order
    """
    world = _short_seat(api)
    seat = world["seat"]

    A.assert_cents(
        seat["prorated_commitment_cents"],
        K.SEAT_PRORATED_17_DAYS_AT_450000,
        "prorated_commitment_cents",
    )
    assert seat["prorated_commitment_cents"] != 1092857, (
        "1092857 is the rejected multiply-then-round order"
    )


def test_a_full_length_commitment_attracts_no_uplift_and_no_subsidy(api):
    """A 26-week in-person room prices the seat at the bare level minimum.

    PRD: "That level minimum is multiplied by a format multiplier, which is the agreement's `mini_room_floor_multiplier` when the room's format is `MINI_ROOM` and exactly 1 for both `IN_PERSON` and `REMOTE` — a mini room pays a premium because it asks fewer writers to carry a whole season."

    PRD: "In every other case the subsidy is 0."

    Design: Difficulty/combinatorial_formula/mode_b_seat_prorated_commitment_pinned_rounding_order
    """
    world = _short_seat(api)
    seat = world["seat"]

    A.assert_seat_pricing(seat, 450000, 450000, 0, 450000)
    A.assert_field_values(seat, status="OFFERED", exclusivity="NON_EXCLUSIVE")


def test_facility_tier_is_keyed_to_the_pre_surcharge_subtotal(api):
    """A subtotal landing exactly on the tier-one ceiling stays in TIER_1.

    PRD: "Step two selects `facility_tier` from that subtotal, and from the subtotal alone: `TIER_1` when the subtotal is at or below the agreement's `TIER_1_MAX` bound, otherwise `TIER_2` when it is at or below `TIER_2_MAX`, otherwise `TIER_3`."

    PRD: "Step three multiplies the facility fee for the selected tier by the agreement's format surcharge fraction for the room's `format` and rounds the product to whole cents, giving `facility_surcharge_weekly_cents`."

    Design: Difficulty/combinatorial_formula/mode_c_room_weekly_burn_tier_keyed_on_pre_surcharge_subtotal
    """
    world = _tier_boundary_room(api)

    X.accept_seat(api, world["s2_id"], world["w2_id"])

    room = X.read_room(api, world["room_id"])
    A.assert_room_burn(room, 1500000, K.FACILITY_TIER_1, 80000, 1580000)
    A.assert_field_values(
        room, confirmed_seat_count=2, filled_seat_count=2, open_seat_count=1
    )
    A.assert_seat_capacity_conserved(room)

    season = X.read_season(api, world["season_id"])
    A.assert_cents(
        season["staffing_commitment_weekly_cents"],
        1580000,
        "staffing_commitment_weekly_cents",
    )


def test_an_offered_seat_never_enters_the_room_subtotal(api):
    """With one seat accepted and one still outstanding the subtotal is 600,000.

    PRD: "Step one sums `weekly_compensation_cents` across only those seats of the room whose status is `CONFIRMED`, producing `seat_subtotal_weekly_cents`; seats merely `OFFERED` contribute nothing."

    Design: Difficulty/combinatorial_formula/mode_c_room_weekly_burn_tier_keyed_on_pre_surcharge_subtotal
    """
    world = _tier_boundary_room(api)

    room = X.read_room(api, world["room_id"])
    A.assert_room_burn(room, 600000, K.FACILITY_TIER_1, 80000, 680000)
    A.assert_field_values(
        room, confirmed_seat_count=1, filled_seat_count=2, open_seat_count=1
    )

    outstanding = X.read_seat(api, world["s2_id"])
    A.assert_field_values(outstanding, status="OFFERED")
    A.assert_cents(
        outstanding["weekly_compensation_cents"], 900000, "weekly_compensation_cents"
    )

    season = X.read_season(api, world["season_id"])
    A.assert_cents(
        season["staffing_commitment_weekly_cents"],
        680000,
        "staffing_commitment_weekly_cents",
    )
