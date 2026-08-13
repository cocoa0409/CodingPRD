"""Priority scoring, the allocation run's deterministic ordering and caps,
slot/lights interval semantics, and waitlist promotion."""
from test_helpers import (
    TEST_USERS,
    cancel_permit_as_owner,
    close_allocation_window,
    create_allocation_window,
    create_organization,
    get_application,
    get_permit_for_application,
    get_success_data,
    get_usage_ledger,
    open_allocation_window,
    run_allocation,
    set_clock,
    setup_awarded_permit,
    setup_confirmed_permit,
    setup_late_strike_scenario,
    setup_open_season,
    submit_application,
    validate_success,
)

SUPERVISOR = TEST_USERS["field_supervisor_headers"]


class TestPriorityScoreVariants:
    def test_provisional_score_snapshot_immune_to_late_strike(self, api):
        """PRD §3.5: "Every application carries two scores produced by the same
        priority formula. The provisional variant is snapshotted at submission time
        using the organization's counters as they stand at that instant; the final
        variant is recomputed during the allocation run with organization counters
        frozen at run time, so a strike landing between submission and the run changes
        `final_score` but never `provisional_score`."

        Snapshot with zero active strikes and no prior-season ledger: 80 (RESIDENT)
        + 15 (YOUTH_LEAGUE) + min(12, 3 x 3) loyalty + 0 utilization + 8
        (LEAGUE_GAME) = 112.

        Design: Difficulty/dual_variant_calc/priority_score_provisional_vs_final_after_late_strike
        """
        ctx = setup_late_strike_scenario()
        assert ctx["a2_provisional"] == 112
        # The strike has landed, but no allocation run has executed on W2: the
        # snapshot on the application must not move.
        after = get_application(ctx["a2"]["id"])
        assert after["provisional_score"] == 112
        assert after["final_score"] is None
        assert after["status"] == "SUBMITTED"

    def test_final_score_recomputed_with_late_strike(self, api, athletics_admin_headers):
        """PRD §3.5: "Each active no-show strike subtracts 12 points, using
        `no_show_strikes_active`."
        PRD §3.1: "Standing re-evaluates on every change to the active strike count.
        The moment the count becomes exactly 2, the organization falls from `GOOD` to
        `PROBATION`."

        One strike lands between submission and the run: final = 112 - 12 = 100;
        standing stays GOOD at a single active strike.

        Design: Difficulty/dual_variant_calc/priority_score_provisional_vs_final_after_late_strike
        """
        ctx = setup_late_strike_scenario()
        close_allocation_window(ctx["w2"]["id"])
        run_allocation(ctx["w2"]["id"])
        after = get_application(ctx["a2"]["id"])
        assert after["final_score"] == 100, \
            "final variant must be recomputed with the strike that landed after submission"
        assert after["provisional_score"] == 112, "provisional snapshot is immutable"
        assert after["status"] == "AWARDED", "sole candidate is still awarded"
        org = get_success_data(api.get_organization(
            ctx["organization"]["id"], athletics_admin_headers))
        assert org["no_show_strikes_active"] == 1
        assert org["standing"] == "GOOD"


