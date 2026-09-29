"""Three shared resources, three different interval semantics.

The tee sheet is half-open, the sponsor service window is closed and padded,
and the cart rule is a required gap between two intervals that never overlap.
"""

from test_helpers import (
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    SPONSORSHIP_HEADERS,
    ApiErrorId,
    assert_instant_equals,
    assert_version_unchanged,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

TEE_SHEET_OUTING = {
    "name": "Tee Sheet Open",
    "format": "STROKE_PLAY",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
TEN_MINUTE_CONTRACT = {
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 0,
    "fnb_minimum_cents": 0,
    "fnb_per_player_cents": 4500,
    "tee_interval_minutes": 10,
    "cart_allowance_count": 4,
}
TRIO_TIER = {
    "code": "TRIO",
    "kind": "INDIVIDUAL",
    "price_cents": 90000,
    "player_slots": 3,
    "gsv_cents": 18000,
    "inventory_cap": 10,
}

NOON = "2026-09-19T12:00:00Z"
TOUCHING = "2026-09-19T12:10:00Z"
ONE_MINUTE_INSIDE = "2026-09-19T12:09:00Z"


def _three_single_player_teams(api):
    """An OPEN outing on a ten-minute interval with ALPHA already off hole 1 at noon."""
    ctx = fx.open_outing(api, outing=TEE_SHEET_OUTING, contract=TEN_MINUTE_CONTRACT, tier=TRIO_TIER)
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Slot Testers", player_count=3
    )
    players = [
        fx.new_player(api, registration["id"], full_name=name, handicap_index=12.0)
        for name in ("S1", "S2", "S3")
    ]
    fx.pay_registration(api, registration["id"], 90000)
    teams = [
        fx.new_team(api, ctx["outing_id"], [players[i]["id"]], team_name=name)
        for i, name in enumerate(("ALPHA", "BRAVO", "CHARLIE"))
    ]
    ctx["teams"] = {t["team_name"]: t for t in teams}
    fx.assign_tee(
        api,
        ctx["teams"]["ALPHA"]["id"],
        wave="A",
        starting_hole=1,
        tee_time=NOON,
        cart_number=1,
        headers=COURSE_HEADERS,
    )
    return ctx


class TestTeeSheetSlotIsHalfOpen:
    """One starting hole of one outing is the resource; the slot excludes its end."""

    def test_a_group_teeing_off_exactly_when_the_slot_ends_is_accepted(self, api):
        """The half-open slot lets 12:10 follow 12:00 on the very same hole.

        The PRD describes the interval as running "from a group's `tee_time` up to
        but not including that time plus the contract's `tee_interval_minutes`"
        and adds that "The interval is half-open, so a group teeing off at exactly
        the instant the previous group's interval ends is accepted".

        Design: Difficulty/resource_temporal_overlap/tee_sheet_slot_is_half_open_per_starting_hole
        """
        ctx = _three_single_player_teams(api)

        alpha = fx.read_team(api, ctx["teams"]["ALPHA"]["id"])
        assert_instant_equals(alpha["slot_occupancy_start"], NOON)
        assert_instant_equals(alpha["slot_occupancy_end"], TOUCHING)

        bravo = ctx["teams"]["BRAVO"]
        response = api.tee_assignment(
            bravo["id"],
            f.tee_assignment_payload(
                bravo["version"], wave="A", starting_hole=1, tee_time=TOUCHING, cart_number=2
            ),
            COURSE_HEADERS,
        )
        validate_success(response, 200)

        placed = fx.read_team(api, bravo["id"])
        assert_instant_equals(placed["tee_time"], TOUCHING)
        assert_instant_equals(placed["slot_occupancy_end"], "2026-09-19T12:20:00Z")
        assert placed["tee_assignment_count"] == 1

    def test_one_minute_inside_the_slot_is_refused_yet_fits_a_different_hole(self, api):
        """12:09 collides on hole 1 and is free on hole 2, because the hole keys the sheet.

        The PRD scopes the slot to a resource pair: "For a given outing and a given
        `starting_hole`, the interval running from a group's `tee_time` up to but
        not including that time plus the contract's `tee_interval_minutes` may hold
        only one team." A genuine overlap "is refused with `ERR_TEE_SLOT_CONFLICT`",
        and the illustration is explicit: "groups off the same hole at 08:00 and
        08:10 coexist while 08:00 and 08:09 do not."

        Design: Difficulty/resource_temporal_overlap/tee_sheet_slot_is_half_open_per_starting_hole
        """
        ctx = _three_single_player_teams(api)
        charlie = ctx["teams"]["CHARLIE"]

        conflict = api.tee_assignment(
            charlie["id"],
            f.tee_assignment_payload(
                charlie["version"],
                wave="A",
                starting_hole=1,
                tee_time=ONE_MINUTE_INSIDE,
                cart_number=3,
            ),
            COURSE_HEADERS,
        )
        validate_error(conflict, ApiErrorId.TEE_SLOT_CONFLICT.value, 409)

        refused = fx.read_team(api, charlie["id"])
        assert refused["tee_time"] is None
        assert refused["tee_assignment_count"] == 0
        assert_version_unchanged(refused, charlie["version"])

        elsewhere = api.tee_assignment(
            charlie["id"],
            f.tee_assignment_payload(
                charlie["version"],
                wave="A",
                starting_hole=2,
                tee_time=ONE_MINUTE_INSIDE,
                cart_number=3,
            ),
            COURSE_HEADERS,
        )
        validate_success(elsewhere, 200)

        placed = fx.read_team(api, charlie["id"])
        assert placed["starting_hole"] == 2
        assert_instant_equals(placed["tee_time"], ONE_MINUTE_INSIDE)
        assert_instant_equals(placed["slot_occupancy_end"], "2026-09-19T12:19:00Z")

        sheet = fx.list_data(api.get_pairing_sheet(ctx["outing_id"], DIRECTOR_HEADERS))
        assert len(sheet) == 3
        occupied = [
            (row["starting_hole"], row["tee_time"]) for row in sheet if row["tee_time"] is not None
        ]
        assert len(occupied) == len(set(occupied))


BEVERAGE_OUTING = {
    "name": "Beverage Window Open",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
POURING_TIER = {"code": "POURING", "price_cents": 200000, "inventory_cap": 5}
BEVERAGE_STATION = {
    "asset_type": "BEVERAGE_STATION",
    "label": "Turn beverage cart",
    "hole_number": 10,
    "capacity": 2,
    "exclusive": False,
    "list_price_cents": 40000,
    "fulfillment_due_at": "2026-09-19T18:00:00Z",
}
WINDOW_START = "2026-09-19T12:00:00Z"
WINDOW_END = "2026-09-19T14:00:00Z"
TOUCHING_PADDED_START = "2026-09-19T15:00:00Z"
CLEAR_START = "2026-09-19T15:01:00Z"
LATER_END = "2026-09-19T16:00:00Z"


def _station_with_a_noon_window(api):
    """A two-capacity beverage station already serving from noon until two o'clock."""
    ctx = fx.open_outing(api, outing=BEVERAGE_OUTING, tier=POURING_TIER, sponsor_tier=True)
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Sparkling Springs", player_count=0
    )
    fx.pay_registration(api, registration["id"], 200000)
    asset = fx.new_asset(api, ctx["outing_id"], **BEVERAGE_STATION)
    first = fx.new_allocation(
        api,
        registration["id"],
        asset["id"],
        source="UPSELL",
        service_window_start=WINDOW_START,
        service_window_end=WINDOW_END,
    )
    ctx["registration_id"] = registration["id"]
    ctx["asset_id"] = asset["id"]
    ctx["first_allocation"] = first
    return ctx


class TestServiceWindowIsClosedAndPadded:
    """The same unit, the opposite inclusivity: padded windows that touch do collide."""

    def test_padded_windows_that_touch_at_a_single_instant_conflict(self, api):
        """A 15:00 start pads back to 14:30 and meets the noon booking's padded end.

        The PRD states that "Two allocations on the same unit conflict when their
        windows, each padded by 30 minutes on both sides, intersect", and that
        "the padded interval is treated as **closed**, so two windows that merely
        touch at the padded boundary do conflict". Its own illustration is this
        case: "a beverage-station sponsor finishing at noon and another starting at
        one o'clock are in conflict, because half an hour of changeover on each
        side closes the gap exactly." The unit still has room, so capacity cannot
        be the reason for the refusal.

        Design: Difficulty/resource_temporal_overlap/sponsorship_service_window_is_closed_and_padded_thirty_minutes
        """
        ctx = _station_with_a_noon_window(api)

        response = api.create_sponsor_allocation(
            f.sponsor_allocation_payload(
                ctx["registration_id"],
                ctx["asset_id"],
                "UPSELL",
                service_window_start=TOUCHING_PADDED_START,
                service_window_end=LATER_END,
            ),
            SPONSORSHIP_HEADERS,
        )
        validate_error(response, ApiErrorId.SERVICE_WINDOW_CONFLICT.value, 409)

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["capacity"] == 2
        assert asset["reserved_count"] == 1
        assert asset["remaining_capacity"] == 1

    def test_one_minute_of_clearance_lets_the_second_window_in(self, api):
        """Shifting the start to 15:01 pads to 14:31 and clears the boundary instant.

        Both allocations then sit merely reserved, and the PRD keeps that out of
        revenue: "A registration still pending payment, waitlisted, cancelled, or
        refunded contributes nothing here, and neither does an allocation still
        merely reserved or already released."

        Design: Difficulty/resource_temporal_overlap/sponsorship_service_window_is_closed_and_padded_thirty_minutes
        """
        ctx = _station_with_a_noon_window(api)
        validate_error(
            api.create_sponsor_allocation(
                f.sponsor_allocation_payload(
                    ctx["registration_id"],
                    ctx["asset_id"],
                    "UPSELL",
                    service_window_start=TOUCHING_PADDED_START,
                    service_window_end=LATER_END,
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.SERVICE_WINDOW_CONFLICT.value,
            409,
        )

        accepted = validate_success(
            api.create_sponsor_allocation(
                f.sponsor_allocation_payload(
                    ctx["registration_id"],
                    ctx["asset_id"],
                    "UPSELL",
                    service_window_start=CLEAR_START,
                    service_window_end=LATER_END,
                ),
                SPONSORSHIP_HEADERS,
            ),
            201,
        )
        assert_instant_equals(accepted["service_window_start"], CLEAR_START)
        assert accepted["status"] == "RESERVED"

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["reserved_count"] == 2
        assert asset["remaining_capacity"] == 0
        assert asset["status"] == "RESERVED"

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["reserved_asset_slot_count"] == 2
        assert outing["gross_revenue_cents"] == 200000


CART_OUTING = {
    "name": "Cart Turnaround Open",
    "format": "STROKE_PLAY",
    "start_format": "WAVE_SPLIT",
    "wave_b_start": "2026-09-19T16:50:00Z",
    "wave_b_end": "2026-09-19T21:00:00Z",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
PAIR_TIER = {
    "code": "PAIR",
    "kind": "INDIVIDUAL",
    "price_cents": 60000,
    "player_slots": 2,
    "gsv_cents": 12000,
    "inventory_cap": 10,
}
WAVE_B_TEE_TIME = "2026-09-19T16:50:00Z"


def _cart_one_held_in_wave_a(api):
    """A twenty-minute changeover between the waves, with cart 1 out in wave A."""
    ctx = fx.open_outing(api, outing=CART_OUTING, contract=TEN_MINUTE_CONTRACT, tier=PAIR_TIER)
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Cart Testers", player_count=2
    )
    players = [
        fx.new_player(api, registration["id"], full_name=name, handicap_index=12.0)
        for name in ("C1", "C2")
    ]
    fx.pay_registration(api, registration["id"], 60000)
    early = fx.new_team(api, ctx["outing_id"], [players[0]["id"]], team_name="EARLY")
    late = fx.new_team(api, ctx["outing_id"], [players[1]["id"]], team_name="LATE")
    fx.assign_tee(
        api,
        early["id"],
        wave="A",
        starting_hole=1,
        tee_time=NOON,
        cart_number=1,
        headers=COURSE_HEADERS,
        expected_team_version=early["version"],
    )
    ctx["early"] = early
    ctx["late"] = late
    return ctx


class TestCartReuseNeedsATurnaroundGap:
    """A cart is the resource, and the rule is a gap between two disjoint intervals."""

    def test_a_twenty_minute_changeover_is_too_short_to_reissue_the_cart(self, api):
        """Nothing overlaps, and the reissue is still refused.

        The PRD makes the requirement a gap rather than an intersection: "A cart
        may be reused across waves, but it needs tread time. When a `cart_number`
        is reissued to a group in a different wave, the previous holder's wave must
        end at least 30 minutes before the new holder's wave starts." Wave A ends
        at 16:30 and wave B opens at 16:50, so twenty minutes is not enough and
        "Either failure is `ERR_CART_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/cart_reuse_across_waves_needs_a_thirty_minute_turnaround_gap
        """
        ctx = _cart_one_held_in_wave_a(api)
        late = ctx["late"]

        response = api.tee_assignment(
            late["id"],
            f.tee_assignment_payload(
                late["version"],
                wave="B",
                starting_hole=1,
                tee_time=WAVE_B_TEE_TIME,
                cart_number=1,
            ),
            COURSE_HEADERS,
        )
        validate_error(response, ApiErrorId.CART_DOUBLE_BOOKED.value, 409)

        refused = fx.read_team(api, late["id"])
        assert refused["cart_number"] is None
        assert refused["wave"] is None
        assert refused["tee_time"] is None
        assert refused["tee_assignment_count"] == 0
        assert_version_unchanged(refused, late["version"])

    def test_an_unused_cart_number_places_the_late_group_unchanged_otherwise(self, api):
        """Only the cart number differs, and the same wave and tee time are accepted.

        Two distinct cart numbers, one per wave, stay inside the contract's
        allowance of four, and the PRD caps only the number itself and the
        per-wave distinct count: "The requested `cart_number` may not exceed the
        contract's `cart_allowance_count`, and the number of distinct
        `cart_number` values assigned within a single wave may not exceed that
        allowance either."

        Design: Difficulty/resource_temporal_overlap/cart_reuse_across_waves_needs_a_thirty_minute_turnaround_gap
        """
        ctx = _cart_one_held_in_wave_a(api)
        late = ctx["late"]
        validate_error(
            api.tee_assignment(
                late["id"],
                f.tee_assignment_payload(
                    late["version"],
                    wave="B",
                    starting_hole=1,
                    tee_time=WAVE_B_TEE_TIME,
                    cart_number=1,
                ),
                COURSE_HEADERS,
            ),
            ApiErrorId.CART_DOUBLE_BOOKED.value,
            409,
        )

        accepted = api.tee_assignment(
            late["id"],
            f.tee_assignment_payload(
                late["version"],
                wave="B",
                starting_hole=1,
                tee_time=WAVE_B_TEE_TIME,
                cart_number=2,
            ),
            COURSE_HEADERS,
        )
        validate_success(accepted, 200)

        placed = fx.read_team(api, late["id"])
        assert placed["cart_number"] == 2
        assert placed["wave"] == "B"
        assert_instant_equals(placed["tee_time"], WAVE_B_TEE_TIME)
        assert placed["tee_assignment_count"] == 1

        assert fx.read_team(api, ctx["early"]["id"])["cart_number"] == 1
