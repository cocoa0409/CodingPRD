"""Assignment gates: overlap, capacity, eligibility, equipment (PRD §2.7, §3.3)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_client_agent_headers, make_coordinator_headers, make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_ready_booking, assign_booking, get_booking, get_photographer,
    submit_and_prepare, confirm_booking,
)


class TestTravelBufferOverlap:
    def test_open_interval_semantics_touching_allowed_inside_rejected(self, api):
        """PRD §2.7: "Because the intersection test treats the widened intervals as
        open, adjacency is permitted when the gap between two shoots is at least the
        travel buffer — a gap exactly equal to the buffer is allowed, while anything
        shorter is a conflict rejected with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` (HTTP 409)."

        Booking A occupies [14:00, 15:00); with a 45-minute buffer the exclusion zone
        is (13:15, 15:45): a second booking at exactly 15:45 is allowed, while 15:30
        collides.

        Design: Difficulty/resource_temporal_overlap/photographer_travel_buffer_open_interval_semantics
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=45)
        photog = create_photographer(market["id"], full_name="Buf Bob", email="bob@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])

        b1 = create_ready_booking(agent, market["id"], order_ref="ORD-T1",
                                  property_address="1 Buf Ave", photo_count=20,
                                  scheduled_start_utc="2026-08-10T14:00:00Z")
        assign_booking(b1["id"], photog["id"])

        b2 = create_ready_booking(agent, market["id"], order_ref="ORD-T2",
                                  property_address="2 Buf Ave", photo_count=20,
                                  scheduled_start_utc="2026-08-10T15:45:00Z")
        b3 = create_ready_booking(agent, market["id"], order_ref="ORD-T3",
                                  property_address="3 Buf Ave", photo_count=20,
                                  scheduled_start_utc="2026-08-10T15:30:00Z")

        # gap == buffer exactly (15:00 end + 45m): allowed by open-interval semantics
        assigned = validate_success(api_client.assign_booking(b2["id"], photog["id"],
                                                              make_coordinator_headers()))
        assert assigned["assigned_photographer_id"] == photog["id"]

        # gap < buffer: inside the widened exclusion zone
        resp = api_client.assign_booking(b3["id"], photog["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_DOUBLE_BOOKED)
        assert get_booking(b3["id"])["assigned_photographer_id"] is None

    def test_gap_shorter_than_buffer_is_conflict_regardless_of_side(self, api):
        """PRD §2.7: "For a candidate window, the server widens both ends by the
        market's `travel_buffer_minutes` and tests the widened interval against every
        other booking assigned to that photographer in `ASSIGNED`,
        `AUTHORIZATION_PENDING`, or `CONFIRMED` state. ... a gap exactly equal to the
        buffer is allowed, while anything shorter is a conflict rejected with
        `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` (HTTP 409)."

        The buffer widens BOTH ends: a candidate 30 minutes BEFORE an existing shoot
        collides symmetrically with one 30 minutes after.

        Design: Difficulty/resource_temporal_overlap/photographer_travel_buffer_open_interval_semantics
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=45)
        photog = create_photographer(market["id"], full_name="Buf Bob", email="bob@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])

        b1 = create_ready_booking(agent, market["id"], order_ref="ORD-T4",
                                  property_address="4 Buf Ave", photo_count=20,
                                  scheduled_start_utc="2026-08-10T14:00:00Z")
        assign_booking(b1["id"], photog["id"])

        # candidate ends at 13:30, only 30 minutes before the 14:00 start: the
        # widened zone (13:15, 15:45) swallows it
        b0 = create_ready_booking(agent, market["id"], order_ref="ORD-T0",
                                  property_address="0 Buf Ave", photo_count=20,
                                  scheduled_start_utc="2026-08-10T12:30:00Z")
        resp = api_client.assign_booking(b0["id"], photog["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_DOUBLE_BOOKED)
        assert get_booking(b0["id"])["state"] == "READY"

    def test_twilight_slot_exclusivity_ignores_buffer(self, api):
        """PRD §2.7: "twilight slots are exclusive per photographer per evening: two
        twilight bookings for the same photographer in the same market on the same
        evening always conflict, regardless of the buffer, because the overlap test for
        twilight work is applied to the raw slot interval before any buffer expansion."

        Design: Difficulty/resource_temporal_overlap/twilight_slot_exclusivity_different_semantics
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=45, twilight_slot_minutes=60)
        photog = create_photographer(market["id"], full_name="Twilight Tess", email="tess@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])

        tw1 = create_ready_booking(agent, market["id"], order_ref="ORD-TW1",
                                   property_address="1 Dusk Dr", photo_count=20,
                                   scheduled_start_utc="2026-08-10T19:00:00Z", is_twilight=True)
        assign_booking(tw1["id"], photog["id"])

        tw2 = create_ready_booking(agent, market["id"], order_ref="ORD-TW2",
                                   property_address="2 Dusk Dr", photo_count=20,
                                   scheduled_start_utc="2026-08-10T21:00:00Z", is_twilight=True)
        # raw gap is 120 minutes > 45-minute buffer — but twilight exclusivity rejects
        resp = api_client.assign_booking(tw2["id"], photog["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_DOUBLE_BOOKED)
        tw2_after = get_booking(tw2["id"])
        assert tw2_after["state"] == "READY"
        assert tw2_after["assigned_photographer_id"] is None

    def test_twilight_and_non_twilight_same_photographer_buffer_applies(self, api):
        """PRD §2.7: "twilight slots are exclusive per photographer per evening: two
        twilight bookings for the same photographer in the same market on the same
        evening always conflict, regardless of the buffer, because the overlap test for
        twilight work is applied to the raw slot interval before any buffer expansion."
        PRD §2.7: "a gap exactly equal to the buffer is allowed, while anything shorter
        is a conflict rejected with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` (HTTP 409)."

        The exclusivity is twilight-vs-twilight: a non-twilight booking two hours after
        a twilight slot clears the 45-minute buffer and assigns cleanly.

        Design: Difficulty/resource_temporal_overlap/twilight_slot_exclusivity_different_semantics
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=45, twilight_slot_minutes=60)
        photog = create_photographer(market["id"], full_name="Twilight Tess", email="tess@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])

        tw1 = create_ready_booking(agent, market["id"], order_ref="ORD-TW3",
                                   property_address="3 Dusk Dr", photo_count=20,
                                   scheduled_start_utc="2026-08-10T19:00:00Z", is_twilight=True)
        assign_booking(tw1["id"], photog["id"])

        # non-twilight booking at 21:00: slot ends 20:00, gap 60 >= buffer 45 -> allowed
        plain = create_ready_booking(agent, market["id"], order_ref="ORD-TW4",
                                     property_address="4 Dusk Dr", photo_count=20,
                                     scheduled_start_utc="2026-08-10T21:00:00Z")
        assigned = validate_success(api_client.assign_booking(
            plain["id"], photog["id"], make_coordinator_headers()))
        assert assigned["state"] == "ASSIGNED"
        assert assigned["assigned_photographer_id"] == photog["id"]


class TestDayCapacity:
    def test_day_capacity_equal_vs_greater_boundary(self, api):
        """PRD §2.7: "Adding a booking's window to a photographer's day must not push
        that day's total over the photographer's `max_shoot_minutes_per_day`; a total
        exactly equal to the cap is permitted, and only a strictly greater total is
        rejected with `ERR_DAY_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/day_capacity_equal_vs_greater_boundary
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=0)
        photog = create_photographer(market["id"], full_name="Cap Carla", email="carla@x.com",
                                     equipment_packages=["STANDARD"], max_shoot_minutes_per_day=120)
        agent = create_agent(market["id"])

        b1 = create_ready_booking(agent, market["id"], order_ref="ORD-C1",
                                  property_address="1 Cap St", photo_count=20,
                                  scheduled_start_utc="2026-08-10T08:00:00Z")
        assign_booking(b1["id"], photog["id"])  # 60 of 120 used

        # lands the day total exactly at the cap (60 + 60 == 120): allowed
        b2 = create_ready_booking(agent, market["id"], order_ref="ORD-C2",
                                  property_address="2 Cap St", photo_count=20,
                                  scheduled_start_utc="2026-08-10T10:00:00Z")
        validate_success(api_client.assign_booking(b2["id"], photog["id"],
                                                   make_coordinator_headers()))
        assert get_photographer(photog["id"])["committed_minutes_by_day"]["2026-08-10"] == 120

        # 70 more minutes would land at 190 > 120: strictly greater, rejected
        b3 = create_ready_booking(agent, market["id"], order_ref="ORD-C3",
                                  property_address="3 Cap St", photo_count=26,
                                  scheduled_start_utc="2026-08-10T13:00:00Z")
        resp = api_client.assign_booking(b3["id"], photog["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_DAY_CAPACITY_EXCEEDED)


    def test_day_capacity_counts_only_same_utc_day(self, api):
        """PRD §2.7: "Each photographer maintains `committed_minutes_by_day`, a map
        from UTC calendar date (in `YYYY-MM-DD` form) to the total committed,
        non-cancelled shoot minutes for that day, recomputed on every assignment
        change. Adding a booking's window to a photographer's day must not push that
        day's total over the photographer's `max_shoot_minutes_per_day`; a total
        exactly equal to the cap is permitted, and only a strictly greater total is
        rejected with `ERR_DAY_CAPACITY_EXCEEDED` (HTTP 409)."

        Minutes committed on a different UTC day do not count: the cap is per-day.

        Design: Difficulty/boundary_precision_check/day_capacity_equal_vs_greater_boundary
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=0)
        photog = create_photographer(market["id"], full_name="Cap Carla", email="carla@x.com",
                                     equipment_packages=["STANDARD"], max_shoot_minutes_per_day=120)
        agent = create_agent(market["id"])

        b1 = create_ready_booking(agent, market["id"], order_ref="ORD-C4",
                                  property_address="4 Cap St", photo_count=20,
                                  scheduled_start_utc="2026-08-10T08:00:00Z")
        assign_booking(b1["id"], photog["id"])  # 60 on 2026-08-10

        # same photographer, next UTC day: the previous day's minutes are irrelevant
        b_next = create_ready_booking(agent, market["id"], order_ref="ORD-C5",
                                      property_address="5 Cap St", photo_count=20,
                                      scheduled_start_utc="2026-08-11T08:00:00Z")
        assigned = validate_success(api_client.assign_booking(
            b_next["id"], photog["id"], make_coordinator_headers()))
        assert assigned["state"] == "ASSIGNED"
        committed = get_photographer(photog["id"])["committed_minutes_by_day"]
        assert committed["2026-08-10"] == 60
        assert committed["2026-08-11"] == 60