class TestLoyaltyCapAndTiebreak:
    def _run_tie_scenario(self, api):
        """Two RESIDENT YOUTH_LEAGUE orgs, A with 4 and B with 8 prior seasons,
        apply for the identical slot 2026-08-10 18:00-20:00; A submits before B."""
        ctx = setup_open_season()
        org_a = create_organization(name="Alpha Youth", prior_seasons_active=4)
        org_b = create_organization(name="Beta Youth", prior_seasons_active=8)
        window, facility = ctx["window"], ctx["facility"]
        app_a = submit_application(window["id"], facility["id"], org_a["id"])
        set_clock("2026-08-01T09:01:00Z")  # keep created_at order == submission order
        app_b = submit_application(window["id"], facility["id"], org_b["id"])
        close_allocation_window(window["id"])
        run_allocation(window["id"])
        return get_application(app_a["id"]), get_application(app_b["id"])

    def test_loyalty_cap_produces_exact_score_tie(self, api):
        """PRD §3.5: "Loyalty adds 3 points per prior active season from
        `prior_seasons_active`, capped at 12 points total."

        A: 80 + 15 + min(12, 12) + 0 + 8 = 115. B: 80 + 15 + min(12, 24) + 0 + 8 =
        115 — the cap, not the raw 24, decides.

        Design: Difficulty/combinatorial_formula/priority_score_loyalty_cap_and_tiebreak
        """
        app_a, app_b = self._run_tie_scenario(api)
        assert app_a["final_score"] == 115
        assert app_b["final_score"] == 115, \
            "8 prior seasons must be capped at 12 loyalty points, not scored as 24"

    def test_score_tie_broken_by_earlier_submission(self, api):
        """PRD §3.5: "Running allocation on a `CLOSED` window — which requires a
        `PUBLISHED` fee schedule to exist, failing with `ERR_INVALID_SCHEDULE_STATE`
        otherwise — walks every application of the window that is in `UNDER_REVIEW` in
        a deterministic order: `final_score` descending, with ties broken by earlier
        `created_at`."
        PRD §3.5: "An application whose half-open slot overlaps any application
        already awarded in this run, or any existing `RESERVED` or `CONFIRMED` permit
        on the same facility and date, is waitlisted as `WAITLISTED` with
        `decision_note` `SLOT_CONFLICT`."

        Design: Difficulty/combinatorial_formula/priority_score_loyalty_cap_and_tiebreak
        """
        app_a, app_b = self._run_tie_scenario(api)
        assert app_a["status"] == "AWARDED", "earlier created_at wins the 115-115 tie"
        assert app_b["status"] == "WAITLISTED"
        assert app_b["decision_note"] == "SLOT_CONFLICT"


class TestPrimeCapBoundary:
    def _run_prime_cap_scenario(self, api):
        """One org; window cap 4 prime hours; three 2-hour prime applications on
        2026-08-10/11/12 (facility turf cap 12 does not mask the org cap)."""
        ctx = setup_open_season(window_overrides={"prime_cap_hours_per_org": 4})
        org_id = ctx["organization"]["id"]
        apps = []
        for i, date in enumerate(("2026-08-10", "2026-08-11", "2026-08-12")):
            # Nudge the clock so created_at order matches submission order.
            set_clock(f"2026-08-01T09:0{i}:00Z")
            apps.append(submit_application(ctx["window"]["id"], ctx["facility"]["id"],
                                           org_id, event_date=date))
        close_allocation_window(ctx["window"]["id"])
        run_allocation(ctx["window"]["id"])
        return ctx, [get_application(a["id"]) for a in apps]

    def test_prime_cap_inclusive_boundary_awards_to_cap(self, api):
        """PRD §3.5: "One whose award would push the organization's season
        `awarded_prime_hours` plus the new slot's prime hours above the window's
        `prime_cap_hours_per_org` is waitlisted with `PRIME_CAP` — landing exactly at
        the cap is allowed."

        Cumulative 2h then exactly 4h (== cap, inclusive): both AWARDED; the season
        ledger holds exactly 4 prime hours.

        Design: Difficulty/boundary_precision_check/prime_cap_inclusive_boundary
        """
        ctx, apps = self._run_prime_cap_scenario(api)
        assert apps[0]["status"] == "AWARDED"
        assert apps[1]["status"] == "AWARDED", "exactly at the cap is allowed"
        ledger = get_usage_ledger(ctx["organization"]["id"], "2026-FALL")
        assert ledger["awarded_prime_hours"] == 4

    def test_prime_cap_overflow_waitlisted(self, api):
        """PRD §3.5: "One whose award would push the organization's season
        `awarded_prime_hours` plus the new slot's prime hours above the window's
        `prime_cap_hours_per_org` is waitlisted with `PRIME_CAP` — landing exactly at
        the cap is allowed."

        The third application would reach 6h > 4h: WAITLISTED with PRIME_CAP.

        Design: Difficulty/boundary_precision_check/prime_cap_inclusive_boundary
        """
        _, apps = self._run_prime_cap_scenario(api)
        assert apps[2]["status"] == "WAITLISTED"
        assert apps[2]["decision_note"] == "PRIME_CAP"


