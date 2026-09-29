"""Error codes on the inventory and ceiling ledgers.

Four families live in this module: the shapes a tier's selling window may not
take together with per-stop tier-code uniqueness, the per-vehicle branding
ceiling next to per-stop vehicle-number uniqueness, the malformed links the
rotation chain refuses, and the three marketing ceilings in their fixed order.

Every scenario is built inside its own test, because each test runs against a
freshly launched server with an empty database, and every instant comes from the
logical clock rather than the host's wall clock.
"""

from __future__ import annotations

from typing import Any, Dict, List

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_marketing_budget_conserved,
    constants,
    factories,
    fixtures as helpers,
    get_success_data,
    test_users as users,
    validate_error,
    validate_success,
)

# Provisioning that exactly meets the floors of a stop selling 500 seats with no
# live entries on a DIRT floor.
_GA_STOP_PROVISIONING = {
    "barrier_linear_feet": 1200,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 1,
    "medical_bls_staff_count": 2,
    "ambulance_count": 1,
    "emergency_access_lanes": 1,
}

# The Atlanta selling window: it opens at the default clock reading and closes
# five hours before the show starts.
_GA_WINDOW_OPEN = "2026-08-01T00:00:00Z"
_GA_WINDOW_CLOSE = "2026-11-14T18:00:00Z"
_ATL_SHOW_START = "2026-11-14T23:00:00Z"

# Six dates in one market, thirty days apart, so neither the building's calendar
# nor the season's 21-day rotation cooldown can interfere.
_CEILING_DATES = [
    ("2026-10-10", "2026-10-09T14:00:00Z", "2026-10-11T06:00:00Z"),
    ("2026-11-09", "2026-11-08T14:00:00Z", "2026-11-10T06:00:00Z"),
    ("2026-12-09", "2026-12-08T14:00:00Z", "2026-12-10T06:00:00Z"),
    ("2027-01-08", "2027-01-07T14:00:00Z", "2027-01-09T06:00:00Z"),
    ("2027-02-07", "2027-02-06T14:00:00Z", "2027-02-08T06:00:00Z"),
    ("2027-03-09", "2027-03-08T14:00:00Z", "2027-03-10T06:00:00Z"),
]

# A 1,000,000-cent season budget puts the stop ceiling at 200000 and the channel
# ceilings at 80000 (RADIO), 120000 (DIGITAL) and 60000 (GRASSROOTS).
_CEILING_BUDGET_CENTS = 1000000
_STOP_CEILING_CENTS = 200000
_RADIO_CEILING_CENTS = 80000
_DIGITAL_CEILING_CENTS = 120000


def _atl_stop_on_sale(api: ApiClient) -> Dict[str, Any]:
    """An Atlanta stop on sale with a single 500-seat GA tier."""
    return helpers.stop_on_sale(
        api,
        include_second_tier=False,
        segment_type="COMPETITION",
        segment_title="Feature",
        run_order_position=1,
        duration_minutes=40,
        tier_code="GA",
        price_cents=3200,
        allotment=500,
        on_sale_start_utc=_GA_WINDOW_OPEN,
        on_sale_end_utc=_GA_WINDOW_CLOSE,
        channel="RADIO",
        amount_cents=500000,
        **_GA_STOP_PROVISIONING,
    )


def _dallas_stop_with_timing(api: ApiClient, season_id: str) -> Dict[str, Any]:
    """A second stop of the same season, in another market on a later date."""
    return helpers.stop_with_show_timing(
        api,
        season_id=season_id,
        venue_name=constants.SECOND_VENUE_NAME,
        market_code=constants.SECOND_VENUE_MARKET_CODE,
        city=constants.SECOND_VENUE_CITY,
        state_code=constants.SECOND_VENUE_STATE_CODE,
        tour_date=constants.SECOND_TOUR_DATE,
        load_in_start_utc=constants.SECOND_LOAD_IN_START_UTC,
        tear_down_end_utc=constants.SECOND_TEAR_DOWN_END_UTC,
        doors_open_utc=constants.SECOND_DOORS_OPEN_UTC,
        show_start_utc=constants.SECOND_SHOW_START_UTC,
    )