class TestAssignmentEligibility:
    def test_assign_wrong_market_photographer_rejected(self, api):
        """PRD §3.3: "the photographer must be `ACTIVE` and belong to the booking's
        market (otherwise `ERR_PHOTOGRAPHER_NOT_ELIGIBLE`) ..."

        Design: Corner/validations/assign_wrong_market_photographer_rejected
        """
        set_clock()
        den = create_market(market_code="DEN", display_name="Denver",
                            pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        atx = create_market(market_code="ATX", display_name="Austin",
                            pricing_multiplier_bps=12500, standard_turnaround_hours=48)
        photog = create_photographer(atx["id"], full_name="Austin Al", email="al@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(den["id"])
        booking = create_ready_booking(agent, den["id"], order_ref="ORD-XM",
                                       property_address="3 Cross St",
                                       scheduled_start_utc="2026-08-10T14:00:00Z")

        resp = api_client.assign_booking(booking["id"], photog["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_NOT_ELIGIBLE)
        after = get_booking(booking["id"])
        assert after["state"] == "READY"
        assert after["assigned_photographer_id"] is None

    def test_equipment_mismatch_rejected(self, api):
        """PRD §3.3: "the photographer's `equipment_packages` must contain the
        booking's `equipment_package` (otherwise `ERR_EQUIPMENT_MISMATCH`) ..."

        Design: Corner/validations/equipment_mismatch_rejected
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Std Steve", email="steve@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_ready_booking(agent, market["id"], order_ref="ORD-EQ",
                                       property_address="5 Luxury Ln",
                                       equipment_package="LUXURY", photo_count=40,
                                       scheduled_start_utc="2026-08-10T14:00:00Z")

        resp = api_client.assign_booking(booking["id"], photog["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_MISMATCH)

    def test_safety_error_dominates_constraint_error_on_assign(self, api):
        """PRD §2.8: "when a single request could fail several checks, the server
        evaluates them in a fixed precedence order and reports only the first applicable
        failure; an earlier tier masks every later tier." Tier 6 is "6.
        **Airspace-safety rules** — drone certification, authorization attempt caps,
        lapsed authorization windows, and the unbranded-tier rule, typified by
        `ERR_DRONE_CERT_REQUIRED` (422)." and tier 7 is "7. **Resource constraints** —
        overlap, day-capacity, equipment-match, duplicate-drone, reschedule-cap,
        revision-cap, and readiness-completeness checks, typified by
        `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` (409)."

        An assign where the photographer BOTH lacks drone certification AND is
        double-booked must report the safety error.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_assign
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=45)
        p_uncert = create_photographer(market["id"], full_name="Uncert Uma", email="uma@x.com",
                                       equipment_packages=["STANDARD"], drone_certified=False)
        agent = create_agent(market["id"])

        # B1 occupies the uncertified photographer 14:00-15:00
        b1 = create_ready_booking(agent, market["id"], order_ref="ORD-OCC",
                                  property_address="2 Busy St", photo_count=20,
                                  scheduled_start_utc="2026-08-10T14:00:00Z")
        assign_booking(b1["id"], p_uncert["id"])

        # B2 carries an ACTIVE drone add-on and overlaps B1's widened window
        b2 = create_booking(agent, market["id"], order_ref="ORD-DRN",
                            property_address="4 Hill", photo_count=20,
                            scheduled_start_utc="2026-08-10T14:30:00Z")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.create_addon(b2["id"], "DRONE_STILLS", headers))
        submit_and_prepare(b2, agent)

        resp = api_client.assign_booking(b2["id"], p_uncert["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_DRONE_CERT_REQUIRED)
        after = get_booking(b2["id"])
        assert after["state"] == "READY"
        assert after["assigned_photographer_id"] is None


class TestCommittedMinutesInvariant:
    def test_committed_minutes_conserved_across_assign_unassign(self, api):
        """PRD §3.3: "A successful assignment sets the booking's
        `assigned_photographer_id`, adds the shoot's minutes to the photographer's
        `committed_minutes_by_day` entry for the scheduled day ..." and "Unassignment
        releases the photographer: the committed minutes for the day are decremented by
        the released window, `assigned_photographer_id` returns to null ... the booking
        falls back to `READY` ..."

        Design: Difficulty/compensating_invariant/photographer_committed_minutes_conserved_across_assign_unassign
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=0)
        photog = create_photographer(market["id"], full_name="Cap Carla", email="carla@x.com",
                                     equipment_packages=["STANDARD"], max_shoot_minutes_per_day=120)
        agent = create_agent(market["id"])

        b1 = create_ready_booking(agent, market["id"], order_ref="ORD-INV1",
                                  property_address="1 Inv St", photo_count=20,
                                  scheduled_start_utc="2026-08-10T08:00:00Z")
        assign_booking(b1["id"], photog["id"])
        b2 = create_ready_booking(agent, market["id"], order_ref="ORD-INV2",
                                  property_address="2 Inv St", photo_count=20,
                                  scheduled_start_utc="2026-08-10T10:00:00Z")
        assign_booking(b2["id"], photog["id"])
        assert get_photographer(photog["id"])["committed_minutes_by_day"]["2026-08-10"] == 120

        # compensating unassign: minutes return exactly to the prior value — no drift
        validate_success(api_client.unassign_booking(b2["id"], make_coordinator_headers()))
        assert get_photographer(photog["id"])["committed_minutes_by_day"]["2026-08-10"] == 60
        after = get_booking(b2["id"])
        assert after["state"] == "READY"
        assert after["assigned_photographer_id"] is None

        # capacity behaves as if the assign/unassign pair never happened
        validate_success(api_client.assign_booking(b2["id"], photog["id"],
                                                   make_coordinator_headers()))
        assert get_photographer(photog["id"])["committed_minutes_by_day"]["2026-08-10"] == 120

    def test_committed_minutes_restored_after_confirmed_cancel(self, api):
        """PRD §3.9: "Every cancellation runs the same release cascade — all
        non-terminal add-ons move to `CANCELLED`, all airspace authorizations move to
        `CANCELLED`, the assigned photographer's committed minutes are released and
        `assigned_photographer_id` returns to null when an assignment existed ..."

        Design: Difficulty/compensating_invariant/photographer_committed_minutes_conserved_across_assign_unassign
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               travel_buffer_minutes=0)
        photog = create_photographer(market["id"], full_name="Cap Carla", email="carla@x.com",
                                     equipment_packages=["STANDARD"], max_shoot_minutes_per_day=120)
        agent = create_agent(market["id"])
        booking = create_ready_booking(agent, market["id"], order_ref="ORD-INV3",
                                       property_address="3 Inv St", photo_count=20,
                                       scheduled_start_utc="2026-08-10T08:00:00Z")
        assign_booking(booking["id"], photog["id"])
        confirm_booking(booking["id"])
        assert get_photographer(photog["id"])["committed_minutes_by_day"]["2026-08-10"] == 60

        validate_success(api_client.cancel_booking(booking["id"],
                                                   make_client_agent_headers(agent["id"])))
        # released exactly: the day's committed minutes return to zero — no drift
        assert get_photographer(photog["id"])["committed_minutes_by_day"].get("2026-08-10", 0) == 0
        after = get_booking(booking["id"])
        assert after["state"] == "CANCELLED_BY_CLIENT"
        assert after["assigned_photographer_id"] is None