class TestFieldSlotOverlapSemantics:
    def _run_overlap_scenario(self, api):
        """Three identical-score orgs (RESIDENT YOUTH_LEAGUE, 0 prior seasons) apply
        on 2026-08-10: A 18:00-20:00, B 20:00-22:00 (adjacent to A), C 19:30-21:00
        (overlaps both); ties decided in created_at order A, B, C."""
        ctx = setup_open_season()
        window, facility = ctx["window"], ctx["facility"]
        orgs = [create_organization(name=f"Org {letter}", prior_seasons_active=0)
                for letter in ("A", "B", "C")]
        app_a = submit_application(window["id"], facility["id"], orgs[0]["id"],
                                   start_minute=1080, end_minute=1200)
        set_clock("2026-08-01T09:01:00Z")  # keep created_at order == submission order
        app_b = submit_application(window["id"], facility["id"], orgs[1]["id"],
                                   start_minute=1200, end_minute=1320)
        set_clock("2026-08-01T09:02:00Z")
        app_c = submit_application(window["id"], facility["id"], orgs[2]["id"],
                                   start_minute=1170, end_minute=1260)
        close_allocation_window(window["id"])
        run_allocation(window["id"])
        return (get_application(app_a["id"]), get_application(app_b["id"]),
                get_application(app_c["id"]))

    def test_adjacent_slots_both_awarded(self, api):
        """PRD §2.9: "Every slot is a half-open interval: a permit occupies the
        minutes from `start_minute` up to but not including `end_minute`. Two slots on
        the same facility and date overlap only when their intervals share at least
        one minute; adjacency — one slot's `end_minute` equal to the other's
        `start_minute` — is not overlap, and back-to-back bookings coexist
        peacefully."

        Design: Difficulty/resource_temporal_overlap/field_slot_half_open_adjacency
        """
        app_a, app_b, _ = self._run_overlap_scenario(api)
        assert app_a["status"] == "AWARDED"
        assert app_b["status"] == "AWARDED", \
            "B starts exactly when A ends (1200 == 1200): half-open adjacency is not a conflict"

    def test_overlapping_slot_waitlisted(self, api):
        """PRD §3.5: "An application whose half-open slot overlaps any application
        already awarded in this run, or any existing `RESERVED` or `CONFIRMED` permit
        on the same facility and date, is waitlisted as `WAITLISTED` with
        `decision_note` `SLOT_CONFLICT`."

        C (19:30-21:00) shares minutes with both awarded slots.

        Design: Difficulty/resource_temporal_overlap/field_slot_half_open_adjacency
        """
        _, _, app_c = self._run_overlap_scenario(api)
        assert app_c["status"] == "WAITLISTED"
        assert app_c["decision_note"] == "SLOT_CONFLICT"