def _omaha_booking(api: ApiClient, season_id: str) -> Dict[str, Any]:
    """A third stop of the same season, in a third market on a later date."""
    return helpers.confirmed_booking(
        api,
        season_id=season_id,
        venue_name=constants.THIRD_VENUE_NAME,
        market_code=constants.THIRD_VENUE_MARKET_CODE,
        city=constants.THIRD_VENUE_CITY,
        state_code=constants.THIRD_VENUE_STATE_CODE,
        seat_capacity=6000,
        floor_type="CONCRETE",
        catch_fence_max_height_ft=9,
        medical_bay_count=1,
        load_in_hours_required=8,
        staging_bay_count=2,
        tour_date=constants.THIRD_TOUR_DATE,
        load_in_start_utc=constants.THIRD_LOAD_IN_START_UTC,
        tear_down_end_utc=constants.THIRD_TEAR_DOWN_END_UTC,
        rental_base_cents=2200000,
        revenue_share_pct=0.10,
        per_ticket_facility_fee_cents=300,
    )


def _phoenix_booking_in_another_season(api: ApiClient) -> Dict[str, Any]:
    """A stop of a second season, earlier than Dallas, for a cross-season link."""
    season = helpers.create_season(
        api,
        season_name="2026-27 Shadow Tour",
        total_marketing_budget_cents=10000000,
    )
    return helpers.confirmed_booking(
        api,
        season_id=season["season_id"],
        venue_name="Phoenix Arena",
        market_code="PHX",
        city="Phoenix",
        state_code="AZ",
        seat_capacity=8000,
        floor_type="DIRT",
        catch_fence_max_height_ft=10,
        medical_bay_count=2,
        load_in_hours_required=9,
        staging_bay_count=3,
        tour_date="2026-11-21",
        load_in_start_utc="2026-11-20T14:00:00Z",
        tear_down_end_utc="2026-11-22T06:00:00Z",
        rental_base_cents=2400000,
        revenue_share_pct=0.10,
        per_ticket_facility_fee_cents=300,
    )


def _rotation_chain_stops(api: ApiClient) -> Dict[str, Any]:
    """Three unlinked stops of one season plus one stop of another season."""
    atlanta = helpers.confirmed_booking(api)
    dallas = helpers.confirmed_booking(
        api,
        season_id=atlanta["season_id"],
        venue_name=constants.SECOND_VENUE_NAME,
        market_code=constants.SECOND_VENUE_MARKET_CODE,
        city=constants.SECOND_VENUE_CITY,
        state_code=constants.SECOND_VENUE_STATE_CODE,
        tour_date=constants.SECOND_TOUR_DATE,
        load_in_start_utc=constants.SECOND_LOAD_IN_START_UTC,
        tear_down_end_utc=constants.SECOND_TEAR_DOWN_END_UTC,
        rental_base_cents=2900000,
        revenue_share_pct=0.11,
        per_ticket_facility_fee_cents=400,
    )
    omaha = _omaha_booking(api, atlanta["season_id"])
    phoenix = _phoenix_booking_in_another_season(api)
    return {
        "season_id": atlanta["season_id"],
        "atlanta": atlanta["stop_id"],
        "dallas": dallas["stop_id"],
        "omaha": omaha["stop_id"],
        "phoenix": phoenix["stop_id"],
    }


def _link_stops(
    api: ApiClient, stop_id: str, predecessor_id: str, haul_distance_miles: int = 0
):
    """Point one stop at another as its predecessor, carrying the road miles."""
    payload: Dict[str, Any] = {"preceding_stop_id": predecessor_id}
    if haul_distance_miles:
        payload["haul_distance_miles"] = haul_distance_miles
    return api.update_tour_stop_logistics(
        stop_id, payload, headers=users.make_series_promoter_headers()
    )


