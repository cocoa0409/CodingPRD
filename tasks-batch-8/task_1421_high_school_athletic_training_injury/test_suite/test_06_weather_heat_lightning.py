"""Heat policy, lightning holds, and weather suspensions (PRD §3.4)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_venue,
    director_headers,
    get_success_data,
    make_director,
    make_trainer,
    post_weather_reading,
    set_clock,
    setup_covered_event,
    setup_venue_with_active_eap,
    trainer_headers,
    validate_error,
    validate_success,
)


def _activity(venue_id, trainer):
    return validate_success(api_client.get_venue_activity_status(
        venue_id, trainer_headers(trainer)))


class TestHeatTierBoundaries:

    def test_district_tier_boundaries_are_lower_bound_inclusive(self):
        """PRD §3.4: "Under the district table, a reading below 80.0 degrees
        is `NORMAL`; 80.0 up to but not including 84.0 is `CAUTION`; 84.0 up
        to but not including 87.0 is `MODERATE`; 87.0 up to but not including
        90.0 is `SEVERE`; and 90.0 or above is `EXTREME`."
        PRD §3.4: "Tier lower bounds are inclusive — a district reading of
        exactly 84.0 degrees is `MODERATE`, not `CAUTION`."

        Design: Difficulty/boundary_precision_check/heat_tier_boundary_84_inclusive
        """
        tr1 = make_trainer()
        venue = create_venue(venue_name="Stadium", surface="TURF")
        set_clock("2026-08-02T14:00:00Z")

        cases = [
            (83.9, "CAUTION", "2026-08-02T13:00:00Z"),
            (84.0, "MODERATE", "2026-08-02T13:05:00Z"),
            (86.9, "MODERATE", "2026-08-02T13:10:00Z"),
            (87.0, "SEVERE", "2026-08-02T13:15:00Z"),
        ]
        for wbgt, expected_tier, recorded_at in cases:
            post_weather_reading(venue["id"], tr1, value_wbgt_f=wbgt,
                                 recorded_at=recorded_at)
            status = _activity(venue["id"], tr1)
            assert status["current_heat_tier"] == expected_tier, (
                f"{wbgt} F must read {expected_tier}, got "
                f"{status['current_heat_tier']}")

    def test_84_boundary_walk_with_explicit_below_and_above(self):
        """PRD §3.4: "Tier lower bounds are inclusive — a district reading of
        exactly 84.0 degrees is `MODERATE`, not `CAUTION`."

        Design: Difficulty/boundary_precision_check/heat_tier_boundary_84_inclusive
        """
        tr1 = make_trainer()
        venue = create_venue(venue_name="Field Two", surface="GRASS")
        set_clock("2026-08-02T14:00:00Z")
        # Just below the MODERATE band.
        post_weather_reading(venue["id"], tr1, value_wbgt_f=83.9,
                             recorded_at="2026-08-02T13:00:00Z")
        assert _activity(venue["id"], tr1)["current_heat_tier"] == "CAUTION"
        # Exactly on the inclusive lower bound.
        post_weather_reading(venue["id"], tr1, value_wbgt_f=84.0,
                             recorded_at="2026-08-02T13:05:00Z")
        assert _activity(venue["id"], tr1)["current_heat_tier"] == "MODERATE"


class TestHeatPolicyDualVariant:
    """Difficulty instance heat_policy_district_vs_state_on_same_reading."""

    def _setup_two_events(self):
        tr1 = make_trainer("Trainer One")
        tr2 = make_trainer("Trainer Two")
        tr3 = make_trainer("Trainer Three")
        ad = make_director()
        venue, _ = setup_venue_with_active_eap(tr1, ad)
        # HOME_GAME: HIGH-contact base 2 -> covered by two trainers.
        ev_a, _ = setup_covered_event(
            ad, [(tr1, "PRIMARY"), (tr2, "SECONDARY")],
            event_name="Game A", sport="FOOTBALL", event_type="HOME_GAME",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T15:00:00Z", expected_attendance=500)
        # TOURNAMENT: base 2 + tournament 1 = 3 -> covered by three.
        ev_b, _ = setup_covered_event(
            ad, [(tr1, "PRIMARY"), (tr2, "SECONDARY"), (tr3, "SECONDARY")],
            event_name="Tourney B", sport="FOOTBALL", event_type="TOURNAMENT",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T16:00:00Z",
            scheduled_end="2026-08-02T17:00:00Z", expected_attendance=500)
        set_clock("2026-08-02T13:55:00Z")
        post_weather_reading(venue["id"], tr1, value_wbgt_f=90.5,
                             recorded_at="2026-08-02T13:00:00Z")
        return tr1, ev_a, ev_b

    def test_district_table_blocks_home_game_start_at_90_5(self):
        """PRD §3.4: "the breakpoint set depends on context: `TOURNAMENT`
        events use the state-association table, everything else — including
        venue-level status checks — uses the district table."
        PRD §3.4: "An `EXTREME` tier at an `OUTDOOR` venue is a hard stop:
        it suspends every in-progress outdoor event there (reason `HEAT`) and
        blocks any outdoor start or resume with `ERR_HEAT_TIER_EXTREME`."

        Design: Difficulty/dual_variant_calc/heat_policy_district_vs_state_on_same_reading
        """
        tr1, ev_a, _ = self._setup_two_events()
        # District table: 90.5 >= 90.0 -> EXTREME.
        resp = api_client.start_event(ev_a["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_HEAT_TIER_EXTREME)
        ev_a_after = validate_success(api_client.get_event(
            ev_a["id"], trainer_headers(tr1)))
        assert ev_a_after["status"] == "COVERED", \
            "the rejected start leaves the event COVERED"

    def test_state_table_allows_tournament_start_at_90_5(self):
        """PRD §3.4: "Under the state-association table the same five tiers
        begin at 82.0, 86.0, 89.0, and 92.0 degrees respectively."

        Design: Difficulty/dual_variant_calc/heat_policy_district_vs_state_on_same_reading
        """
        tr1, _, ev_b = self._setup_two_events()
        # State-association table: 90.5 in [89.0, 92.0) -> SEVERE, so the
        # identical reading does not block a TOURNAMENT start.
        data = validate_success(api_client.start_event(
            ev_b["id"], trainer_headers(tr1)))
        assert data["status"] == "IN_PROGRESS"


class TestLightningHolds:

    def _setup_started_practice(self):
        tr1 = make_trainer()
        ad = make_director()
        venue, _ = setup_venue_with_active_eap(tr1, ad)
        event, _ = setup_covered_event(
            ad, [(tr1, "PRIMARY")],
            event_name="Practice", sport="SOCCER", event_type="PRACTICE",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T15:30:00Z", expected_attendance=0)
        set_clock("2026-08-02T13:55:00Z")
        validate_success(api_client.start_event(event["id"],
                                                trainer_headers(tr1)))
        return tr1, venue, event

    def test_radius_inclusive_timer_reset_and_all_clear(self):
        """PRD §3.4: "A strike *counts* at a venue when its
        `strike_distance_miles` is no greater than the venue's
        `lightning_radius_miles` — a strike at exactly the radius counts."
        PRD §3.4: "Every new counting strike re-raises the hold from its own
        observation time. The hold is active while the clock is strictly
        before that all-clear instant; at the exact all-clear instant,
        starting and resuming are allowed again."

        Design: Corner/calculations/lightning_timer_reset_and_radius_boundary
        """
        tr1, venue, event = self._setup_started_practice()
        venue_read = validate_success(api_client.get_venue(venue["id"],
                                                           ADMIN))
        assert venue_read["lightning_radius_miles"] == 8.0, \
            "default radius applies (PRD §3.2)"

        # 8.1 mi is outside the radius: no hold, event keeps playing.
        set_clock("2026-08-02T14:00:00Z")
        post_weather_reading(venue["id"], tr1,
                             reading_type="LIGHTNING_STRIKE",
                             value_wbgt_f=None, strike_distance_miles=8.1,
                             recorded_at="2026-08-02T14:00:00Z")
        status = _activity(venue["id"], tr1)
        assert status["lightning_hold_active"] is False
        ev = validate_success(api_client.get_event(event["id"],
                                                   trainer_headers(tr1)))
        assert ev["status"] == "IN_PROGRESS"

        # 8.0 mi counts (inclusive boundary) and suspends the event.
        set_clock("2026-08-02T14:10:00Z")
        post_weather_reading(venue["id"], tr1,
                             reading_type="LIGHTNING_STRIKE",
                             value_wbgt_f=None, strike_distance_miles=8.0,
                             recorded_at="2026-08-02T14:10:00Z")
        ev = validate_success(api_client.get_event(event["id"],
                                                   trainer_headers(tr1)))
        assert ev["status"] == "SUSPENDED_WEATHER"

        # A second counting strike at 14:20 resets the all-clear to 14:50.
        set_clock("2026-08-02T14:20:00Z")
        post_weather_reading(venue["id"], tr1,
                             reading_type="LIGHTNING_STRIKE",
                             value_wbgt_f=None, strike_distance_miles=3.0,
                             recorded_at="2026-08-02T14:20:00Z",
                             source="WEATHER_SERVICE")
        status = _activity(venue["id"], tr1)
        assert_instant_equals(status["lightning_hold_until"],
                              "2026-08-02T14:50:00Z", "lightning_hold_until")

        # Before the all-clear the resume is rejected; at it, allowed.
        set_clock("2026-08-02T14:35:00Z")
        resp = api_client.resume_event(event["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_LIGHTNING_HOLD_ACTIVE)
        set_clock("2026-08-02T14:50:00Z")
        data = validate_success(api_client.resume_event(
            event["id"], trainer_headers(tr1)))
        assert data["status"] == "IN_PROGRESS"

    def test_late_posted_earlier_reading_does_not_displace_tier(self):
        """PRD §3.4: "The current tier at a venue is the tier of the
        `HEAT_WBGT` reading with the latest `recorded_at`; if several
        readings share that timestamp, the most recently created one
        governs".

        Design: Corner/calculations/late_arriving_reading_keeps_current_tier
        """
        tr1 = make_trainer()
        venue = create_venue(venue_name="Track", surface="TRACK")
        set_clock("2026-08-02T14:00:00Z")
        post_weather_reading(venue["id"], tr1, value_wbgt_f=88.0,
                             recorded_at="2026-08-02T13:00:00Z")
        assert _activity(venue["id"], tr1)["current_heat_tier"] == "SEVERE"

        # Posted later but recorded earlier: must not become current.
        post_weather_reading(venue["id"], tr1, value_wbgt_f=81.0,
                             recorded_at="2026-08-02T12:00:00Z",
                             source="WEATHER_SERVICE")
        assert _activity(venue["id"], tr1)["current_heat_tier"] == "SEVERE"


class TestEnvironmentalReadingImmutability:

    def test_reading_carries_no_version_or_updated_at(self):
        """PRD §2.5: "An `EnvironmentalReading` and an `InventoryTransaction`
        are immutable observations: each carries only `id` and `created_at` —
        both `updated_at` and `version` are absent, and neither resource can
        be edited after creation."

        Design: Corner/entities/immutable_environmental_reading_has_no_version
        """
        tr1 = make_trainer()
        venue = create_venue(venue_name="Field")
        set_clock("2026-08-02T14:00:00Z")
        reading = post_weather_reading(venue["id"], tr1, value_wbgt_f=82.5,
                                       recorded_at="2026-08-02T13:00:00Z",
                                       source="MANUAL")
        data = validate_success(api_client.get_weather_reading(
            reading["id"], trainer_headers(tr1)))
        assert data["value_wbgt_f"] == 82.5
        assert data["created_at"]
        assert "version" not in data, "append-only record has no version"
        assert "updated_at" not in data, "append-only record has no updated_at"


class TestEventStartEapGate:
    """Difficulty instance event_start_gated_by_venue_eap (two tests)."""

    def _setup_covered_event_with_approved_eap(self):
        tr1 = make_trainer()
        ad = make_director()
        venue = create_venue(venue_name="Practice Field")
        event, _ = setup_covered_event(
            ad, [(tr1, "PRIMARY")],
            event_name="Practice", sport="SOCCER", event_type="PRACTICE",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T15:30:00Z", expected_attendance=0)
        return tr1, ad, venue, event

    def test_start_blocked_until_eap_active(self):
        """PRD §3.4: "A trainer starts an event only from `COVERED` (any
        other state draws `ERR_INVALID_STATE`), only while the venue has an
        `ACTIVE` emergency action plan — a null `active_eap_id` draws
        `ERR_NO_ACTIVE_EAP`".

        Design: Difficulty/cross_entity_state_dependency/event_start_gated_by_venue_eap
        """
        tr1, ad, venue, event = \
            self._setup_covered_event_with_approved_eap()
        assert event["required_trainer_count"] == 1, \
            "MEDIUM-contact PRACTICE needs one trainer (PRD §3.3)"
        # No EAP exists at all yet: active_eap_id is null.
        resp = api_client.start_event(event["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_EAP)

    def test_approved_but_not_active_eap_still_blocks_start(self):
        """PRD §3.2: "The computed `active_eap_id` is a nullable pointer to
        the venue's currently `ACTIVE` emergency action plan — null until
        one is activated".

        Design: Difficulty/cross_entity_state_dependency/event_start_gated_by_venue_eap
        """
        tr1, ad, venue, event = \
            self._setup_covered_event_with_approved_eap()
        eap = get_success_data(api_client.create_eap(
            {
                "venue_id": venue["id"],
                "version_label": "v1",
                "evacuation_route": "Gate C",
                "aed_location": "Shed",
                "ems_contact": "911",
                "nearest_hospital": "General",
            },
            trainer_headers(tr1)))
        validate_success(api_client.submit_eap(eap["id"],
                                               trainer_headers(tr1)))
        validate_success(api_client.approve_eap(eap["id"],
                                                director_headers(ad)))
        # APPROVED is not ACTIVE: the pointer is still null.
        resp = api_client.start_event(event["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_EAP)

        venue_now = validate_success(api_client.get_venue(venue["id"], ADMIN))
        validate_success(api_client.activate_eap(
            eap["id"], {"expected_venue_version": venue_now["version"]},
            director_headers(ad)))
        data = validate_success(api_client.start_event(
            event["id"], trainer_headers(tr1)))
        assert data["status"] == "IN_PROGRESS"


class TestSuspendResumeCycle:
    """Difficulty instance event_suspend_resume_weather_cycle (two tests)."""

    def _setup_running_event(self):
        tr1 = make_trainer("Trainer One")
        tr2 = make_trainer("Trainer Two")
        ad = make_director()
        venue, _ = setup_venue_with_active_eap(tr1, ad)
        event, (ca1, ca2) = setup_covered_event(
            ad, [(tr1, "PRIMARY"), (tr2, "SECONDARY")],
            event_name="Game E", sport="FOOTBALL", event_type="HOME_GAME",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T17:00:00Z", expected_attendance=500)
        validate_success(api_client.acknowledge_assignment(
            ca1["id"], trainer_headers(tr1)))
        validate_success(api_client.check_in_assignment(
            ca1["id"], trainer_headers(tr1)))
        set_clock("2026-08-02T14:05:00Z")
        validate_success(api_client.start_event(event["id"],
                                                trainer_headers(tr1)))
        return tr1, tr2, ad, venue, event, ca1, ca2

    def test_strike_holds_on_site_assignment_and_resume_restores(self):
        """PRD §3.4: "every coverage assignment of the event in
        `ACKNOWLEDGED` or `ON_SITE` moves to `ON_HOLD` with its pre-hold
        status snapshotted into `pre_hold_status`".
        PRD §3.4: "On resumption the event returns to `IN_PROGRESS`,
        `suspension_reason` is cleared to null, and each `ON_HOLD` assignment
        returns to its snapshotted `pre_hold_status` — `ACKNOWLEDGED` or
        `ON_SITE` — after which `pre_hold_status` is cleared."

        Design: Difficulty/non_linear_state_machine/event_suspend_resume_weather_cycle
        """
        tr1, tr2, ad, venue, event, ca1, ca2 = self._setup_running_event()
        set_clock("2026-08-02T14:30:00Z")
        post_weather_reading(venue["id"], tr1,
                             reading_type="LIGHTNING_STRIKE",
                             value_wbgt_f=None, strike_distance_miles=5.0,
                             recorded_at="2026-08-02T14:30:00Z")
        ev = validate_success(api_client.get_event(event["id"],
                                                   trainer_headers(tr1)))
        assert ev["status"] == "SUSPENDED_WEATHER"
        assert ev["suspension_reason"] == "LIGHTNING"

        ca1_mid = validate_success(api_client.get_coverage_assignment(
            ca1["id"], trainer_headers(tr1)))
        assert ca1_mid["status"] == "ON_HOLD"
        assert ca1_mid["pre_hold_status"] == "ON_SITE", \
            "the pre-hold status is snapshotted"
        ca2_mid = validate_success(api_client.get_coverage_assignment(
            ca2["id"], trainer_headers(tr1)))
        assert ca2_mid["status"] == "ASSIGNED", \
            "only ACKNOWLEDGED/ON_SITE assignments are held"

        # hold_until = 14:30 + 30 minutes = 15:00; resume at the exact
        # all-clear instant is allowed.
        set_clock("2026-08-02T15:00:00Z")
        resumed = validate_success(api_client.resume_event(
            event["id"], trainer_headers(tr1)))
        assert resumed["status"] == "IN_PROGRESS"
        ca1_after = validate_success(api_client.get_coverage_assignment(
            ca1["id"], trainer_headers(tr1)))
        assert ca1_after["status"] == "ON_SITE"
        assert ca1_after["pre_hold_status"] is None, \
            "the snapshot is cleared after the restore"

    def test_cycle_repeats_with_second_strike(self):
        """PRD §3.4: "The system suspends automatically when a newly posted
        reading pushes the venue into an `EXTREME` heat tier (reason `HEAT`)
        or lands a counting lightning strike (reason `LIGHTNING`)."
        PRD §3.4: "This in-and-out weather loop can repeat across a long
        afternoon."

        Design: Difficulty/non_linear_state_machine/event_suspend_resume_weather_cycle
        """
        tr1, tr2, ad, venue, event, ca1, ca2 = self._setup_running_event()
        set_clock("2026-08-02T14:30:00Z")
        post_weather_reading(venue["id"], tr1,
                             reading_type="LIGHTNING_STRIKE",
                             value_wbgt_f=None, strike_distance_miles=5.0,
                             recorded_at="2026-08-02T14:30:00Z")
        set_clock("2026-08-02T15:00:00Z")
        validate_success(api_client.resume_event(event["id"],
                                                 trainer_headers(tr1)))
        # A second counting strike suspends the event again.
        set_clock("2026-08-02T15:10:00Z")
        post_weather_reading(venue["id"], tr1,
                             reading_type="LIGHTNING_STRIKE",
                             value_wbgt_f=None, strike_distance_miles=6.5,
                             recorded_at="2026-08-02T15:10:00Z",
                             source="WEATHER_SERVICE")
        ev = validate_success(api_client.get_event(event["id"],
                                                   trainer_headers(tr1)))
        assert ev["status"] == "SUSPENDED_WEATHER", "the cycle repeats"
        ca2_after = validate_success(api_client.get_coverage_assignment(
            ca2["id"], trainer_headers(tr1)))
        assert ca2_after["status"] == "ASSIGNED", \
            "the unacknowledged assignment stays ASSIGNED through both holds"
