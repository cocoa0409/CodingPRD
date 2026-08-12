"""Show cancellation cascades and compensating invariants (PRD §3.4, §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_show, create_show_with_accepted_hold,
    create_confirmed_show, confirm_show, get_tour, get_venue, get_show,
    get_hold, get_packet, submit_and_approve_section,
    assert_show, ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]


def _stage_confirmed_show(api, capacity=9000, price=10000, tour_name="TCas",
                          market_code="DEN", venue_name="Red Rocks",
                          show_date="2026-08-15", guarantee=2000000):
    staged = create_staged_tour(
        start_clock="2026-06-01T00:00:00Z",
        tour_overrides={"tour_name": tour_name},
        market_overrides={"market_code": market_code, "metro_name": market_code,
                          "radius_miles": 60},
        venue_overrides={"venue_name": venue_name, "capacity": capacity,
                         "available_dates": [show_date]})
    tid = staged["tour"]["id"]
    show, hold = create_confirmed_show(
        tid, staged["market"]["id"], staged["venue"]["id"],
        show_date=show_date, on_sale_at="2026-07-01T00:00:00Z",
        avg_ticket_price_cents=price,
        hold_overrides={"guarantee_cents": guarantee, "versus_pct": 80})
    return staged, tid, show, hold


class TestShowCancelDepth3Cascade:
    def test_cancel_withdraws_hold_releases_date_and_removes_projection(self, api):
        """PRD §3.4: "cancelling a confirmed show releases `show_date` from the
        venue's `booked_dates`, withdraws the attached promoter hold (an
        `ACCEPTED` hold becomes `WITHDRAWN`), resets every advance-packet
        section back to `PENDING`, and recalculates the tour's posture."
        PRD §3.8: "exactly those shows whose status is `CONFIRMED`,
        `ADVANCED`, `PERFORMED`, or `SETTLED` — shows still in hold states or
        cancelled never enter the set."

        Design: Difficulty/transitive_cascade/show_cancel_depth3_cascade
        """
        staged, tid, show, hold = _stage_confirmed_show(api)
        vid = staged["venue"]["id"]

        venue_mid = get_venue(tid, vid)
        assert "2026-08-15" in venue_mid["booked_dates"]
        tour_mid = get_tour(tid)
        # Pre-on-sale variant: round(9000 * 10000 * 0.65) = 58500000
        assert tour_mid["projected_gross_cents"] == 58500000

        cancelled = validate_success(api.cancel_show(tid, show["id"], TM), 200)
        assert_show(cancelled)
        assert cancelled["status"] == "CANCELLED"

        # Link 1 -> 2: cancel cascades to the attached promoter hold
        hold_after = get_hold(tid, show["id"], hold["id"])
        assert hold_after["status"] == "WITHDRAWN"

        # Link 2 -> 3: the venue date is released
        venue_after = get_venue(tid, vid)
        assert "2026-08-15" not in venue_after["booked_dates"]
        assert venue_after["booked_dates"] == []

        # Link 3 -> 4: the cancelled show exits the forward projection set
        tour_after = get_tour(tid)
        assert tour_after["projected_gross_cents"] == 0
        assert tour_after["projected_cost_cents"] == 0

    def test_cancel_resets_advance_packet_sections_to_pending(self, api):
        """PRD §3.4: "cancelling a confirmed show releases `show_date` from the
        venue's `booked_dates`, withdraws the attached promoter hold (an
        `ACCEPTED` hold becomes `WITHDRAWN`), resets every advance-packet
        section back to `PENDING`, and recalculates the tour's posture."

        Design: Difficulty/transitive_cascade/show_cancel_depth3_cascade
        """
        staged, tid, show, hold = _stage_confirmed_show(
            api, capacity=1000, price=10000, tour_name="TCas2",
            market_code="BNA", venue_name="Ryman", show_date="2026-08-15")
        # Move one section to APPROVED before cancelling
        packet = submit_and_approve_section(tid, show["id"], "tech_rider")
        assert packet["tech_rider_status"] == "APPROVED"

        validate_success(api.cancel_show(tid, show["id"], TM), 200)

        packet_after = get_packet(tid, show["id"])
        assert packet_after["tech_rider_status"] == "PENDING"
        assert packet_after["hospitality_status"] == "PENDING"
        assert packet_after["immigration_status"] == "PENDING"


class TestVenueBookedDatesConservedAcrossConfirmCancel:
    def test_confirm_then_cancel_is_identity_on_booked_dates(self, api):
        """PRD §3.4: "A successful confirmation moves the show to `CONFIRMED`,
        adds `show_date` to the venue's `booked_dates`", and "cancelling a
        confirmed show releases `show_date` from the venue's `booked_dates`".

        Design: Difficulty/compensating_invariant/venue_booked_dates_conserved_across_confirm_cancel
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TInv1"},
            market_overrides={"market_code": "STL", "metro_name": "St Louis"},
            venue_overrides={"venue_name": "Pageant", "capacity": 1300,
                             "available_dates": ["2026-08-10"]})
        tid = staged["tour"]["id"]
        vid = staged["venue"]["id"]
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], vid, show_date="2026-08-10",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=6000,
            hold_overrides={"guarantee_cents": 800000, "versus_pct": 75})

        booked_pre = get_venue(tid, vid)["booked_dates"]
        assert booked_pre == [], "venue calendar empty before confirm"

        confirm_show(tid, show["id"])
        booked_mid = get_venue(tid, vid)["booked_dates"]
        assert booked_mid == ["2026-08-10"], "confirm adds the show date"

        validate_success(api.cancel_show(tid, show["id"], TM), 200)
        booked_post = get_venue(tid, vid)["booked_dates"]
        assert booked_post == booked_pre, (
            "confirm+cancel conserves venue booked_dates membership exactly")

    def test_cancel_releases_only_the_cancelled_shows_date(self, api):
        """PRD §3.4: "cancelling a confirmed show releases `show_date` from the
        venue's `booked_dates`" — the compensating release is scoped to the
        cancelled show's own date.

        Design: Difficulty/compensating_invariant/venue_booked_dates_conserved_across_confirm_cancel
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TInv1b"},
            market_overrides={"market_code": "STL", "metro_name": "St Louis"},
            venue_overrides={"venue_name": "Pageant", "capacity": 1300,
                             "available_dates": ["2026-08-10", "2026-08-11"]})
        tid = staged["tour"]["id"]
        vid = staged["venue"]["id"]
        mid = staged["market"]["id"]
        s1, _ = create_confirmed_show(
            tid, mid, vid, show_date="2026-08-10",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=6000)
        s2, _ = create_confirmed_show(
            tid, mid, vid, show_date="2026-08-11",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=6000)
        assert sorted(get_venue(tid, vid)["booked_dates"]) == [
            "2026-08-10", "2026-08-11"]

        validate_success(api.cancel_show(tid, s1["id"], TM), 200)
        booked = get_venue(tid, vid)["booked_dates"]
        assert booked == ["2026-08-11"], (
            "the other confirmed show's date remains booked")


class TestTourProjectedGrossConservedAcrossConfirmCancel:
    def test_confirm_then_cancel_is_identity_on_projected_gross(self, api):
        """PRD §3.8: "exactly those shows whose status is `CONFIRMED`,
        `ADVANCED`, `PERFORMED`, or `SETTLED` — shows still in hold states or
        cancelled never enter the set." And: "While the logical clock is still
        earlier than the show's `on_sale_at`, the pre-on-sale variant projects
        gross as the frozen `capacity` multiplied by `avg_ticket_price_cents`
        and then by a sellout factor of 0.65".

        Design: Difficulty/compensating_invariant/tour_projected_gross_conserved_across_confirm_cancel
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TInv2"},
            market_overrides={"market_code": "KC", "metro_name": "Kansas City"},
            venue_overrides={"venue_name": "T-Mobile", "capacity": 1000,
                             "available_dates": ["2026-08-12"]})
        tid = staged["tour"]["id"]
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-12", on_sale_at="2026-07-15T00:00:00Z",
            avg_ticket_price_cents=10000,
            hold_overrides={"guarantee_cents": 1000000, "versus_pct": 80})

        gross_pre = get_tour(tid)["projected_gross_cents"]
        assert gross_pre == 0, "held shows are not in the projection set"

        confirm_show(tid, show["id"])
        gross_mid = get_tour(tid)["projected_gross_cents"]
        assert gross_mid == 6500000, (
            "pre-on-sale projection: round(1000 * 10000 * 0.65) = 6500000")

        validate_success(api.cancel_show(tid, show["id"], TM), 200)
        gross_post = get_tour(tid)["projected_gross_cents"]
        assert gross_post == gross_pre, (
            "confirm+cancel conserves projected_gross_cents exactly (zero drift)")

    def test_projected_cost_also_conserved_and_pnl_read_matches(self, api):
        """PRD §3.8: "While the logical clock is still earlier than the show's
        `on_sale_at`, the pre-on-sale variant projects gross as the frozen
        `capacity` multiplied by `avg_ticket_price_cents` and then by a sellout
        factor of 0.65 — the house is assumed sixty-five percent sold — and
        projects cost as the sum of `estimated_cents` over the show's committed
        budget lines plus 350 cents of per-ticket variable cost for every seat
        of capacity." And: "A computed tour P&L read returns all four totals —
        projected gross, projected cost, settled gross, settled cost — side by
        side."

        Design: Difficulty/compensating_invariant/tour_projected_gross_conserved_across_confirm_cancel
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TInv2b"},
            market_overrides={"market_code": "KC", "metro_name": "Kansas City"},
            venue_overrides={"venue_name": "T-Mobile", "capacity": 1000,
                             "available_dates": ["2026-08-12"]})
        tid = staged["tour"]["id"]
        show, _ = create_confirmed_show(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-12", on_sale_at="2026-07-15T00:00:00Z",
            avg_ticket_price_cents=10000,
            hold_overrides={"guarantee_cents": 1000000, "versus_pct": 80})

        pnl_mid = validate_success(api.get_tour_pnl(tid, TM), 200)
        assert pnl_mid["projected_gross_cents"] == 6500000
        # No budget lines: cost = 1000 seats * 350 cents of variable cost
        assert pnl_mid["projected_cost_cents"] == 350000
        assert pnl_mid["settled_gross_cents"] == 0
        assert pnl_mid["settled_cost_cents"] == 0

        validate_success(api.cancel_show(tid, show["id"], TM), 200)
        pnl_post = validate_success(api.get_tour_pnl(tid, TM), 200)
        assert pnl_post["projected_gross_cents"] == 0
        assert pnl_post["projected_cost_cents"] == 0


class TestCancelFromTerminalState:
    def test_second_cancel_on_cancelled_show_rejected(self, api):
        """PRD §3.4: "Cancellation remains available from `HOLD_REQUESTED`,
        `HOLD_PLACED`, or `CONFIRMED`" and "`CANCELLED` is terminal."
        PRD §2.10: "Sixth, whether the target entity is in a permissible state
        for the requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/cancel_show_from_settled_returns_invalid_state
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"capacity": 100, "available_dates": ["2026-08-01"]})
        tid = staged["tour"]["id"]
        show = create_show(tid, staged["market"]["id"], staged["venue"]["id"],
                           show_date="2026-08-01",
                           on_sale_at="2026-07-01T00:00:00Z",
                           avg_ticket_price_cents=5000)
        first = validate_success(api.cancel_show(tid, show["id"], TM), 200)
        assert first["status"] == "CANCELLED"

        res = api.cancel_show(tid, show["id"], TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cascade_down_cancel_releases_venue_date(self, api):
        """PRD §3.4: "cancelling a confirmed show releases `show_date` from the
        venue's `booked_dates`, withdraws the attached promoter hold (an
        `ACCEPTED` hold becomes `WITHDRAWN`), resets every advance-packet
        section back to `PENDING`, and recalculates the tour's posture."

        Design: Corner/state_machines/cascade_down_cancel_releases_venue_date
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"capacity": 100, "available_dates": ["2026-08-01"]})
        tid = staged["tour"]["id"]
        vid = staged["venue"]["id"]
        show, _ = create_confirmed_show(
            tid, staged["market"]["id"], vid, show_date="2026-08-01",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})
        assert get_venue(tid, vid)["booked_dates"] == ["2026-08-01"]

        validate_success(api.cancel_show(tid, show["id"], TM), 200)
        assert get_venue(tid, vid)["booked_dates"] == []