def _branding_stage(api: ApiClient) -> Dict[str, Any]:
    """Two stops, two teams, one entry numbered 7 and three proposed packages.

    All three packages brand the same entry and ask for 3, 2 and 1 slots, and all
    three are proposed while the entry has no committed slots at all.
    """
    atlanta = helpers.stop_with_show_timing(api)
    dallas = _dallas_stop_with_timing(api, atlanta["season_id"])
    alpha = helpers.create_competitor(
        api,
        team_name="Alpha Racing",
        driver_name="K. Sato",
        home_market_code="CLT",
        vehicle_class="LIGHT",
    )
    bravo = helpers.create_competitor(
        api,
        team_name="Bravo Racing",
        driver_name="L. Ortiz",
        home_market_code="PHX",
        vehicle_class="LIGHT",
    )
    entry = helpers.create_vehicle_entry(
        api,
        atlanta["stop_id"],
        competitor_id=alpha["competitor_id"],
        vehicle_number="7",
        vehicle_weight_lbs=7000,
        entry_haul_distance_miles=100,
        scheduled_arrival_utc="2026-11-14T16:00:00Z",
    )

    packages: List[Dict[str, Any]] = []
    for company, category, fee, slots, signage in (
        ("Apex Tire", "TIRE", 900000, 3, 6),
        ("Delta Fuel", "FUEL", 500000, 2, 4),
        ("Gamma Oil", "BEVERAGE", 300000, 1, 2),
    ):
        # No sponsor claims category exclusivity, so nothing but the branding
        # ceiling can stand between a package and activation.
        sponsor = helpers.create_sponsor(
            api,
            company_name=company,
            sponsor_category=category,
            contact_email=f"rep@{company.split()[0].lower()}.example",
            exclusive_category=False,
        )
        packages.append(
            helpers.create_sponsorship_activation(
                api,
                atlanta["stop_id"],
                sponsor_id=sponsor["sponsor_id"],
                branded_vehicle_entry_id=entry["entry_id"],
                fee_cents=fee,
                vehicle_branding_slots=slots,
                signage_units=signage,
            )
        )

    return {
        "season_id": atlanta["season_id"],
        "atlanta": atlanta["stop_id"],
        "dallas": dallas["stop_id"],
        "alpha_id": alpha["competitor_id"],
        "bravo_id": bravo["competitor_id"],
        "entry_id": entry["entry_id"],
        "three_slots": packages[0],
        "two_slots": packages[1],
        "one_slot": packages[2],
    }


def _enter_number_seven(
    api: ApiClient, stop_id: str, competitor_id: str, scheduled_arrival_utc: str
):
    """Enter a light vehicle numbered 7 for the team at the stop."""
    return api.create_vehicle_entry(
        factories.make_vehicle_entry_payload(
            competitor_id,
            stop_id,
            vehicle_number="7",
            vehicle_weight_lbs=7000,
            haul_distance_miles=100,
            scheduled_arrival_utc=scheduled_arrival_utc,
        ),
        headers=users.make_series_promoter_headers(),
    )


def _drained_marketing_season(api: ApiClient) -> Dict[str, Any]:
    """One season whose whole marketing pool is committed across five markets.

    Six dates are booked in the same building; the first five stops are each
    filled to exactly their 200000-cent ceiling with 80000 of RADIO and 120000 of
    DIGITAL, which leaves the season pool empty and the sixth stop untouched.
    """
    season = helpers.create_season(
        api,
        season_name="Budget Ceiling Tour",
        total_marketing_budget_cents=_CEILING_BUDGET_CENTS,
    )
    venue = helpers.create_venue(api)

    stop_ids: List[str] = []
    for tour_date, load_in_start_utc, tear_down_end_utc in _CEILING_DATES:
        booking = helpers.confirmed_booking(
            api,
            season_id=season["season_id"],
            venue_id=venue["venue_id"],
            tour_date=tour_date,
            load_in_start_utc=load_in_start_utc,
            tear_down_end_utc=tear_down_end_utc,
        )
        stop_ids.append(booking["stop_id"])

    release_allocation_id = None
    for stop_id in stop_ids[:5]:
        for channel, amount_cents in (
            ("RADIO", _RADIO_CEILING_CENTS),
            ("DIGITAL", _DIGITAL_CEILING_CENTS),
        ):
            committed = helpers.commit_marketing_allocation(
                api,
                stop_id,
                season["season_id"],
                channel=channel,
                amount_cents=amount_cents,
            )
            if release_allocation_id is None:
                release_allocation_id = committed["allocation_id"]

    ledger = helpers.fetch_season(api, season["season_id"])
    assert ledger["marketing_allocated_cents"] == _CEILING_BUDGET_CENTS
    assert ledger["marketing_unallocated_cents"] == 0

    return {
        "season_id": season["season_id"],
        "stop_ids": stop_ids,
        "release_allocation_id": release_allocation_id,
    }


