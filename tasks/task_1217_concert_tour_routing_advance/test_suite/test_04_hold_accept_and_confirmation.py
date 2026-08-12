"""Hold acceptance cascade, venue calendar point-membership, the on-sale lead
boundary, and confirm-time read consistency (PRD §3.3, §3.4).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_show, place_hold, accept_hold, get_show,
    get_tour, get_venue, get_hold, confirm_show, set_clock,
    create_show_with_accepted_hold, confirm_show_payload,
    assert_show, assert_promoter_hold, ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]
PROMOTER = TEST_USERS["promoter_headers"]


class TestHoldAcceptCascade:
    def _stage_show_with_pending_hold(self, api):
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "THA"},
            market_overrides={"market_code": "MIA", "metro_name": "Miami",
                              "radius_miles": 50},
            venue_overrides={"venue_name": "Fillmore", "capacity": 1500,
                             "available_dates": ["2026-08-20"]})
        tid = staged["tour"]["id"]
        show = create_show(tid, staged["market"]["id"], staged["venue"]["id"],
                           show_date="2026-08-20", on_sale_at="2026-07-01T00:00:00Z",
                           avg_ticket_price_cents=9000)
        hold = place_hold(tid, show["id"], guarantee_cents=1000000, versus_pct=75)
        return staged, show, hold

    def test_first_acceptance_moves_show_to_hold_placed(self, api):
        """PRD §3.3: "The first acceptance on a show moves it from
        `HOLD_REQUESTED` to `HOLD_PLACED`, freezes the show's `capacity` as a
        snapshot of the venue's `capacity` at that moment, recomputes
        `gross_potential_cents` as that frozen capacity multiplied by
        `avg_ticket_price_cents`, and updates the venue's `booked_dates`
        calendar to reflect the held date."

        Design: Difficulty/transitive_cascade/hold_accept_depth2_cascade
        """
        staged, show, hold = self._stage_show_with_pending_hold(api)
        assert show["status"] == "HOLD_REQUESTED"

        accepted = accept_hold(staged["tour"]["id"], show["id"], hold["id"])
        assert_promoter_hold(accepted)
        assert accepted["status"] == "ACCEPTED"

        after = get_show(staged["tour"]["id"], show["id"])
        assert_show(after)
        assert after["status"] == "HOLD_PLACED", (
            "link 1 of the cascade: accept moves the show HOLD_REQUESTED -> HOLD_PLACED")
        assert after["capacity"] == 1500, (
            "link 2 of the cascade: capacity snapshot of the venue at acceptance")

    def test_first_acceptance_recomputes_gross_potential(self, api):
        """PRD §3.3: "The first acceptance on a show moves it from
        `HOLD_REQUESTED` to `HOLD_PLACED`, freezes the show's `capacity` as a
        snapshot of the venue's `capacity` at that moment, recomputes
        `gross_potential_cents` as that frozen capacity multiplied by
        `avg_ticket_price_cents`, and updates the venue's `booked_dates`
        calendar to reflect the held date."

        Design: Difficulty/transitive_cascade/hold_accept_depth2_cascade
        """
        staged, show, hold = self._stage_show_with_pending_hold(api)
        accept_hold(staged["tour"]["id"], show["id"], hold["id"])

        after = get_show(staged["tour"]["id"], show["id"])
        assert after["gross_potential_cents"] == 1500 * 9000, (
            "link 3 of the cascade: gross_potential = frozen capacity * avg price "
            "= 1500 * 9000 = 13500000")

        hold_after = get_hold(staged["tour"]["id"], show["id"], hold["id"])
        assert hold_after["status"] == "ACCEPTED"


class TestVenueBookedDatesPointMembership:
    def _stage_two_held_shows_same_venue(self, api):
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TOv1"},
            market_overrides={"market_code": "MIN", "metro_name": "Minneapolis",
                              "radius_miles": 30, "exclusivity_window_days": 7},
            venue_overrides={"venue_name": "FirstAve", "capacity": 1500,
                             "available_dates": ["2026-08-01", "2026-08-02"]})
        tid = staged["tour"]["id"]
        mid = staged["market"]["id"]
        vid = staged["venue"]["id"]
        s1, _ = create_show_with_accepted_hold(
            tid, mid, vid, show_date="2026-08-01",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 500000, "versus_pct": 70})
        confirm_show(tid, s1["id"])
        return staged, tid, mid, vid

    def test_same_date_second_show_rejected(self, api):
        """PRD §3.4: "The venue must still be able to host the date —
        `show_date` present in `available_dates` and absent from `booked_dates`
        — or the confirm fails with `ERR_VENUE_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/venue_booked_dates_point_membership
        """
        _, tid, mid, vid = self._stage_two_held_shows_same_venue(api)
        # Second show on the SAME date: point collision in booked_dates
        s2, _ = create_show_with_accepted_hold(
            tid, mid, vid, show_date="2026-08-01",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 500000, "versus_pct": 70})
        tour = get_tour(tid)
        res = api.confirm_show(tid, s2["id"],
                               confirm_show_payload(tour["version"]), TM)
        validate_error(res, ApiErrorId.ERR_VENUE_UNAVAILABLE.value)

    def test_adjacent_date_show_confirms(self, api):
        """PRD §3.4: "The venue must still be able to host the date —
        `show_date` present in `available_dates` and absent from `booked_dates`
        — or the confirm fails with `ERR_VENUE_UNAVAILABLE`." Venue overlap is
        exact-date membership: the next calendar day is not booked.

        Design: Difficulty/resource_temporal_overlap/venue_booked_dates_point_membership
        """
        _, tid, mid, vid = self._stage_two_held_shows_same_venue(api)
        # Adjacent calendar day: no buffer, must succeed
        s3, _ = create_show_with_accepted_hold(
            tid, mid, vid, show_date="2026-08-02",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 500000, "versus_pct": 70})
        confirmed = confirm_show(tid, s3["id"])
        assert confirmed["status"] == "CONFIRMED"
        venue = get_venue(tid, vid)
        assert "2026-08-01" in venue["booked_dates"]
        assert "2026-08-02" in venue["booked_dates"]


class TestOnSaleLeadBoundary:
    def test_exactly_14_days_lead_allowed(self, api):
        """PRD §3.3: "the on-sale moment must lead the performance by at least
        14 days: measured from `on_sale_at` to the show date as a UTC midnight,
        the gap must be no less than fourteen days, with a gap of exactly
        fourteen days allowed."

        Design: Difficulty/boundary_precision_check/on_sale_lead_exactly_14_days_passes
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"available_dates": ["2026-08-01"]})
        tid = staged["tour"]["id"]
        # 2026-07-18T00:00:00Z -> 2026-08-01 (UTC midnight) is exactly 14 days
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-01", on_sale_at="2026-07-18T00:00:00Z",
            avg_ticket_price_cents=8000)
        confirmed = confirm_show(tid, show["id"])
        assert confirmed["status"] == "CONFIRMED", (
            "a gap of exactly fourteen days is allowed (>=, not >)")

    def test_13_days_lead_rejected_at_create(self, api):
        """PRD §3.3: "the on-sale moment must lead the performance by at least
        14 days: measured from `on_sale_at` to the show date as a UTC midnight,
        the gap must be no less than fourteen days, with a gap of exactly
        fourteen days allowed. A date outside the window or not hostable by the
        venue is rejected with `ERR_VENUE_UNAVAILABLE`; insufficient on-sale
        lead is rejected with `ERR_ON_SALE_LEAD_VIOLATED`."

        Design: Difficulty/boundary_precision_check/on_sale_lead_exactly_14_days_passes
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"available_dates": ["2026-08-02"]})
        tid = staged["tour"]["id"]
        # 2026-07-20T00:00:00Z -> 2026-08-02 is 13 days: one below the boundary
        res = api.create_show(
            tid,
            {"market_id": staged["market"]["id"], "venue_id": staged["venue"]["id"],
             "show_date": "2026-08-02", "on_sale_at": "2026-07-20T00:00:00Z",
             "avg_ticket_price_cents": 8000},
            TM)
        validate_error(res, ApiErrorId.ERR_ON_SALE_LEAD_VIOLATED.value)

    def test_confirm_rejected_when_clock_plus_14_days_passes_show_date(self, api):
        """PRD §3.4: "The on-sale lead must still be satisfiable from the
        present: the current logical clock plus fourteen days must not fall
        after the show date, or the confirm fails with
        `ERR_ON_SALE_LEAD_VIOLATED`."

        Design: Difficulty/boundary_precision_check/on_sale_lead_exactly_14_days_passes
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"available_dates": ["2026-08-15"]})
        tid = staged["tour"]["id"]
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-15", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=8000)
        # Advance the clock to 2026-08-10: 2026-08-10 + 14 days = 2026-08-24,
        # which falls after the 2026-08-15 show date.
        set_clock("2026-08-10T00:00:00Z")
        tour = get_tour(tid)
        res = api.confirm_show(tid, show["id"],
                               confirm_show_payload(tour["version"]), TM)
        validate_error(res, ApiErrorId.ERR_ON_SALE_LEAD_VIOLATED.value)


class TestImmediateConsistencyOnConfirm:
    def test_confirm_response_and_reads_reflect_effects_immediately(self, api):
        """PRD §3.4: "A successful confirmation moves the show to `CONFIRMED`,
        adds `show_date` to the venue's `booked_dates`, increments the tour's
        `version` by one, and recomputes the tour's projected totals with the
        show now inside the forward projection set."

        Design: Corner/consistency_model/immediate_consistency_on_confirm
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"capacity": 100, "available_dates": ["2026-08-01"]})
        tid = staged["tour"]["id"]
        vid = staged["venue"]["id"]
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], vid,
            show_date="2026-08-01", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=10000,
            hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})

        tour_before = get_tour(tid)
        res = api.confirm_show(tid, show["id"],
                               confirm_show_payload(tour_before["version"]), TM)
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED", "status visible in the same response"

        venue = get_venue(tid, vid)
        assert "2026-08-01" in venue["booked_dates"], (
            "venue calendar reflects the confirmation on the immediately following read")
        tour_after = get_tour(tid)
        assert tour_after["version"] == tour_before["version"] + 1
        assert tour_after["projected_gross_cents"] == 650000, (
            "pre-on-sale projection 100 * 10000 * 0.65 = 650000 visible immediately")
