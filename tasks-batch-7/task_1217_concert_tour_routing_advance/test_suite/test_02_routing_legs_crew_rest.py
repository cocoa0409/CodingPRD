"""Routing legs: derived drive time and the crew-rest boundary (PRD §3.2)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_routing_leg_payload, create_staged_tour, create_tour, create_market,
    create_venue, assert_routing_leg, ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]


class TestRoutingLegComputedDriveTime:
    def test_drive_minutes_computed_on_create(self, api):
        """PRD §3.2: "The system assumes a fleet average speed of 55 miles per
        hour: a leg's `drive_minutes` is the drive distance multiplied by 60
        and divided by 55, rounded half-up to a whole minute." And: "Drive time
        is derived, not entered."

        Design: Corner/entities/routing_leg_computed_drive_minutes
        """
        tour = create_tour(start_clock="2026-05-01T00:00:00Z")
        m1 = create_market(tour["id"], market_code="A", territory_rank=1)
        m2 = create_market(tour["id"], market_code="B", territory_rank=2)

        payload = create_routing_leg_payload(m1["id"], m2["id"], drive_miles=110)
        payload["drive_minutes"] = 9999  # client-supplied value must be ignored
        leg = validate_success(api.create_routing_leg(tour["id"], payload, TM), 201)
        assert_routing_leg(leg)
        assert leg["drive_minutes"] == 120, (
            f"expected round(110*60/55)=120, got {leg['drive_minutes']}")
        assert leg["crew_rest_required"] is False


class TestCrewRestBoundary:
    def test_exactly_480_minutes_no_rest_required(self, api):
        """PRD §3.2: "Whenever that computed drive time is **strictly greater
        than** 480 minutes — eight hours behind the wheel — the leg's
        `crew_rest_required` flag is set to true; at exactly 480 minutes the
        flag remains false."

        Design: Difficulty/boundary_precision_check/crew_rest_at_exactly_480_minutes
        """
        tour = create_tour(start_clock="2026-06-01T00:00:00Z")
        m1 = create_market(tour["id"], market_code="PHX", territory_rank=1)
        m2 = create_market(tour["id"], market_code="TUS", territory_rank=2)
        create_venue(tour["id"], m1["id"])
        validate_success(api.start_routing(tour["id"], TM), 200)

        # 440 miles * 60 / 55 = 480.0 minutes exactly
        leg = validate_success(
            api.create_routing_leg(
                tour["id"],
                create_routing_leg_payload(m1["id"], m2["id"], drive_miles=440,
                                           travel_date="2026-08-10", leg_index=1),
                TM), 201)
        assert leg["drive_minutes"] == 480
        assert leg["crew_rest_required"] is False, (
            "at exactly 480 minutes the flag remains false (strictly-greater rule)")

    def test_481_minutes_rest_required(self, api):
        """PRD §3.2: "Whenever that computed drive time is **strictly greater
        than** 480 minutes — eight hours behind the wheel — the leg's
        `crew_rest_required` flag is set to true; at exactly 480 minutes the
        flag remains false."

        Design: Difficulty/boundary_precision_check/crew_rest_at_exactly_480_minutes
        """
        tour = create_tour(start_clock="2026-06-01T00:00:00Z")
        m1 = create_market(tour["id"], market_code="PHX", territory_rank=1)
        m2 = create_market(tour["id"], market_code="TUS", territory_rank=2)
        create_venue(tour["id"], m1["id"])
        validate_success(api.start_routing(tour["id"], TM), 200)

        # 441 miles * 60 / 55 = 481.09 → 481 minutes, one above the boundary
        leg = validate_success(
            api.create_routing_leg(
                tour["id"],
                create_routing_leg_payload(m1["id"], m2["id"], drive_miles=441,
                                           travel_date="2026-08-11", leg_index=1),
                TM), 201)
        assert leg["drive_minutes"] == 481
        assert leg["crew_rest_required"] is True, "481 > 480 must require rest"


class TestRoutingLegLockAnchoring:
    def test_lock_without_confirmed_shows_rejected(self, api):
        """PRD §3.2: "the origin and destination markets must each contain at
        least one `CONFIRMED` show, unless the leg is a non-production ferry
        leg, in which case the anchor requirement is waived; a leg that fails
        this is rejected with `ERR_LEG_UNANCHORED`."

        Design: Corner/errors/err_leg_unanchored_when_no_confirmed_shows
        """
        staged = create_staged_tour(start_clock="2026-05-01T00:00:00Z")
        tid = staged["tour"]["id"]
        m1 = staged["market"]
        m2 = create_market(tid, market_code="B", metro_name="B", territory_rank=2)
        leg = validate_success(
            api.create_routing_leg(
                tid, create_routing_leg_payload(m1["id"], m2["id"], drive_miles=100,
                                                travel_date="2026-07-15", leg_index=1),
                TM), 201)
        res = api.lock_routing_leg(tid, leg["id"], TM)
        validate_error(res, ApiErrorId.ERR_LEG_UNANCHORED.value)