class TestLightsGridSemantics:
    def _run_lights_scenario(self, api):
        """One org, four lights applications: A 2026-08-10 18:00-20:00,
        B 2026-08-10 20:30-22:30 (gap exactly 30), C 2026-08-11 18:00-20:00,
        D 2026-08-11 20:15-22:00 (gap 15 after C). Nightly block cap 16: A(8)+B(8)
        lands exactly on the cap; D's 7 blocks would fit the cap but not the buffer."""
        ctx = setup_open_season(facility_overrides={"weekly_prime_hour_cap": 20})
        org_id = ctx["organization"]["id"]
        window, facility = ctx["window"], ctx["facility"]
        apps = {}
        for i, (key, date, start, end) in enumerate((("a", "2026-08-10", 1080, 1200),
                                                     ("b", "2026-08-10", 1230, 1350),
                                                     ("c", "2026-08-11", 1080, 1200),
                                                     ("d", "2026-08-11", 1215, 1320))):
            # Nudge the clock so created_at order matches submission order.
            set_clock(f"2026-08-01T09:0{i}:00Z")
            apps[key] = submit_application(window["id"], facility["id"], org_id,
                                           event_date=date, start_minute=start,
                                           end_minute=end, wants_lights=True)
        close_allocation_window(window["id"])
        run_allocation(window["id"])
        return {key: get_permit_for_application(a["id"]) for key, a in apps.items()}

    def test_lights_buffer_exactly_30_minutes_approved(self, api):
        """PRD §2.9: "Two lights windows on the same facility and date conflict when
        the gap between them is strictly less than 30 minutes — measured from the
        earlier window's end to the later window's start, symmetrically in either
        order — while a gap of exactly 30 minutes is permitted."
        PRD §2.9: "A facility's `nightly_light_block_cap` bounds the total number of
        15-minute light blocks approvable per calendar date, where each permit
        contributes its approved lights minutes divided by 15 and rounded up to a
        whole block; the cap is inclusive, so a date landing exactly on the cap is
        allowed."

        Design: Difficulty/resource_temporal_overlap/lights_buffer_gap_semantics
        """
        permits = self._run_lights_scenario(api)
        assert permits["a"]["lights_approved"] is True
        assert permits["a"]["quoted_total_cents"] == 9600, \
            "4000 field (2h x 2000) + 8 blocks x 700 lights"
        assert permits["b"]["lights_approved"] is True, \
            "gap of exactly 30 minutes is permitted; nightly blocks 16 == cap is inclusive"

    def test_lights_buffer_under_30_soft_denied(self, api):
        """PRD §3.5: "An application passing every gate is awarded, and the award fans
        out into several records at once. The system creates a Permit in `RESERVED`
        status with `fee_schedule_id` pinned to the currently `PUBLISHED` schedule,
        computes the provisional fee quote of §3.6 onto the permit, and decides lights
        per the grid rules of §2.9 — a buffer conflict or a breached nightly cap never
        blocks the award itself; the permit is simply awarded with `lights_approved`
        false and `lights_minutes_quoted` 0."
        PRD §3.6: "The lights line prices `lights_minutes_quoted` — which equals the
        slot's full duration when lights were approved and 0 otherwise — by dividing
        it into 15-minute blocks rounded up to a whole block and multiplying by the
        pinned `lights_block_cents`, yielding `quoted_lights_fee_cents`."

        D (gap 15 < 30 after C): still RESERVED, lights stripped; the 105-minute
        field fee of 3500 carries no lights line.

        Design: Difficulty/resource_temporal_overlap/lights_buffer_gap_semantics
        """
        permits = self._run_lights_scenario(api)
        permit_d = permits["d"]
        assert permit_d["status"] == "RESERVED"
        assert permit_d["lights_approved"] is False
        assert permit_d["lights_minutes_quoted"] == 0
        assert permit_d["quoted_lights_fee_cents"] == 0
        assert permit_d["quoted_total_cents"] == 3500, \
            "105 minutes x 2000/hr = 3500; the lights fee is stripped"


