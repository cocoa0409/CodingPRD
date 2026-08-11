"""Vendor mobilization scheduling: half-open window overlap, market crew-day
capacity, predecessor chain, schedule/cancel capacity conservation, readiness
cascade, and removal protection."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_vendor_mobilization,
    complete_vendor_window,
    create_vendor_mobilization,
    read_commitment_for_site,
    read_mobilization,
    read_site,
    recalculate_commitment,
    schedule_mobilization_ok,
    set_clock,
    setup_multi_sites_in_build,
    setup_site_in_build,
    setup_site_mobilized,
    validate_error,
    validate_success,
)

SUPER = TEST_USERS["site_superintendent_headers"]


class TestHalfOpenWindowOverlap:
    def test_same_site_vendor_window_half_open_overlap(self, api,
                                                       site_superintendent_headers):
        """PRD §3.5: "The window must not overlap any other mobilization on
        the same site in `PLANNED`, `SCHEDULED`, or `ON_SITE` under half-open
        semantics — two windows that merely touch, one ending exactly when the
        next begins, do not conflict (`ERR_VENDOR_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/same_site_vendor_window_half_open_overlap
        """
        ctx = setup_site_in_build(crews=3)
        site_id = ctx["site"]["id"]
        fix1 = create_vendor_mobilization(site_id, planned_start_on="2026-06-01",
                                          planned_end_on="2026-06-21")
        schedule_mobilization_ok(fix1["id"])
        fix2 = create_vendor_mobilization(site_id, planned_start_on="2026-06-15",
                                          planned_end_on="2026-06-21")
        fix3 = create_vendor_mobilization(site_id, planned_start_on="2026-06-21",
                                          planned_end_on="2026-07-06")

        # [06-15, 06-21) intersects [06-01, 06-21): rejected. The rejected
        # mobilization stays PLANNED, and PLANNED windows still block (§3.5),
        # so fix2 ends exactly where fix3 begins — half-open touching, which
        # must not block fix3 below.
        resp = api.schedule_mobilization(fix2["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_VENDOR_WINDOW_OVERLAP)
        assert read_mobilization(fix2["id"])["status"] == "PLANNED"

        # [06-21, 07-06) starts exactly when the first ends: half-open
        # adjacency is allowed.
        resp = api.schedule_mobilization(fix3["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"

    def test_same_site_adjacent_window_touching_at_start_accepted(
            self, api, site_superintendent_headers):
        """PRD §3.5: "two windows that merely touch, one ending exactly when
        the next begins, do not conflict (`ERR_VENDOR_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/same_site_vendor_window_half_open_overlap
        """
        ctx = setup_site_in_build(crews=3)
        site_id = ctx["site"]["id"]
        fix1 = create_vendor_mobilization(site_id, planned_start_on="2026-06-01",
                                          planned_end_on="2026-06-21")
        schedule_mobilization_ok(fix1["id"])
        # [05-15, 06-01) ends exactly when the scheduled window begins.
        fix0 = create_vendor_mobilization(site_id, planned_start_on="2026-05-15",
                                          planned_end_on="2026-06-01")

        resp = api.schedule_mobilization(fix0["id"], headers=site_superintendent_headers)
        mob = validate_success(resp)
        assert_vendor_mobilization(mob)
        assert mob["status"] == "SCHEDULED"


class TestMarketCrewDayCapacity:
    def test_market_crew_day_aggregate_capacity_boundary(self, api,
                                                         site_superintendent_headers):
        """PRD §3.5: "Finally comes market crew-day capacity: for every day of
        the window, the count of other mobilizations across all sites of the
        same market in `SCHEDULED` or `ON_SITE` whose windows also cover that
        day must be strictly below the market's `max_concurrent_vendor_crews`
        — a day may land exactly at capacity but never above it
        (`ERR_MARKET_CAPACITY_FULL`)."

        Design: Difficulty/resource_temporal_overlap/market_crew_day_aggregate_capacity_boundary
        """
        ctx = setup_multi_sites_in_build(site_count=3, crews=2)
        site_a, site_b, site_c = [s["id"] for s in ctx["sites"]]
        v_a = create_vendor_mobilization(site_a, planned_start_on="2026-06-01",
                                         planned_end_on="2026-06-21")
        v_b = create_vendor_mobilization(site_b, planned_start_on="2026-06-10",
                                         planned_end_on="2026-06-25")
        v_c = create_vendor_mobilization(site_c, planned_start_on="2026-06-15",
                                         planned_end_on="2026-06-30")

        resp = api.schedule_mobilization(v_a["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"
        # Days 2026-06-10..2026-06-20 now hold exactly two crews: at capacity,
        # which is allowed.
        resp = api.schedule_mobilization(v_b["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"
        # A third window would push 2026-06-15..2026-06-20 to three crews.
        resp = api.schedule_mobilization(v_c["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_MARKET_CAPACITY_FULL)
        assert read_mobilization(v_c["id"])["status"] == "PLANNED"

    def test_market_crew_day_disjoint_windows_share_capacity(self, api,
                                                             site_superintendent_headers):
        """PRD §3.5: "for every day of the window, the count of other
        mobilizations across all sites of the same market in `SCHEDULED` or
        `ON_SITE` whose windows also cover that day must be strictly below the
        market's `max_concurrent_vendor_crews` — a day may land exactly at
        capacity but never above it (`ERR_MARKET_CAPACITY_FULL`)."

        Design: Difficulty/resource_temporal_overlap/market_crew_day_aggregate_capacity_boundary
        """
        ctx = setup_multi_sites_in_build(site_count=2, crews=1)
        site_a, site_b = [s["id"] for s in ctx["sites"]]
        # Half-open windows covering disjoint day sets share the single crew.
        v_a = create_vendor_mobilization(site_a, planned_start_on="2026-06-01",
                                         planned_end_on="2026-06-10")
        v_b = create_vendor_mobilization(site_b, planned_start_on="2026-06-10",
                                         planned_end_on="2026-06-20")

        resp = api.schedule_mobilization(v_a["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"
        resp = api.schedule_mobilization(v_b["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"

    def test_vendor_schedule_cancel_capacity_conservation(self, api,
                                                          site_superintendent_headers):
        """PRD §3.5: "Cancelling from `PLANNED` or `SCHEDULED` moves the
        mobilization to `CANCELLED` and releases its market crew-day usage for
        every day of the window."

        Design: Difficulty/compensating_invariant/vendor_schedule_cancel_capacity_conservation
        """
        ctx = setup_multi_sites_in_build(site_count=2, crews=1)
        site_a, site_b = [s["id"] for s in ctx["sites"]]
        v_a = create_vendor_mobilization(site_a, planned_start_on="2026-06-01",
                                         planned_end_on="2026-06-21")
        v_b = create_vendor_mobilization(site_b, planned_start_on="2026-06-10",
                                         planned_end_on="2026-06-25")

        resp = api.schedule_mobilization(v_a["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"
        # While A holds the single crew, B's overlapping window is refused.
        resp = api.schedule_mobilization(v_b["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_MARKET_CAPACITY_FULL)

        resp = api.cancel_mobilization(v_a["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "CANCELLED"
        # Cancel released every day of A's window; B now schedules.
        resp = api.schedule_mobilization(v_b["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"

    def test_vendor_completion_releases_capacity_for_later_windows(
            self, api, site_superintendent_headers):
        """PRD §3.5: "for every day of the window, the count of other
        mobilizations across all sites of the same market in `SCHEDULED` or
        `ON_SITE` whose windows also cover that day must be strictly below the
        market's `max_concurrent_vendor_crews`"
        PRD §3.5: "Completion moves it from `ON_SITE` to `COMPLETE`, stamps
        `actual_end_on`, and recomputes the site's `readiness_posture`"

        Design: Difficulty/compensating_invariant/vendor_schedule_cancel_capacity_conservation
        """
        ctx = setup_multi_sites_in_build(site_count=2, crews=1)
        site_a, site_b = [s["id"] for s in ctx["sites"]]
        v_a = create_vendor_mobilization(site_a, planned_start_on="2026-06-01",
                                         planned_end_on="2026-06-21")
        v_b = create_vendor_mobilization(site_b, planned_start_on="2026-06-10",
                                         planned_end_on="2026-06-25")

        schedule_mobilization_ok(v_a["id"])
        set_clock("2026-06-01T00:00:00Z")
        resp = api.arrive_mobilization(v_a["id"], headers=site_superintendent_headers)
        validate_success(resp)
        # ON_SITE still consumes crew-days: B remains blocked.
        resp = api.schedule_mobilization(v_b["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_MARKET_CAPACITY_FULL)

        resp = api.complete_mobilization(v_a["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "COMPLETE"
        # COMPLETE mobilizations no longer count against the capacity map.
        resp = api.schedule_mobilization(v_b["id"], headers=site_superintendent_headers)
        assert validate_success(resp)["status"] == "SCHEDULED"


class TestPredecessorChain:
    def test_referential_precedes_temporal_on_schedule_conflict(
            self, api, site_superintendent_headers):
        """PRD §2.10: "The server evaluates checks in a fixed order, and the
        first failing check determines which error the client receives"
        PRD §2.10: "8. Cross-entity reference gates — municipality profile
        presence, drawing approval and revision currency, vendor predecessor
        completion, BUILDING permit issuance (`ERR_MUNICIPALITY_PROFILE_MISSING`,
        `ERR_DRAWING_NOT_APPROVED`, `ERR_DRAWING_SUPERSEDED`,
        `ERR_VENDOR_PREDECESSOR_INCOMPLETE`, `ERR_PERMIT_NOT_ISSUED`)."
        PRD §2.10: "9. Temporal gates — bid windows, vendor window feasibility
        and overlap, permit expiry, opening-date locks
        (`ERR_BID_WINDOW_NOT_OPEN`, `ERR_BID_WINDOW_CLOSED`,
        `ERR_BID_WINDOW_STILL_OPEN`, `ERR_SCHEDULE_INFEASIBLE`,
        `ERR_PERMIT_EXPIRED`, `ERR_VENDOR_WINDOW_OVERLAP`,
        `ERR_OPEN_DATE_LOCKED`, `ERR_OPENING_LOCK_ENGAGED`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_vendor_schedule_conflict
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        # FIXTURE scheduled but not complete: predecessor violated.
        vfix = create_vendor_mobilization(site_id, vendor_type="FIXTURE",
                                          planned_start_on="2026-06-01",
                                          planned_end_on="2026-06-21")
        schedule_mobilization_ok(vfix["id"])
        # IT window also overlaps the FIXTURE window: temporal violated too.
        vit = create_vendor_mobilization(site_id, vendor_type="IT",
                                         vendor_name="NetCabling Co",
                                         planned_start_on="2026-06-15",
                                         planned_end_on="2026-06-30")

        resp = api.schedule_mobilization(vit["id"], headers=site_superintendent_headers)
        error = validate_error(resp, ApiErrorId.ERR_VENDOR_PREDECESSOR_INCOMPLETE)
        assert error["error_id"] != "ERR_VENDOR_WINDOW_OVERLAP", (
            "the referential check (step 8) wins over the temporal check (step 9)")
        assert read_mobilization(vit["id"])["status"] == "PLANNED"

    def test_window_overlap_reported_once_predecessor_satisfied(
            self, api, site_superintendent_headers):
        """PRD §3.5: "The window must not overlap any other mobilization on
        the same site in `PLANNED`, `SCHEDULED`, or `ON_SITE` under half-open
        semantics — two windows that merely touch, one ending exactly when the
        next begins, do not conflict (`ERR_VENDOR_WINDOW_OVERLAP`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_vendor_schedule_conflict
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        # FIXTURE completed: the IT predecessor rule is satisfied.
        complete_vendor_window(site_id, "FIXTURE", "2026-05-11", "2026-05-12",
                               "2026-05-11", vendor_name="Fixtures R Us")
        it1 = create_vendor_mobilization(site_id, vendor_type="IT",
                                         vendor_name="NetCabling Co",
                                         planned_start_on="2026-06-15",
                                         planned_end_on="2026-06-30")
        schedule_mobilization_ok(it1["id"])
        it2 = create_vendor_mobilization(site_id, vendor_type="IT",
                                         vendor_name="NetCabling Co",
                                         planned_start_on="2026-06-20",
                                         planned_end_on="2026-07-05")

        resp = api.schedule_mobilization(it2["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_VENDOR_WINDOW_OVERLAP)
        assert read_mobilization(it2["id"])["status"] == "PLANNED"


class TestReadinessCascade:
    def test_vendor_complete_three_hop_readiness_cascade(self, api,
                                                         site_superintendent_headers):
        """PRD §3.5: "Completion moves it from `ON_SITE` to `COMPLETE`, stamps
        `actual_end_on`, and recomputes the site's `readiness_posture`: a
        completed `FIXTURE` mobilization yields `FIXTURE_SET`, a completed
        `IT` yields `IT_LIVE`, and a completed `SIGNAGE` yields
        `SIGNAGE_HUNG`. When every vendor type holds a `COMPLETE`
        mobilization, the site automatically advances from `IN_BUILD` to
        `PUNCH` — readiness reads `SIGNAGE_HUNG`, the opening forecast is
        recomputed, and the site's `version` increments."
        PRD §3.8: "For a mobilization already `ON_SITE`, both variants count
        only the remaining planned time from the later of the cursor and today
        through `planned_end_on`, floored at zero."

        Design: Difficulty/transitive_cascade/vendor_complete_three_hop_readiness_cascade
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        complete_vendor_window(site_id, "FIXTURE", "2026-06-01", "2026-06-21",
                               "2026-06-01", vendor_name="Fixtures R Us")
        complete_vendor_window(site_id, "IT", "2026-06-22", "2026-07-07",
                               "2026-06-22", vendor_name="NetCabling Co")
        vsig = create_vendor_mobilization(site_id, vendor_type="SIGNAGE",
                                          vendor_name="SignPros",
                                          planned_start_on="2026-08-10",
                                          planned_end_on="2026-09-05")
        schedule_mobilization_ok(vsig["id"])
        set_clock("2026-08-10T00:00:00Z")
        validate_success(api.arrive_mobilization(vsig["id"],
                                                 headers=site_superintendent_headers))

        # Pre-completion: ON_SITE SIGNAGE contributes 16 remaining days from
        # 2026-08-20 through 2026-09-05; forecast = 08-20 + 16 + 10 days.
        set_clock("2026-08-20T00:00:00Z")
        oc = read_commitment_for_site(site_id)
        pre = recalculate_commitment(oc["id"])
        assert pre["forecast_open_on"] == "2026-09-15"
        assert pre["protection_posture"] == "AT_RISK"

        # Link 1+2: completion recomputes readiness and auto-advances the site.
        resp = api.complete_mobilization(vsig["id"], headers=site_superintendent_headers)
        validate_success(resp)
        site = read_site(site_id)
        assert site["readiness_posture"] == "SIGNAGE_HUNG"
        assert site["status"] == "PUNCH"

        # Link 3: with no scheduled work remaining the forecast collapses to
        # today + the ten-day punch buffer.
        post = recalculate_commitment(oc["id"])
        assert post["forecast_open_on"] == "2026-08-30"
        assert post["protection_posture"] == "PROTECTED"

    def test_readiness_ladder_per_completed_vendor_type(self, api):
        """PRD §3.5: "a completed `FIXTURE` mobilization yields
        `FIXTURE_SET`, a completed `IT` yields `IT_LIVE`, and a completed
        `SIGNAGE` yields `SIGNAGE_HUNG`. When every vendor type holds a
        `COMPLETE` mobilization, the site automatically advances from
        `IN_BUILD` to `PUNCH`"

        Design: Difficulty/transitive_cascade/vendor_complete_three_hop_readiness_cascade
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        complete_vendor_window(site_id, "FIXTURE", "2026-05-11", "2026-05-12",
                               "2026-05-11", vendor_name="Fixtures R Us")
        site = read_site(site_id)
        assert site["readiness_posture"] == "FIXTURE_SET"
        assert site["status"] == "IN_BUILD", "site advances only when all three complete"

        complete_vendor_window(site_id, "IT", "2026-05-12", "2026-05-13",
                               "2026-05-12", vendor_name="NetCabling Co")
        site = read_site(site_id)
        assert site["readiness_posture"] == "IT_LIVE"
        assert site["status"] == "IN_BUILD"


class TestScheduleAndRemovalGuards:
    def test_vendor_schedule_site_not_in_build_rejected(self, api,
                                                        site_superintendent_headers):
        """PRD §3.5: "The site must be in `IN_BUILD` or `PUNCH`
        (`ERR_SITE_NOT_IN_BUILD`)."

        Design: Corner/errors/c_vendor_schedule_site_not_in_build_rejected
        """
        ctx = setup_site_mobilized()
        vfix = create_vendor_mobilization(ctx["site"]["id"],
                                          planned_start_on="2026-06-01",
                                          planned_end_on="2026-06-21")

        resp = api.schedule_mobilization(vfix["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_IN_BUILD)
        assert read_mobilization(vfix["id"])["status"] == "PLANNED"

    def test_inverted_vendor_window_infeasible(self, api, site_superintendent_headers):
        """PRD §3.5: "The window must be feasible, with `planned_start_on`
        earlier than `planned_end_on` and the end still in the future relative
        to the current date (`ERR_SCHEDULE_INFEASIBLE`)."

        Design: Corner/validations/c_inverted_vendor_window_infeasible
        """
        ctx = setup_site_in_build()
        vfix = create_vendor_mobilization(ctx["site"]["id"],
                                          planned_start_on="2026-06-21",
                                          planned_end_on="2026-06-01")

        resp = api.schedule_mobilization(vfix["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_INFEASIBLE)
        assert read_mobilization(vfix["id"])["status"] == "PLANNED"

    def test_site_remove_blocked_with_on_site_vendor(self, api,
                                                     program_director_headers):
        """PRD §3.1: "Removal is refused while a vendor crew is physically on
        site — any mobilization in `ON_SITE` triggers
        `ERR_ACTIVE_VENDOR_ON_SITE`."

        Design: Corner/state_machines/c_site_remove_blocked_with_on_site_vendor
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        vfix = create_vendor_mobilization(site_id, planned_start_on="2026-05-11",
                                          planned_end_on="2026-05-21")
        schedule_mobilization_ok(vfix["id"])
        set_clock("2026-05-11T00:00:00Z")
        validate_success(api.arrive_mobilization(vfix["id"], headers=SUPER))
        assert read_mobilization(vfix["id"])["status"] == "ON_SITE"

        resp = api.remove_site(site_id, headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_VENDOR_ON_SITE)
        assert read_site(site_id)["status"] == "IN_BUILD"
