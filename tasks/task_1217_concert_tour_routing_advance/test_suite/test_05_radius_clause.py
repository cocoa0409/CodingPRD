"""Radius-clause sweep semantics at confirm: half-open window, severity
grading, and the temporal-vs-safety ordering (PRD §2.10, §3.4).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_tour, create_market, create_venue, create_show_with_accepted_hold,
    confirm_show, confirm_show_payload, get_tour, set_clock,
    assert_compliance_hold, ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]


def _stage_two_market_tour(api, window1=30, window2=30,
                           v2_dates=("2026-08-31", "2026-09-01"),
                           window_end="2026-10-15"):
    """Tour with BOS (rank 1) and PROV (rank 2) markets, each with a venue,
    moved to ROUTING. Both markets default to radius 60 / window 30."""
    tour = create_tour(start_clock="2026-06-01T00:00:00Z",
                       tour_name="TOv2", window_start_date="2026-07-01",
                       window_end_date=window_end)
    m1 = create_market(tour["id"], market_code="BOS", metro_name="Boston",
                       radius_miles=60, exclusivity_window_days=window1,
                       territory_rank=1)
    m2 = create_market(tour["id"], market_code="PROV", metro_name="Providence",
                       radius_miles=60, exclusivity_window_days=window2,
                       territory_rank=2)
    v1 = create_venue(tour["id"], m1["id"], venue_name="TDG", capacity=1800,
                      available_dates=["2026-08-01"])
    v2 = create_venue(tour["id"], m2["id"], venue_name="PPAC", capacity=1200,
                      available_dates=list(v2_dates))
    validate_success(api.start_routing(tour["id"], TM), 200)
    return tour, m1, m2, v1, v2


def _confirm_first_show(api, tour_id, m1, v1):
    s1, _ = create_show_with_accepted_hold(
        tour_id, m1["id"], v1["id"], show_date="2026-08-01",
        on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=7000,
        hold_overrides={"guarantee_cents": 800000, "versus_pct": 75})
    confirmed = confirm_show(tour_id, s1["id"])
    assert confirmed["status"] == "CONFIRMED"
    return confirmed


class TestRadiusClauseHalfOpenWindow:
    def test_gap_exactly_at_window_is_standard_conflict_not_blocking(self, api):
        """PRD §3.4: "The date boundary is half-open in the strict sense: a gap
        exactly equal to the smaller window **is** a conflict, while a gap one
        day beyond it is not. When the conflicting date sits exactly at that
        window edge, the conflict is graded `STANDARD`; when it falls strictly
        inside the window, the conflict is `CRITICAL`. A `CRITICAL` conflict
        rejects the confirmation outright with `ERR_RADIUS_CONFLICT`. A
        `STANDARD` conflict does not block the confirmation — instead the
        system opens a ComplianceHold of `hold_kind` `RADIUS_CONFLICT` and
        severity `STANDARD` scoped to the new show, which immediately drops the
        tour's posture to `RESTRICTED` and thereby blocks any further
        confirmations until it is resolved."

        Design: Difficulty/resource_temporal_overlap/radius_clause_half_open_window
        """
        tour, m1, m2, v1, v2 = _stage_two_market_tour(api)
        tid = tour["id"]
        _confirm_first_show(api, tid, m1, v1)

        # Second show at exactly +30 days (2026-08-31): the window edge.
        s2, _ = create_show_with_accepted_hold(
            tid, m2["id"], v2["id"], show_date="2026-08-31",
            on_sale_at="2026-07-15T00:00:00Z", avg_ticket_price_cents=7000,
            hold_overrides={"guarantee_cents": 800000, "versus_pct": 75})
        confirmed2 = confirm_show(tid, s2["id"])
        assert confirmed2["status"] == "CONFIRMED", (
            "a STANDARD edge conflict does not block the confirmation")

        holds, meta = validate_paginated(
            api.list_compliance_holds(tid, TM, params={"status": "ACTIVE"}))
        radius_holds = [h for h in holds if h["hold_kind"] == "RADIUS_CONFLICT"]
        assert len(radius_holds) == 1, f"expected one RADIUS_CONFLICT hold, got {radius_holds}"
        assert_compliance_hold(radius_holds[0])
        assert radius_holds[0]["severity"] == "STANDARD"
        assert radius_holds[0]["related_show_id"] == s2["id"], (
            "the standard hold is scoped to the new show")

        tour_after = get_tour(tid)
        assert tour_after["posture"] == "RESTRICTED", (
            "the standard hold immediately drops the tour posture to RESTRICTED")

    def test_gap_one_day_beyond_window_is_no_conflict(self, api):
        """PRD §3.4: "The date boundary is half-open in the strict sense: a gap
        exactly equal to the smaller window **is** a conflict, while a gap one
        day beyond it is not."

        Design: Difficulty/resource_temporal_overlap/radius_clause_half_open_window
        """
        tour, m1, m2, v1, v2 = _stage_two_market_tour(api)
        tid = tour["id"]
        _confirm_first_show(api, tid, m1, v1)

        # Second show at +31 days (2026-09-01): one day beyond the window.
        s3, _ = create_show_with_accepted_hold(
            tid, m2["id"], v2["id"], show_date="2026-09-01",
            on_sale_at="2026-07-15T00:00:00Z", avg_ticket_price_cents=7000,
            hold_overrides={"guarantee_cents": 800000, "versus_pct": 75})
        confirmed3 = confirm_show(tid, s3["id"])
        assert confirmed3["status"] == "CONFIRMED"

        holds, _ = validate_paginated(api.list_compliance_holds(tid, TM))
        assert [h for h in holds if h["hold_kind"] == "RADIUS_CONFLICT"] == [], (
            "no radius hold is opened one day beyond the window")
        assert get_tour(tid)["posture"] == "OPEN"

    def test_gap_strictly_inside_window_rejected_critical(self, api):
        """PRD §3.4: "when it falls strictly inside the window, the conflict is
        `CRITICAL`. A `CRITICAL` conflict rejects the confirmation outright
        with `ERR_RADIUS_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/radius_clause_half_open_window
        """
        tour, m1, m2, v1, v2 = _stage_two_market_tour(
            api, v2_dates=["2026-08-16"], window_end="2026-10-15")
        tid = tour["id"]
        _confirm_first_show(api, tid, m1, v1)

        # Second show at +15 days: strictly inside the 30-day window.
        s2, _ = create_show_with_accepted_hold(
            tid, m2["id"], v2["id"], show_date="2026-08-16",
            on_sale_at="2026-07-15T00:00:00Z", avg_ticket_price_cents=7000,
            hold_overrides={"guarantee_cents": 800000, "versus_pct": 75})
        tour_now = get_tour(tid)
        res = api.confirm_show(tid, s2["id"],
                               confirm_show_payload(tour_now["version"]), TM)
        validate_error(res, ApiErrorId.ERR_RADIUS_CONFLICT.value)


class TestTemporalBeatsSafetyOnConfirm:
    def test_on_sale_lead_reported_before_radius_sweep(self, api):
        """PRD §2.10: "Only then are the domain rules evaluated: venue
        availability, on-sale lead time, the radius-clause sweep, crew-rest
        enforcement, hold counter limits and expiry, advance-packet
        completeness, settlement variance, the budget cap, segregation of
        duties, and uniqueness constraints." The on-sale lead check is a
        business-temporal rule evaluated ahead of the radius-clause sweep, a
        business-safety rule, so a confirm violating both surfaces
        `ERR_ON_SALE_LEAD_VIOLATED`.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_confirm
        """
        tour, m1, m2, v1, v2 = _stage_two_market_tour(api, v2_dates=["2026-08-15"])
        tid = tour["id"]
        _confirm_first_show(api, tid, m1, v1)

        # Candidate show at +14 days: strictly inside the 30-day window, so a
        # CRITICAL radius conflict exists against the confirmed first show.
        s2, _ = create_show_with_accepted_hold(
            tid, m2["id"], v2["id"], show_date="2026-08-15",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=7000,
            hold_overrides={"guarantee_cents": 800000, "versus_pct": 75})

        # Advance the clock so the on-sale lead is ALSO violated at confirm:
        # 2026-08-10 + 14 days = 2026-08-24 falls after the 2026-08-15 date
        # (PRD §3.4 confirm-time lead gate).
        set_clock("2026-08-10T00:00:00Z")
        tour_now = get_tour(tid)
        res = api.confirm_show(tid, s2["id"],
                               confirm_show_payload(tour_now["version"]), TM)
        validate_error(res, ApiErrorId.ERR_ON_SALE_LEAD_VIOLATED.value)

    def test_radius_conflict_reported_when_only_safety_fails(self, api):
        """PRD §3.4: "A `CRITICAL` conflict rejects the confirmation outright
        with `ERR_RADIUS_CONFLICT`." With venue availability and on-sale lead
        satisfied, the radius-clause sweep is the rule that fires.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_confirm
        """
        tour, m1, m2, v1, v2 = _stage_two_market_tour(api, v2_dates=["2026-08-15"])
        tid = tour["id"]
        _confirm_first_show(api, tid, m1, v1)

        s2, _ = create_show_with_accepted_hold(
            tid, m2["id"], v2["id"], show_date="2026-08-15",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=7000,
            hold_overrides={"guarantee_cents": 800000, "versus_pct": 75})
        # Clock stays at 2026-06-01: lead (June 15 <= Aug 15) and venue fine.
        tour_now = get_tour(tid)
        res = api.confirm_show(tid, s2["id"],
                               confirm_show_payload(tour_now["version"]), TM)
        validate_error(res, ApiErrorId.ERR_RADIUS_CONFLICT.value)