class TestFeeScheduleBranches:
    def test_tournament_flat_rate_threshold(self, api):
        """PRD §3.6: "When the event is a `TOURNAMENT` and the duration reaches at
        least the pinned schedule's `tournament_day_min_minutes`, the raw field fee is
        the flat `tournament_day_cents` day rate, which replaces hourly billing
        entirely."

        360 minutes (== tournament_day_min_minutes) prices flat at 24000; 300 minutes
        stays hourly at 5 x 2000 = 10000.

        Design: Corner/calculations/tournament_flat_rate_threshold
        """
        ctx = setup_open_season(org_overrides={
            "name": "Regional Tourneys Inc", "org_type": "TOURNAMENT_OPERATOR",
            "prior_seasons_active": 1})
        org_id = ctx["organization"]["id"]
        app_360 = submit_application(ctx["window"]["id"], ctx["facility"]["id"], org_id,
                                     event_date="2026-08-10", start_minute=540,
                                     end_minute=900, event_type="TOURNAMENT",
                                     headcount=100)
        app_300 = submit_application(ctx["window"]["id"], ctx["facility"]["id"], org_id,
                                     event_date="2026-08-11", start_minute=540,
                                     end_minute=840, event_type="TOURNAMENT",
                                     headcount=100)
        close_allocation_window(ctx["window"]["id"])
        run_allocation(ctx["window"]["id"])
        permit_360 = get_permit_for_application(app_360["id"])
        permit_300 = get_permit_for_application(app_300["id"])
        assert permit_360["quoted_field_fee_cents"] == 24000, \
            "duration reaches the 360-minute threshold: flat day rate replaces hourly"
        assert permit_360["quoted_total_cents"] == 24000
        assert permit_300["quoted_field_fee_cents"] == 10000, \
            "below the threshold: hourly branch (300 min x 2000/hr = 10000)"
        assert permit_300["quoted_total_cents"] == 10000

    def test_deposit_floor_and_pct_selection(self, api):
        """PRD §3.6: "The `deposit_required_cents` is the smaller of the quoted total
        and the larger of two floors: `min_deposit_cents`, and the quoted total
        multiplied by `deposit_pct` divided by 100 and rounded half-up."

        3h resident no-lights total is 6000; 25% would be 1500, so the 5000 floor
        governs (max branch) and the total does not clamp it (min branch not taken).

        Design: Corner/calculations/deposit_floor_and_pct_selection
        """
        ctx = setup_awarded_permit(app_overrides={"end_minute": 1260})  # 18:00-21:00
        permit = ctx["permit"]
        assert permit["quoted_total_cents"] == 6000
        assert permit["deposit_required_cents"] == 5000, \
            "min(6000, max(5000, 1500)) — the min_deposit floor governs"

    def test_lights_block_ceil_rounding(self, api):
        """PRD §3.6: "The lights line prices `lights_minutes_quoted` — which equals
        the slot's full duration when lights were approved and 0 otherwise — by
        dividing it into 15-minute blocks rounded up to a whole block and multiplying
        by the pinned `lights_block_cents`, yielding `quoted_lights_fee_cents`."

        50 minutes of lights bills ceil(50/15) = 4 blocks = 2800 cents.

        Design: Corner/calculations/lights_block_ceil_rounding
        """
        ctx = setup_awarded_permit(app_overrides={
            "start_minute": 1080, "end_minute": 1130,  # 18:00-18:50, 50 minutes
            "event_type": "LEAGUE_PRACTICE", "wants_lights": True, "headcount": 20})
        permit = ctx["permit"]
        assert permit["quoted_field_fee_cents"] == 1667, \
            "round_half_up(50 x 2000 / 60 = 1666.67)"
        assert permit["quoted_lights_fee_cents"] == 2800, "ceil(50/15) = 4 blocks x 700"
        assert permit["quoted_total_cents"] == 4467
        assert permit["deposit_required_cents"] == 4467, \
            "min(4467, max(5000, 1117)): the total clamps the floor"


