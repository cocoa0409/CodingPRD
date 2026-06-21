"""Tour scheduling: confirmation overlap rules (space-buffered and broker-unbuffered),
clock gates, hold release, and the tour-vs-space cross-entity dependency.

Covers Difficulty rules non_linear_state_machine (tour branch), resource_temporal_overlap
(both instances), boundary_precision_check (buffer edge), and cross_entity_state_dependency
(tour->space), plus Corner state-machine tour instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    make_admin_headers, make_listing_broker_headers, make_tenant_broker_headers,
    setup_two_firms, create_broker, create_property, create_published_space,
    create_requirement, create_tour, confirm_tour,
    setup_confirmed_tour_holding_space, setup_published_space_and_requirement,
)


class TestTourBranch:
    def test_cancel_from_confirmed_releases_held_space(self, api):
        """PRD §3.4: "Whenever a held tour completes, cancels, or is marked no-show, the space reverts
        from `ON_HOLD` to `AVAILABLE`, its `held_by_tour_id` is cleared,
        `holds_space` is set false, and the property's `available_sf` is recomputed."

        Design: Difficulty/non_linear_state_machine/tour_branch_join_divergent_side_effects
        """
        base = setup_confirmed_tour_holding_space(
            window_start="2026-07-01T10:00:00Z", window_end="2026-07-01T11:00:00Z")
        lb_h = make_listing_broker_headers(base["lb"]["id"])
        tb_h = make_tenant_broker_headers(base["tb"]["id"])
        # space is ON_HOLD while confirmed-with-hold
        assert get_success_data(api.get_space(base["space"]["id"], lb_h))["status"] == "ON_HOLD"
        tour = validate_success(api.cancel_tour(base["tour"]["id"], tb_h))
        assert tour["status"] == "CANCELLED"
        assert tour["holds_space"] is False
        space = get_success_data(api.get_space(base["space"]["id"], lb_h))
        assert space["status"] == "AVAILABLE"
        assert space["held_by_tour_id"] is None

    def test_hold_on_confirm_moves_space_to_on_hold(self, api):
        """PRD §3.4: "When a confirmation carries `hold` set to true, it sets `holds_space` true,
        transitions the space from `AVAILABLE` to `ON_HOLD` while recording the
        holding tour's identifier in the space's `held_by_tour_id`, and bubbles the
        requirement from `OPEN` to `TOURING`."

        Design: Difficulty/non_linear_state_machine/tour_branch_join_divergent_side_effects
        """
        base = setup_confirmed_tour_holding_space()
        lb_h = make_listing_broker_headers(base["lb"]["id"])
        space = get_success_data(api.get_space(base["space"]["id"], lb_h))
        assert space["status"] == "ON_HOLD"
        assert space["held_by_tour_id"] == base["tour"]["id"]
        req = get_success_data(api.get_requirement(base["requirement"]["id"], lb_h))
        assert req["status"] == "TOURING"


class TestSpaceOverlap:
    def test_buffered_space_overlap_conflict(self, api):
        """PRD §3.4: "against any other `CONFIRMED` tour on the same space, each existing
        confirmed window is expanded by a thirty-minute turnover buffer on both ends, and
        the candidate window conflicts when its start is earlier than that existing
        window's end plus thirty minutes and its end is later than that existing window's
        start minus thirty minutes ... and a conflict is rejected with
        `ERR_TOUR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/space_buffered_overlap_conflict
        """
        lb, tb1 = setup_two_firms()
        # second tenant broker in tb1's firm so the broker-overlap rule cannot fire instead
        tb2 = create_broker(tb1["brokerage_id"], "TENANT_BROKER", "TB2")
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        space = create_published_space(lb["id"], prop["id"], "71", rentable_sf=2500, asking_rent_psf_yr=50)
        req1 = create_requirement(tb1["id"], "SOMA-SF", "OFFICE", 1000, 5000, 60, "T1")
        req2 = create_requirement(tb2["id"], "SOMA-SF", "OFFICE", 1000, 5000, 60, "T2")
        t1 = create_tour(tb1["id"], req1["id"], space["id"],
                         "2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z")
        confirm_tour(lb["id"], t1["id"], hold=False)
        # candidate 11:15-12:00 vs buffered existing-end 11:30 -> conflict (11:15 < 11:30)
        t2 = create_tour(tb2["id"], req2["id"], space["id"],
                         "2026-10-01T11:15:00Z", "2026-10-01T12:00:00Z")
        validate_error(api.confirm_tour(t2["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_TOUR_WINDOW_CONFLICT.value)
        assert get_success_data(api.get_tour(t2["id"], lb_h))["status"] == "REQUESTED"

    def test_buffered_space_overlap_before_existing_start(self, api):
        """PRD §3.4: "the candidate window conflicts when ... its end is later than that
        existing window's start minus thirty minutes".

        Design: Difficulty/resource_temporal_overlap/space_buffered_overlap_conflict
        """
        lb, tb1 = setup_two_firms()
        tb2 = create_broker(tb1["brokerage_id"], "TENANT_BROKER", "TB2c")
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        space = create_published_space(lb["id"], prop["id"], "72", rentable_sf=2500, asking_rent_psf_yr=50)
        req1 = create_requirement(tb1["id"], "SOMA-SF", "OFFICE", 1000, 5000, 60, "T1")
        req2 = create_requirement(tb2["id"], "SOMA-SF", "OFFICE", 1000, 5000, 60, "T2")
        # existing confirmed 12:00-13:00; candidate 11:00-11:45 ends 11:45 > 12:00-30min=11:30 -> conflict
        t1 = create_tour(tb1["id"], req1["id"], space["id"],
                         "2026-10-05T12:00:00Z", "2026-10-05T13:00:00Z")
        confirm_tour(lb["id"], t1["id"], hold=False)
        t2 = create_tour(tb2["id"], req2["id"], space["id"],
                         "2026-10-05T11:00:00Z", "2026-10-05T11:45:00Z")
        validate_error(api.confirm_tour(t2["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_TOUR_WINDOW_CONFLICT.value)

    def test_candidate_at_buffered_edge_does_not_conflict(self, api):
        """PRD §3.4: "a window that merely touches a buffered edge does not conflict".
        PRD §3.4: "the candidate window conflicts when its start is earlier than that
        existing window's end plus thirty minutes".

        Design: Difficulty/boundary_precision_check/tour_space_buffer_strict_boundary_zero_conflict
        """
        lb, tb1 = setup_two_firms()
        tb2 = create_broker(tb1["brokerage_id"], "TENANT_BROKER", "TB2b")
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "PEARL-DEN", "OFFICE", total_sf=10000)
        space = create_published_space(lb["id"], prop["id"], "41", rentable_sf=2500, asking_rent_psf_yr=45)
        req1 = create_requirement(tb1["id"], "PEARL-DEN", "OFFICE", 1000, 5000, 60, "T1")
        req2 = create_requirement(tb2["id"], "PEARL-DEN", "OFFICE", 1000, 5000, 60, "T2")
        t1 = create_tour(tb1["id"], req1["id"], space["id"],
                         "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z")
        confirm_tour(lb["id"], t1["id"], hold=False)
        # candidate starts exactly at 11:00 + 30min buffer = 11:30: strict < => allowed.
        t2 = create_tour(tb2["id"], req2["id"], space["id"],
                         "2026-09-01T11:30:00Z", "2026-09-01T12:30:00Z")
        tour = validate_success(api.confirm_tour(t2["id"], lb_h, {"hold": False}))
        assert tour["status"] == "CONFIRMED", "tour exactly at the buffered edge confirms"

    def test_candidate_one_minute_inside_buffer_conflicts(self, api):
        """PRD §3.4: "the candidate window conflicts when its start is earlier than that
        existing window's end plus thirty minutes ... a window that merely touches a
        buffered edge does not conflict".

        Design: Difficulty/boundary_precision_check/tour_space_buffer_strict_boundary_zero_conflict
        """
        lb, tb1 = setup_two_firms()
        tb2 = create_broker(tb1["brokerage_id"], "TENANT_BROKER", "TB2d")
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "PEARL-DEN", "OFFICE", total_sf=10000)
        space = create_published_space(lb["id"], prop["id"], "42", rentable_sf=2500, asking_rent_psf_yr=45)
        req1 = create_requirement(tb1["id"], "PEARL-DEN", "OFFICE", 1000, 5000, 60, "T1")
        req2 = create_requirement(tb2["id"], "PEARL-DEN", "OFFICE", 1000, 5000, 60, "T2")
        t1 = create_tour(tb1["id"], req1["id"], space["id"],
                         "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z")
        confirm_tour(lb["id"], t1["id"], hold=False)
        # candidate starts 11:29 < 11:00 + 30min buffer (11:30): strictly inside -> conflict.
        t2 = create_tour(tb2["id"], req2["id"], space["id"],
                         "2026-09-02T11:29:00Z", "2026-09-02T12:29:00Z")
        validate_error(api.confirm_tour(t2["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_TOUR_WINDOW_CONFLICT.value)


class TestBrokerOverlap:
    def test_unbuffered_broker_double_book_conflict(self, api):
        """PRD §3.4: "against any other `CONFIRMED` tour run by the same `tenant_broker_id`
        on any space, the half-open windows conflict with no buffer at all — the candidate
        conflicts when its start is earlier than the existing tour's end and its end is
        later than the existing tour's start ... and a conflict is rejected with
        `ERR_BROKER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/broker_unbuffered_double_book_conflict
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "RIVER-CHI", "OFFICE", total_sf=20000)
        space_x = create_published_space(lb["id"], prop["id"], "X1", rentable_sf=2000, asking_rent_psf_yr=50)
        space_y = create_published_space(lb["id"], prop["id"], "Y1", rentable_sf=2200, asking_rent_psf_yr=50)
        req = create_requirement(tb["id"], "RIVER-CHI", "OFFICE", 1000, 5000, 60)
        # same broker, different spaces, overlapping windows 10:00-11:00 and 10:30-11:30
        tx = create_tour(tb["id"], req["id"], space_x["id"],
                         "2026-11-01T10:00:00Z", "2026-11-01T11:00:00Z")
        confirm_tour(lb["id"], tx["id"], hold=False)
        ty = create_tour(tb["id"], req["id"], space_y["id"],
                         "2026-11-01T10:30:00Z", "2026-11-01T11:30:00Z")
        validate_error(api.confirm_tour(ty["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_BROKER_DOUBLE_BOOKED.value)
        assert get_success_data(api.get_tour(ty["id"], lb_h))["status"] == "REQUESTED"

    def test_back_to_back_broker_tours_do_not_conflict(self, api):
        """PRD §3.4: "so two tours that are exactly back to back (the candidate beginning
        at the instant another ends) do not conflict".

        Design: Difficulty/resource_temporal_overlap/broker_unbuffered_double_book_conflict
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "RIVER-CHI", "OFFICE", total_sf=20000)
        space_x = create_published_space(lb["id"], prop["id"], "X2", rentable_sf=2000, asking_rent_psf_yr=50)
        space_y = create_published_space(lb["id"], prop["id"], "Y2", rentable_sf=2200, asking_rent_psf_yr=50)
        req = create_requirement(tb["id"], "RIVER-CHI", "OFFICE", 1000, 5000, 60)
        tx = create_tour(tb["id"], req["id"], space_x["id"],
                         "2026-11-02T10:00:00Z", "2026-11-02T11:00:00Z")
        confirm_tour(lb["id"], tx["id"], hold=False)
        # candidate begins 11:00 exactly when tx ends: half-open, no buffer => allowed.
        ty = create_tour(tb["id"], req["id"], space_y["id"],
                         "2026-11-02T11:00:00Z", "2026-11-02T12:00:00Z")
        tour = validate_success(api.confirm_tour(ty["id"], lb_h, {"hold": False}))
        assert tour["status"] == "CONFIRMED", "back-to-back broker tours confirm without conflict"


class TestTourCrossEntityAndClock:
    def test_confirm_requires_space_showable(self, api):
        """PRD §3.4: "Confirmation requires the space to be in `AVAILABLE` or `ON_HOLD`; a space that is
        `LEASED`, `OFF_MARKET`, or `UNDER_LOI` causes rejection with
        `ERR_SPACE_NOT_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/tour_confirm_requires_space_showable
        """
        base = setup_published_space_and_requirement(market="ARTS-LA", asset_class="FLEX")
        lb_h = make_listing_broker_headers(base["lb"]["id"])
        tour = create_tour(base["tb"]["id"], base["requirement"]["id"], base["space"]["id"],
                           "2026-09-10T10:00:00Z", "2026-09-10T11:00:00Z")
        # withdraw the space (AVAILABLE -> OFF_MARKET) before confirm
        validate_success(api.withdraw_space(base["space"]["id"], lb_h))
        validate_error(api.confirm_tour(tour["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_SPACE_NOT_AVAILABLE.value)
        assert get_success_data(api.get_tour(tour["id"], lb_h))["status"] == "REQUESTED"

    def test_confirm_on_under_loi_space_rejected(self, api):
        """PRD §3.4: "Confirmation requires the space to be in `AVAILABLE` or `ON_HOLD`; a space that is
        `LEASED`, `OFF_MARKET`, or `UNDER_LOI` causes rejection with
        `ERR_SPACE_NOT_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/tour_confirm_requires_space_showable
        """
        from test_helpers import (
            create_active_listing, setup_accepted_deal,
        )
        # Accept a deal so the space goes UNDER_LOI, then request + try to confirm a tour.
        ctx = setup_accepted_deal(
            co_broke=True, base_rent_psf_yr=50, term_months=60, annual_escalation_pct=0,
            rentable_sf=3000, asking_rent_psf_yr=50, max_rent_psf_yr=70, market="ARTS-LA",
            asset_class="FLEX")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        assert get_success_data(api.get_space(ctx["space"]["id"], lb_h))["status"] == "UNDER_LOI"
        tour_req = create_requirement(ctx["tb"]["id"], "ARTS-LA", "FLEX", 1000, 5000, 70, "Tour Req")
        tour = create_tour(ctx["tb"]["id"], tour_req["id"], ctx["space"]["id"],
                           "2026-09-20T10:00:00Z", "2026-09-20T11:00:00Z")
        validate_error(api.confirm_tour(tour["id"], lb_h, {"hold": False}),
                       ApiErrorId.ERR_SPACE_NOT_AVAILABLE.value)

    def test_complete_before_window_start_rejected(self, api):
        """PRD §3.4: "Completing a tour moves it from `CONFIRMED` to `COMPLETED` and is gated by the clock
        — it requires the server's current time to be at or after `window_start`,
        failing otherwise with `ERR_TOUR_NOT_STARTED`."

        Design: Corner/state_machines/tour_complete_before_window_start_rejected
        """
        base = setup_published_space_and_requirement(market="SOMA-SF", asset_class="OFFICE")
        admin_h = make_admin_headers()
        lb_h = make_listing_broker_headers(base["lb"]["id"])
        tb_h = make_tenant_broker_headers(base["tb"]["id"])
        validate_success(api.set_clock("2026-12-01T09:00:00Z", admin_h))
        tour = create_tour(base["tb"]["id"], base["requirement"]["id"], base["space"]["id"],
                           "2026-12-01T10:00:00Z", "2026-12-01T11:00:00Z")
        confirm_tour(base["lb"]["id"], tour["id"], hold=False)
        validate_error(api.complete_tour(tour["id"], tb_h), ApiErrorId.ERR_TOUR_NOT_STARTED.value)
        assert get_success_data(api.get_tour(tour["id"], lb_h))["status"] == "CONFIRMED"

    def test_no_show_before_window_end_rejected(self, api):
        """PRD §3.4: "Marking a no-show, the listing side's action, moves the tour from `CONFIRMED` to
        `NO_SHOW` and requires the current time to be at or after `window_end`,
        failing otherwise with `ERR_TOUR_NOT_ENDED`."

        Design: Corner/state_machines/tour_no_show_before_window_end_rejected
        """
        base = setup_published_space_and_requirement(market="SOMA-SF", asset_class="OFFICE")
        admin_h = make_admin_headers()
        lb_h = make_listing_broker_headers(base["lb"]["id"])
        validate_success(api.set_clock("2026-12-02T10:30:00Z", admin_h))
        tour = create_tour(base["tb"]["id"], base["requirement"]["id"], base["space"]["id"],
                           "2026-12-02T10:00:00Z", "2026-12-02T11:00:00Z")
        confirm_tour(base["lb"]["id"], tour["id"], hold=False)
        validate_error(api.no_show_tour(tour["id"], lb_h), ApiErrorId.ERR_TOUR_NOT_ENDED.value)
        assert get_success_data(api.get_tour(tour["id"], lb_h))["status"] == "CONFIRMED"