class TestTierWindowShapeAndCodeUniqueness:
    """Tier codes are unique per stop and the selling window has a legal shape."""

    def test_repeated_tier_code_on_the_same_stop_is_rejected(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.6: "A tier declares a `tier_code` that must be unique among the stop's tiers — a repeat is rejected with `ERR_DUPLICATE_TIER_CODE` — a face `price_cents` of zero or more, and an `allotment` of at least 1 seat, which is the conserved seat pool for that tier."

        Design: Corner/errors/corner_error_tier_window_shape_and_code_uniqueness
        """
        state = _atl_stop_on_sale(api)

        rejected = api.create_ticket_tier(
            state["stop_id"],
            factories.make_ticket_tier_payload(
                tier_code="GA",
                price_cents=4000,
                allotment=100,
                on_sale_start_utc=_GA_WINDOW_OPEN,
                on_sale_end_utc=_GA_WINDOW_CLOSE,
            ),
            headers=ticketing_headers,
        )

        validate_error(rejected, ApiErrorId.ERR_DUPLICATE_TIER_CODE)
        tiers = get_success_data(
            api.list_ticket_tiers(state["stop_id"], headers=ticketing_headers)
        )
        assert [tier["tier_code"] for tier in tiers] == ["GA"]

    def test_window_that_opens_when_it_closes_is_rejected(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.6: "The selling window is declared as `on_sale_start_utc` and `on_sale_end_utc`; `on_sale_start_utc` must be strictly earlier than `on_sale_end_utc` and `on_sale_end_utc` may not fall after the stop's `show_start_utc`, or the tier is rejected with `ERR_TIER_WINDOW_INVALID`."

        Design: Corner/errors/corner_error_tier_window_shape_and_code_uniqueness
        """
        state = _atl_stop_on_sale(api)

        # Start and end on the same instant is not a window: the comparison is
        # strict.
        rejected = api.create_ticket_tier(
            state["stop_id"],
            factories.make_ticket_tier_payload(
                tier_code="CLUB",
                price_cents=5000,
                allotment=100,
                on_sale_start_utc=_GA_WINDOW_CLOSE,
                on_sale_end_utc=_GA_WINDOW_CLOSE,
            ),
            headers=ticketing_headers,
        )

        validate_error(rejected, ApiErrorId.ERR_TIER_WINDOW_INVALID)
        tiers = get_success_data(
            api.list_ticket_tiers(state["stop_id"], headers=ticketing_headers)
        )
        assert [tier["tier_code"] for tier in tiers] == ["GA"]

    def test_window_closing_one_second_past_show_start_is_rejected(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.6: "The selling window is declared as `on_sale_start_utc` and `on_sale_end_utc`; `on_sale_start_utc` must be strictly earlier than `on_sale_end_utc` and `on_sale_end_utc` may not fall after the stop's `show_start_utc`, or the tier is rejected with `ERR_TIER_WINDOW_INVALID`."

        Design: Corner/errors/corner_error_tier_window_shape_and_code_uniqueness
        """
        state = _atl_stop_on_sale(api)
        assert state["stop"]["show_start_utc"] == _ATL_SHOW_START

        # The window may touch show start but not pass it, so one second past it
        # is out.
        rejected = api.create_ticket_tier(
            state["stop_id"],
            factories.make_ticket_tier_payload(
                tier_code="CLUB",
                price_cents=5000,
                allotment=100,
                on_sale_start_utc=_GA_WINDOW_OPEN,
                on_sale_end_utc="2026-11-14T23:00:01Z",
            ),
            headers=ticketing_headers,
        )

        validate_error(rejected, ApiErrorId.ERR_TIER_WINDOW_INVALID)

    def test_same_tier_code_is_free_on_another_stop(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.6: "A tier declares a `tier_code` that must be unique among the stop's tiers — a repeat is rejected with `ERR_DUPLICATE_TIER_CODE` — a face `price_cents` of zero or more, and an `allotment` of at least 1 seat, which is the conserved seat pool for that tier."

        Design: Corner/errors/corner_error_tier_window_shape_and_code_uniqueness
        """
        state = _atl_stop_on_sale(api)
        dallas = _dallas_stop_with_timing(api, state["season_id"])

        admitted = api.create_ticket_tier(
            dallas["stop_id"],
            factories.make_ticket_tier_payload(
                tier_code="GA",
                price_cents=3200,
                allotment=500,
                on_sale_start_utc=_GA_WINDOW_OPEN,
                on_sale_end_utc="2026-12-05T18:00:00Z",
            ),
            headers=ticketing_headers,
        )

        # Uniqueness is scoped to the stop, so GA is free in the second market.
        tier = validate_success(admitted, 201)
        assert tier["tier_code"] == "GA"
        assert tier["tour_stop_id"] == dallas["stop_id"]

    def test_order_at_the_close_bound_is_admitted_and_one_second_later_is_not(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "The current logical clock must sit inside the tier's selling window running from `on_sale_start_utc` to `on_sale_end_utc`, with both bounds inclusive; outside it, the order is rejected with `ERR_TIER_WINDOW_CLOSED`."

        Design: Corner/errors/corner_error_tier_window_shape_and_code_uniqueness
        """
        state = _atl_stop_on_sale(api)
        tier_id = state["tier_id"]

        version = helpers.fetch_tier_version(api, tier_id)
        helpers.set_clock(api, _GA_WINDOW_CLOSE)
        admitted = api.create_ticket_order(
            factories.make_ticket_order_payload(
                state["stop_id"],
                tier_id,
                version,
                qty=2,
                purchaser_name="Last Second",
                purchaser_email="last@example.com",
            ),
            headers=ticketing_headers,
        )

        # 2 * 3200 of face value plus 2 * 350 of facility fee, with no discount.
        order = validate_success(admitted, 201)
        assert order["total_cents"] == 7100
        assert helpers.fetch_tier(api, tier_id)["reserved_seat_count"] == 2

        helpers.set_clock(api, "2026-11-14T18:00:01Z")
        version = helpers.fetch_tier_version(api, tier_id)
        rejected = api.create_ticket_order(
            factories.make_ticket_order_payload(
                state["stop_id"],
                tier_id,
                version,
                qty=2,
                purchaser_name="One Second Late",
                purchaser_email="late@example.com",
            ),
            headers=ticketing_headers,
        )

        validate_error(rejected, ApiErrorId.ERR_TIER_WINDOW_CLOSED)
        assert helpers.fetch_tier(api, tier_id)["reserved_seat_count"] == 2


class TestBrandingCeilingAndDuplicateVehicleNumber:
    """Branding slots are counted per vehicle, vehicle numbers per stop and team."""

    def test_three_proposals_do_not_collide_before_any_is_activated(
        self, api: ApiClient
    ) -> None:
        """PRD §3.8: "The `vehicle_branding_slots` are added to the branded entry's `branding_slots_committed`, which is the sum of slots over activations naming that entry in `ACTIVATED` or `FULFILLED`."

        Design: Corner/errors/corner_error_branding_ceiling_and_duplicate_vehicle_number
        """
        state = _branding_stage(api)

        # 3 + 2 + 1 is six proposed slots on one vehicle, and none of them counts
        # until its package is activated.
        for package in ("three_slots", "two_slots", "one_slot"):
            assert state[package]["activation"]["state"] == "PROPOSED"
        assert helpers.fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 0

    def test_proposal_past_four_committed_slots_is_rejected(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.8: "At proposal time the branding capacity and hospitality capacity are already checked: committed slots on the branded entry plus the requested `vehicle_branding_slots` may not exceed 4 slots per vehicle, or the proposal is rejected with `ERR_BRANDING_SLOTS_EXCEEDED`; and the hospitality seats already held on the named tier plus the requested `hospitality_seat_count` may not push past that tier's `allotment`, or the proposal is rejected with `ERR_HOSPITALITY_SEATS_EXCEEDED`."

        Design: Corner/errors/corner_error_branding_ceiling_and_duplicate_vehicle_number
        """
        state = _branding_stage(api)
        get_success_data(
            api.activate_sponsorship_activation(
                state["three_slots"]["activation_id"], headers=promoter_headers
            )
        )
        assert helpers.fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 3

        rejected = api.create_sponsorship_activation(
            factories.make_sponsorship_activation_payload(
                state["two_slots"]["sponsor_id"],
                state["atlanta"],
                branded_vehicle_entry_id=state["entry_id"],
                fee_cents=500000,
                vehicle_branding_slots=2,
                signage_units=4,
            ),
            headers=promoter_headers,
        )

        # Three committed slots plus two more is five, past the four the vehicle
        # can carry.
        validate_error(rejected, ApiErrorId.ERR_BRANDING_SLOTS_EXCEEDED)
        assert helpers.fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 3

    def test_activation_at_exactly_four_slots_is_admitted(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.8: "When `vehicle_branding_slots` is greater than 0, `branded_vehicle_entry_id` must be set, must belong to the same stop, and the entry's `branding_slots_committed` plus the requested slots must not exceed 4."

        Design: Corner/errors/corner_error_branding_ceiling_and_duplicate_vehicle_number
        """
        state = _branding_stage(api)
        get_success_data(
            api.activate_sponsorship_activation(
                state["three_slots"]["activation_id"], headers=promoter_headers
            )
        )

        admitted = api.activate_sponsorship_activation(
            state["one_slot"]["activation_id"], headers=promoter_headers
        )

        # Three committed plus one requested lands exactly on the ceiling.
        activation = validate_success(admitted)
        assert activation["state"] == "ACTIVATED"
        assert helpers.fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 4
        stop = helpers.fetch_stop(api, state["atlanta"])
        assert stop["sponsorship_committed_cents"] == 1200000

    def test_same_vehicle_number_for_the_same_team_at_the_same_stop_is_rejected(
        self, api: ApiClient
    ) -> None:
        """PRD §3.3: "A team may not field two live entries with the same `vehicle_number` at the same stop — if the competitor already has a non-`WITHDRAWN` entry with that number on that stop, the request is rejected with `ERR_DUPLICATE_VEHICLE_ENTRY`."

        Design: Corner/errors/corner_error_branding_ceiling_and_duplicate_vehicle_number
        """
        state = _branding_stage(api)

        rejected = _enter_number_seven(
            api, state["atlanta"], state["alpha_id"], "2026-11-14T16:00:00Z"
        )

        validate_error(rejected, ApiErrorId.ERR_DUPLICATE_VEHICLE_ENTRY)
        entries = get_success_data(
            api.list_vehicle_entries(
                {"tour_stop_id": state["atlanta"]},
                headers=users.make_series_promoter_headers(),
            )
        )
        assert len(entries) == 1

    def test_same_vehicle_number_is_free_for_another_team(self, api: ApiClient) -> None:
        """PRD §3.3: "A team may not field two live entries with the same `vehicle_number` at the same stop — if the competitor already has a non-`WITHDRAWN` entry with that number on that stop, the request is rejected with `ERR_DUPLICATE_VEHICLE_ENTRY`."

        Design: Corner/errors/corner_error_branding_ceiling_and_duplicate_vehicle_number
        """
        state = _branding_stage(api)

        admitted = _enter_number_seven(
            api, state["atlanta"], state["bravo_id"], "2026-11-14T16:00:00Z"
        )

        # The number is only reserved against the team that painted it.
        entry = validate_success(admitted, 201)
        assert entry["vehicle_number"] == "7"
        assert entry["competitor_id"] == state["bravo_id"]

    def test_same_vehicle_number_is_free_for_the_same_team_at_another_stop(
        self, api: ApiClient
    ) -> None:
        """PRD §3.3: "A team may not field two live entries with the same `vehicle_number` at the same stop — if the competitor already has a non-`WITHDRAWN` entry with that number on that stop, the request is rejected with `ERR_DUPLICATE_VEHICLE_ENTRY`."

        Design: Corner/errors/corner_error_branding_ceiling_and_duplicate_vehicle_number
        """
        state = _branding_stage(api)

        admitted = _enter_number_seven(
            api, state["dallas"], state["alpha_id"], "2026-12-05T16:00:00Z"
        )

        entry = validate_success(admitted, 201)
        assert entry["tour_stop_id"] == state["dallas"]
        # The candidate bays are those of the booked venue minus the bays held by
        # live entries of the same stop, so a light rig opens the second market at
        # the lowest index.
        assert entry["staging_bay_index"] == 1


class TestRotationChainRejectsMalformedLinks:
    """The transport chain stays a simple path inside one season."""

    def test_predecessor_from_another_season_is_rejected(self, api: ApiClient) -> None:
        """PRD §3.2: "Four conditions make a chain link invalid, and all four are rejected with `ERR_ROTATION_CHAIN_INVALID`: the named predecessor is the stop itself; the predecessor belongs to a different season; the predecessor's `event_date` is on or after this stop's `event_date`; or some other stop already points at that predecessor, since a stop may be the predecessor of at most one successor."

        Design: Corner/errors/corner_error_rotation_chain_rejects_every_malformed_link
        """
        stops = _rotation_chain_stops(api)

        # Phoenix exists and is dated well before Dallas, and its tear-down clears
        # the Dallas load-in by weeks, so only the season boundary is at issue.
        rejected = _link_stops(api, stops["dallas"], stops["phoenix"])

        validate_error(rejected, ApiErrorId.ERR_ROTATION_CHAIN_INVALID)
        assert helpers.fetch_stop(api, stops["dallas"])["preceding_stop_id"] is None

    def test_predecessor_already_claimed_by_another_stop_is_rejected(
        self, api: ApiClient
    ) -> None:
        """PRD §3.2: "Four conditions make a chain link invalid, and all four are rejected with `ERR_ROTATION_CHAIN_INVALID`: the named predecessor is the stop itself; the predecessor belongs to a different season; the predecessor's `event_date` is on or after this stop's `event_date`; or some other stop already points at that predecessor, since a stop may be the predecessor of at most one successor."

        Design: Corner/errors/corner_error_rotation_chain_rejects_every_malformed_link
        """
        stops = _rotation_chain_stops(api)
        validate_success(_link_stops(api, stops["dallas"], stops["atlanta"], 800))

        # Atlanta is spoken for, and 900 miles of haul leaves the Omaha load-in
        # far outside the buffer, so the claim is the only objection.
        rejected = _link_stops(api, stops["omaha"], stops["atlanta"], 900)

        validate_error(rejected, ApiErrorId.ERR_ROTATION_CHAIN_INVALID)
        assert helpers.fetch_stop(api, stops["omaha"])["preceding_stop_id"] is None
        assert (
            helpers.fetch_stop(api, stops["dallas"])["preceding_stop_id"]
            == stops["atlanta"]
        )

    def test_valid_links_build_a_queryable_chain(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.2: "The transport chain is expressed by `preceding_stop_id`, which points at the stop the transporters are coming from and is null for the first stop of a chain."

        Design: Corner/errors/corner_error_rotation_chain_rejects_every_malformed_link
        """
        stops = _rotation_chain_stops(api)

        dallas = validate_success(
            _link_stops(api, stops["dallas"], stops["atlanta"], 800)
        )
        assert dallas["preceding_stop_id"] == stops["atlanta"]
        assert dallas["haul_distance_miles"] == 800

        omaha = validate_success(_link_stops(api, stops["omaha"], stops["dallas"], 700))
        assert omaha["preceding_stop_id"] == stops["dallas"]

        # The chain now runs Atlanta -> Dallas -> Omaha, and Dallas has exactly
        # one successor.
        successors = get_success_data(
            api.list_tour_stops(
                {"preceding_stop_id": stops["dallas"]}, headers=promoter_headers
            )
        )
        assert [stop["id"] for stop in successors] == [stops["omaha"]]


class TestMarketingCeilingsFireInChannelStopThenPoolOrder:
    """The narrowest ceiling always answers first, the season pool last."""

    def test_channel_ceiling_answers_first(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.9: "First, the channel running total after this commit — the sum of `amount_cents` over the stop's `COMMITTED` allocations on the same channel, plus this `amount_cents` — must not exceed that channel's ceiling, or the request is rejected with `ERR_CHANNEL_CAP_EXCEEDED`."

        Design: Corner/errors/corner_error_marketing_ceilings_fire_in_channel_stop_then_pool_order
        """
        state = _drained_marketing_season(api)
        untouched_stop = state["stop_ids"][5]
        version = helpers.fetch_season_version(api, state["season_id"])

        rejected = api.create_marketing_allocation(
            untouched_stop,
            factories.make_marketing_allocation_payload(
                version, channel="RADIO", amount_cents=_RADIO_CEILING_CENTS + 1
            ),
            headers=promoter_headers,
        )

        # One cent past the RADIO ceiling on a stop with nothing on it: the empty
        # season pool would refuse it too, but the channel is checked first.
        validate_error(rejected, ApiErrorId.ERR_CHANNEL_CAP_EXCEEDED)
        assert helpers.fetch_season_version(api, state["season_id"]) == version
        assert helpers.fetch_stop(api, untouched_stop)["marketing_spend_committed_cents"] == 0

    def test_stop_ceiling_answers_before_the_season_pool(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.9: "Second, the stop running total after this commit — the stop's `marketing_spend_committed_cents` plus this `amount_cents` — must not exceed the stop ceiling, or the request is rejected with `ERR_STOP_MARKETING_CAP_EXCEEDED`."

        Design: Corner/errors/corner_error_marketing_ceilings_fire_in_channel_stop_then_pool_order
        """
        state = _drained_marketing_season(api)
        filled_stop = state["stop_ids"][0]
        assert (
            helpers.fetch_stop(api, filled_stop)["marketing_spend_committed_cents"]
            == _STOP_CEILING_CENTS
        )
        version = helpers.fetch_season_version(api, state["season_id"])

        rejected = api.create_marketing_allocation(
            filled_stop,
            factories.make_marketing_allocation_payload(
                version, channel="GRASSROOTS", amount_cents=1
            ),
            headers=promoter_headers,
        )

        # One cent of GRASSROOTS is far inside that channel's 60000 ceiling, but it
        # pushes the stop to 200001.
        validate_error(rejected, ApiErrorId.ERR_STOP_MARKETING_CAP_EXCEEDED)
        assert helpers.fetch_season_version(api, state["season_id"]) == version
        assert (
            helpers.fetch_stop(api, filled_stop)["marketing_spend_committed_cents"]
            == _STOP_CEILING_CENTS
        )

    def test_season_pool_answers_when_the_narrower_ceilings_are_clear(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.9: "Third, `amount_cents` must not exceed the season's `marketing_unallocated_cents`, or the request is rejected with `ERR_MARKETING_BUDGET_EXCEEDED`."

        Design: Corner/errors/corner_error_marketing_ceilings_fire_in_channel_stop_then_pool_order
        """
        state = _drained_marketing_season(api)
        untouched_stop = state["stop_ids"][5]
        version = helpers.fetch_season_version(api, state["season_id"])

        rejected = api.create_marketing_allocation(
            untouched_stop,
            factories.make_marketing_allocation_payload(
                version, channel="DIGITAL", amount_cents=1
            ),
            headers=promoter_headers,
        )

        # One cent of DIGITAL on an empty stop clears both the channel ceiling and
        # the stop ceiling, so only the exhausted pool is left to refuse it.
        validate_error(rejected, ApiErrorId.ERR_MARKETING_BUDGET_EXCEEDED)
        assert helpers.fetch_season_version(api, state["season_id"]) == version

    def test_releasing_an_allocation_readmits_the_refused_commit(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.9: "Releasing an allocation moves it from `COMMITTED` to `RELEASED`, stamps `released_at` from the logical clock, and applies exactly the inverse deltas: the amount comes off `marketing_allocated_cents`, `marketing_unallocated_cents` is restored, the season's `version` increments by one, the stop's `marketing_spend_committed_cents` falls, and the posture is recomputed — which can pull a stop back to `RESTRICTED` if the release leaves the market with no committed spend at all, halting an `ON_SALE` stop."

        Design: Corner/errors/corner_error_marketing_ceilings_fire_in_channel_stop_then_pool_order
        """
        state = _drained_marketing_season(api)
        first_stop, untouched_stop = state["stop_ids"][0], state["stop_ids"][5]

        version = helpers.fetch_season_version(api, state["season_id"])
        refused = api.create_marketing_allocation(
            untouched_stop,
            factories.make_marketing_allocation_payload(
                version, channel="DIGITAL", amount_cents=1
            ),
            headers=promoter_headers,
        )
        validate_error(refused, ApiErrorId.ERR_MARKETING_BUDGET_EXCEEDED)

        released = validate_success(
            api.release_marketing_allocation(
                state["release_allocation_id"], headers=promoter_headers
            )
        )

        assert released["state"] == "RELEASED"
        season = helpers.fetch_season(api, state["season_id"])
        assert season["marketing_allocated_cents"] == 920000
        assert season["marketing_unallocated_cents"] == _RADIO_CEILING_CENTS
        assert_marketing_budget_conserved(season)
        assert (
            helpers.fetch_stop(api, first_stop)["marketing_spend_committed_cents"]
            == _DIGITAL_CEILING_CENTS
        )

        version = helpers.fetch_season_version(api, state["season_id"])
        admitted = api.create_marketing_allocation(
            untouched_stop,
            factories.make_marketing_allocation_payload(
                version, channel="DIGITAL", amount_cents=1
            ),
            headers=promoter_headers,
        )

        # The freed 80000 cents make the same one-cent commit admissible.
        allocation = validate_success(admitted, 201)
        assert allocation["state"] == "COMMITTED"
        assert allocation["amount_cents"] == 1