class TestUtilizationBonus:
    def test_utilization_bonus_from_prior_season_ledger(self, api):
        """PRD §3.5: "A utilization bonus looks backward across seasons: ignoring the
        season now being allocated, take the organization's UsageLedger rows from
        prior seasons ordered by `season_code` descending and select the most recent
        row that has any awarded history. Its utilization is the ratio of
        `attended_hours` to the sum of `awarded_prime_hours`, `awarded_nonprime_hours`,
        and `attended_hours`, compared as an exact rational — attended hours
        multiplied by 100 is compared against 80 (respectively 60) multiplied by that
        total, with no rounding of the ratio itself. Utilization of at least 80
        percent earns 10 points; at least 60 percent earns 5; anything lower —
        including the case where no qualifying prior ledger exists and utilization is
        null — earns 0."

        A fully attended 2-hour 2026-SPRING permit (utilization 1.0) earns +10 on the
        fall application: 80 + 15 + min(12, 6) + 10 + 8 = 119. The org is created
        with prior_seasons_active=2 so loyalty contributes exactly 6.

        Design: Corner/calculations/utilization_bonus_from_prior_season_ledger
        """
        # Spring season: award, confirm, attend in full, settle.
        ctx = setup_confirmed_permit(
            app_overrides={"event_date": "2026-08-02", "start_minute": 840,
                           "end_minute": 960, "event_type": "LEAGUE_PRACTICE",
                           "headcount": 30},
            org_overrides={"prior_seasons_active": 2},
            window_overrides={"season_code": "2026-SPRING",
                              "closes_at": "2026-08-01T23:59:59Z"})
        org_id = ctx["organization"]["id"]
        set_clock("2026-08-02T15:00:00Z")
        validate_success(api.check_in_permit(ctx["permit"]["id"],
                                             {"attended_minutes": 120},
                                             SUPERVISOR), 200)
        set_clock("2026-08-02T16:01:00Z")
        validate_success(api.settle_permit(ctx["permit"]["id"], {}, SUPERVISOR), 200)

        # Fall season opens; the new application's provisional score reads the
        # prior-season ledger only (the fall ledger does not exist yet).
        fall = create_allocation_window(season_code="2026-FALL",
                                        opens_at="2026-08-03T00:00:00Z")
        set_clock("2026-08-03T09:00:00Z")
        open_allocation_window(fall["id"])
        application = submit_application(fall["id"], ctx["facility"]["id"], org_id,
                                         event_date="2026-08-10", start_minute=1080,
                                         end_minute=1200, event_type="LEAGUE_GAME",
                                         headcount=40)
        assert application["provisional_score"] == 119, \
            "80 base + 15 youth + 6 loyalty + 10 utilization + 8 LEAGUE_GAME"


class TestUsageLedgerCreation:
    def test_usage_ledger_row_created_on_first_award_with_prime_split(self, api):
        """PRD §3.5: "The organization's UsageLedger for the window's `season_code` is
        created on first award, and `awarded_prime_hours` and `awarded_nonprime_hours`
        rise by the slot's prime and non-prime hours."
        PRD §2.9: "A slot is prime when its `start_minute` is at least 1020 — 5:00 PM
        local time, 1020 minutes after midnight. A slot's prime hours are its duration
        expressed in hours when the slot is prime, and zero otherwise; all cap
        accounting is done in whole hours."

        A 14:00-16:00 award (start 840 < 1020) lands entirely in non-prime hours.

        Design: Corner/entities/usage_ledger_row_created_on_first_award_with_prime_split
        """
        ctx = setup_awarded_permit(app_overrides={
            "start_minute": 840, "end_minute": 960,
            "event_type": "LEAGUE_PRACTICE", "headcount": 30})
        ledger = get_usage_ledger(ctx["organization"]["id"], "2026-FALL")
        assert ledger["season_code"] == "2026-FALL"
        assert ledger["awarded_prime_hours"] == 0
        assert ledger["awarded_nonprime_hours"] == 2


class TestWaitlistPromotion:
    def _run_promotion_scenario(self, api):
        """A (RESIDENT, 3 seasons, score 112) applies first; C (NONRESIDENT, 0
        seasons, 68) second; B (RESIDENT, 0 seasons, 103) third — all for the same
        slot 2026-08-10 18:00-20:00. A is awarded; C and B waitlist."""
        ctx = setup_open_season()
        org_a = ctx["organization"]
        org_c = create_organization(name="Gamma Nonres", classification="NONRESIDENT",
                                    prior_seasons_active=0)
        org_b = create_organization(name="Beta Youth", prior_seasons_active=0)
        window, facility = ctx["window"], ctx["facility"]
        app_a = submit_application(window["id"], facility["id"], org_a["id"])
        set_clock("2026-08-01T09:01:00Z")  # keep created_at order == submission order
        app_c = submit_application(window["id"], facility["id"], org_c["id"])
        set_clock("2026-08-01T09:02:00Z")
        app_b = submit_application(window["id"], facility["id"], org_b["id"])
        close_allocation_window(window["id"])
        run_allocation(window["id"])
        permit_a = get_permit_for_application(app_a["id"])
        return ctx, org_a, org_b, org_c, permit_a, app_b, app_c

    def test_waitlist_promotion_selector_order(self, api):
        """PRD §3.5: "The promotion pool is the `WAITLISTED` applications of the same
        window naming the same `facility_id` and `event_date`, ranked by `final_score`
        descending and then `created_at` ascending; the first candidate whose slot
        fits the freed interval, with all caps re-checked and passing, is promoted to
        `AWARDED` with the full award fan-out described above."

        B (103) is promoted although C (68) submitted earlier: ranking is by score,
        not arrival order.

        Design: Corner/complexity_layers/waitlist_promotion_selector_order
        """
        ctx, org_a, org_b, org_c, permit_a, app_b, app_c = \
            self._run_promotion_scenario(api)
        assert get_application(app_b["id"])["status"] == "WAITLISTED"
        assert get_application(app_c["id"])["status"] == "WAITLISTED"

        res = cancel_permit_as_owner(permit_a["id"], org_a["id"])
        validate_success(res, 200)

        assert get_application(app_b["id"])["status"] == "AWARDED", \
            "higher final_score promotes B despite C's earlier submission"
        assert get_application(app_c["id"])["status"] == "WAITLISTED"

    def test_award_then_cancel_returns_ledger_to_baseline(self, api):
        """PRD §2.10: "A UsageLedger accumulates per organization and season:
        `awarded_prime_hours` and `awarded_nonprime_hours` count the hours held by
        that organization's permits in `RESERVED` or `CONFIRMED` status and rise on
        award and fall on release; `attended_hours` grows at settlement;
        `no_show_count` grows when a permit is marked as a no-show."
        PRD §3.8: "In every cancellation the awarded hours leave the season ledger,
        the facility's `weekly_prime_hours_used` recomputes, waitlist promotion per
        §3.5 runs for the freed slot, and the permit lands in the terminal `CANCELLED`
        state."

        Org A's ledger: +2 at award, -2 at cancel — exactly back to 0, no drift.

        Design: Difficulty/compensating_invariant/usage_ledger_hours_conservation_cancel_promote
        """
        ctx, org_a, _, _, permit_a, _, _ = self._run_promotion_scenario(api)
        ledger_before = get_usage_ledger(org_a["id"], "2026-FALL")
        assert ledger_before["awarded_prime_hours"] == 2

        res = cancel_permit_as_owner(permit_a["id"], org_a["id"])
        validate_success(res, 200)

        ledger_after = get_usage_ledger(org_a["id"], "2026-FALL")
        assert ledger_after["awarded_prime_hours"] == 0, \
            "award (+2) then cancel (-2) must return the ledger to its baseline"

    def test_promotion_readds_freed_hours_to_successor(self, api):
        """PRD §3.5: "The promotion pool is the `WAITLISTED` applications of the same
        window naming the same `facility_id` and `event_date`, ranked by `final_score`
        descending and then `created_at` ascending; the first candidate whose slot
        fits the freed interval, with all caps re-checked and passing, is promoted to
        `AWARDED` with the full award fan-out described above."
        PRD §2.10: "A UsageLedger accumulates per organization and season:
        `awarded_prime_hours` and `awarded_nonprime_hours` count the hours held by
        that organization's permits in `RESERVED` or `CONFIRMED` status and rise on
        award and fall on release; `attended_hours` grows at settlement;
        `no_show_count` grows when a permit is marked as a no-show."

        The freed 2 prime hours reappear on the promoted org's ledger: hours are
        conserved across the system.

        Design: Difficulty/compensating_invariant/usage_ledger_hours_conservation_cancel_promote
        """
        ctx, org_a, org_b, _, permit_a, app_b, _ = self._run_promotion_scenario(api)
        res = cancel_permit_as_owner(permit_a["id"], org_a["id"])
        validate_success(res, 200)

        assert get_application(app_b["id"])["status"] == "AWARDED"
        ledger_b = get_usage_ledger(org_b["id"], "2026-FALL")
        assert ledger_b["awarded_prime_hours"] == 2, \
            "the freed hours are conserved, re-added to the promoted org"
        ledger_a = get_usage_ledger(org_a["id"], "2026-FALL")
        assert ledger_a["awarded_prime_hours"] == 0
