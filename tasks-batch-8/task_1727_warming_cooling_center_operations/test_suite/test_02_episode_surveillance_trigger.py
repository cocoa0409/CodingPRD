"""Episode creation defaults, the append-only weather log, and the breach-run
trigger with its boundaries and surveillance cycles (PRD §2.5, §3.1)."""
from test_helpers import (
    ApiErrorId,
    activate_episode,
    assert_episode,
    assert_weather_reading,
    create_episode,
    create_site,
    designate_site,
    evaluate_episode,
    get_episode,
    parse_instant,
    post_breach_run,
    post_weather_reading,
    run_episode_double_cycle,
    setup_episode_trigger_met_without_sites,
    validate_error,
    validate_paginated,
    validate_success,
)
from datetime import datetime, timezone


class TestEpisodeDefaults:
    def test_episode_create_applies_system_defaults(self, api,
                                                    eoc_manager_headers):
        """PRD §3.1: "A new episode stands in `STANDBY` with `trigger_met`
        false, `breach_run_minutes` zero, `extension_count` zero and
        `ops_run_index` zero."

        Design: Corner/entities/episode_create_applies_system_defaults
        """
        resp = api.create_episode(
            {
                "mode": "COOLING",
                "threshold_f": 100.0,
                "sustained_hours_required": 2,
                "scheduled_end_at": "2026-08-12T00:00:00Z",
            },
            eoc_manager_headers,
        )
        data = validate_success(resp, 201)
        assert_episode(data)
        assert data["status"] == "STANDBY"
        assert data["trigger_met"] is False
        assert data["breach_run_minutes"] == 0
        assert data["extension_count"] == 0
        assert data["ops_run_index"] == 0

    def test_weather_reading_is_immutable_event(self, api, eoc_manager_headers):
        """PRD §2.5: "One entity is deliberately exempt: a weather reading is
        an append-only event log entry carrying only `id` and `created_at`. It
        has no `updated_at`, no `version`, and no update or delete endpoint —
        once appended, a reading is immutable."
        PRD §3.1: "Each appended reading records `observed_at` (when the
        observation was taken), `temp_f`, `heat_index_f` and an optional
        `source` of `NWS` or `MANUAL`, defaulting to `MANUAL` when omitted;
        the reading's `episode_id` ties it to the owning episode."

        Design: Corner/entities/weather_reading_is_immutable_event
        """
        episode = create_episode(mode="WARMING", threshold_f=32.0)
        create_resp = api.post_weather_reading(
            episode["id"],
            {"observed_at": "2026-08-10T06:00:00Z", "temp_f": 30.0,
             "heat_index_f": 28.0},
            eoc_manager_headers,
        )
        validate_success(create_resp, 201)
        data, meta = validate_paginated(
            api.list_weather_readings(episode["id"], eoc_manager_headers))
        assert meta["total_count"] == 1
        reading = data[0]
        assert_weather_reading(reading)
        assert reading["episode_id"] == episode["id"]
        assert parse_instant(reading["observed_at"]) == datetime(
            2026, 8, 10, 6, 0, tzinfo=timezone.utc)
        assert reading["source"] == "MANUAL"


class TestBreachRunBoundaries:
    def test_heat_index_exactly_at_threshold_and_exactly_sustained_qualifies(
            self, api, eoc_manager_headers):
        """PRD §3.1: "A reading qualifies as a breach when, on a `COOLING`
        episode, its `heat_index_f` is at least `threshold_f`, or, on a
        `WARMING` episode, its `temp_f` is at most `threshold_f`; both
        comparisons are inclusive."
        PRD §3.1: "Otherwise `breach_run_minutes` is the live run's length in
        minutes from its first breach reading to its last, and `trigger_met`
        is true exactly when that length reaches `sustained_hours_required`
        multiplied by sixty minutes — a run of exactly the required duration
        qualifies."

        Design: Difficulty/boundary_precision_check/heat_index_exactly_at_threshold_and_exactly_sustained_qualifies
        """
        # Five readings at exactly the threshold, 06:00 through 07:00: a run
        # of exactly 60 minutes at exactly sustained_hours_required * 60.
        ep1 = create_episode(mode="COOLING", threshold_f=100.0,
                             sustained_hours_required=1)
        for t in ("2026-08-10T06:00:00Z", "2026-08-10T06:15:00Z",
                  "2026-08-10T06:30:00Z", "2026-08-10T06:45:00Z",
                  "2026-08-10T07:00:00Z"):
            post_weather_reading(ep1["id"], t, temp_f=95.0, heat_index_f=100.0)
        data = validate_success(api.evaluate_episode(ep1["id"], eoc_manager_headers))
        assert data["breach_run_minutes"] == 60
        assert data["trigger_met"] is True
        assert data["status"] == "ACTIVATING"

    def test_subthreshold_reading_and_short_run_do_not_qualify(
            self, api, eoc_manager_headers):
        """PRD §3.1: "both comparisons are inclusive" — so 99.9 against a
        threshold of 100.0 is not a breach — and "`trigger_met` is true
        exactly when that length reaches `sustained_hours_required` multiplied
        by sixty minutes", so a 45-minute run does not qualify.

        Design: Difficulty/boundary_precision_check/heat_index_exactly_at_threshold_and_exactly_sustained_qualifies
        """
        # First reading is 0.1 below the threshold (no breach); the remaining
        # four span only 45 minutes, one notch under the required 60.
        ep2 = create_episode(mode="COOLING", threshold_f=100.0,
                             sustained_hours_required=1)
        post_weather_reading(ep2["id"], "2026-08-10T06:00:00Z",
                             temp_f=95.0, heat_index_f=99.9)
        for t in ("2026-08-10T06:15:00Z", "2026-08-10T06:30:00Z",
                  "2026-08-10T06:45:00Z", "2026-08-10T07:00:00Z"):
            post_weather_reading(ep2["id"], t, temp_f=95.0, heat_index_f=100.5)
        data = validate_success(api.evaluate_episode(ep2["id"], eoc_manager_headers))
        assert data["breach_run_minutes"] == 45
        assert data["trigger_met"] is False
        assert data["status"] == "STANDBY"

    def test_breach_gap_exactly_15_keeps_run_16_breaks_it(
            self, api, eoc_manager_headers):
        """PRD §3.1: "A breach reading whose gap from the previous breach
        reading's `observed_at` is at most fifteen minutes extends the live
        run to its own `observed_at` — a gap of exactly fifteen minutes keeps
        the run alive, while sixteen minutes breaks it."

        Design: Corner/calculations/breach_gap_exactly_15_keeps_run_16_breaks_it
        """
        # Episode A: every gap exactly 15 minutes — one continuous 60-minute run.
        ep_a = create_episode(mode="COOLING", threshold_f=100.0,
                              sustained_hours_required=1)
        post_breach_run(ep_a["id"])
        # Episode B: a 16-minute gap after 06:00 abandons the first reading and
        # starts a fresh 45-minute run at 06:16.
        ep_b = create_episode(mode="COOLING", threshold_f=100.0,
                              sustained_hours_required=1)
        for t in ("2026-08-10T06:00:00Z", "2026-08-10T06:16:00Z",
                  "2026-08-10T06:31:00Z", "2026-08-10T06:46:00Z",
                  "2026-08-10T07:01:00Z"):
            post_weather_reading(ep_b["id"], t, temp_f=95.0, heat_index_f=101.0)

        data_a = validate_success(api.evaluate_episode(ep_a["id"], eoc_manager_headers))
        assert data_a["breach_run_minutes"] == 60
        assert data_a["status"] == "ACTIVATING"

        data_b = validate_success(api.evaluate_episode(ep_b["id"], eoc_manager_headers))
        assert data_b["breach_run_minutes"] == 45
        assert data_b["status"] == "STANDBY"


class TestActivationGates:
    def test_activate_after_breach_reset_returns_trigger_not_met(
            self, api, eoc_manager_headers):
        """PRD §3.1: "It is refused with `ERR_TRIGGER_NOT_MET` when
        `trigger_met` is false at activation time, and with
        `ERR_NO_SITES_DESIGNATED` when the episode has no site activation in
        `OPENING` or `OPEN`."
        PRD §3.1: "A non-breach reading resets the run to empty."

        Design: Corner/validations/activate_after_breach_reset_returns_trigger_not_met
        """
        episode = create_episode()
        post_breach_run(episode["id"])
        site = create_site()
        designate_site(episode["id"], site["id"])
        evaluate_episode(episode["id"])  # ACTIVATING with trigger met
        # The appended non-breach reading recomputes the run to empty.
        post_weather_reading(episode["id"], "2026-08-10T07:15:00Z",
                             temp_f=90.0, heat_index_f=90.0)
        resp = api.activate_episode(episode["id"], eoc_manager_headers)
        validate_error(resp, ApiErrorId.ERR_TRIGGER_NOT_MET, expected_status=409)
        assert get_episode(episode["id"])["status"] == "ACTIVATING"

    def test_activate_without_designated_sites_rejected(self, api,
                                                        eoc_manager_headers):
        """PRD §3.1: "It is refused with `ERR_TRIGGER_NOT_MET` when
        `trigger_met` is false at activation time, and with
        `ERR_NO_SITES_DESIGNATED` when the episode has no site activation in
        `OPENING` or `OPEN`."

        Design: Corner/validations/activate_without_designated_sites_rejected
        """
        ws = setup_episode_trigger_met_without_sites()
        resp = api.activate_episode(ws["episode"]["id"], eoc_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SITES_DESIGNATED,
                       expected_status=409)
        assert get_episode(ws["episode"]["id"])["status"] == "ACTIVATING"

    def test_evaluate_on_active_episode_rejected(self, api, eoc_manager_headers):
        """PRD §3.1: "Evaluation attempted while the episode is `ACTIVE`,
        `DEACTIVATED` or `CLOSED` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/evaluate_on_active_episode_rejected
        """
        episode = create_episode()
        post_breach_run(episode["id"])
        site = create_site()
        designate_site(episode["id"], site["id"])
        evaluate_episode(episode["id"])
        activate_episode(episode["id"])
        resp = api.evaluate_episode(episode["id"], eoc_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_episode(episode["id"])["status"] == "ACTIVE"


class TestSurveillanceCycles:
    def test_standby_activating_standby_cycle(self, api):
        """PRD §3.1: "From `STANDBY` with `trigger_met` true the episode
        advances to `ACTIVATING`. From `ACTIVATING` with `trigger_met` false
        it stands back down to `STANDBY`, mutating no other entity — this
        surveillance cycle may repeat indefinitely as fronts stall and
        rebuild."

        Design: Difficulty/non_linear_state_machine/episode_double_cycle_standby_standdown_and_deactivation_resurge
        """
        run = run_episode_double_cycle()
        assert run["st1"] == "ACTIVATING"   # first 60-minute breach run
        assert run["st2"] == "STANDBY"      # non-breach reading reset the run
        assert run["st3"] == "ACTIVATING"   # second breach run re-arms
        assert run["st4"] == "ACTIVE"

    def test_deactivating_active_resurge_reopens_draining_site(self, api):
        """PRD §3.1: "From `DEACTIVATING` with the trigger newly re-met, the
        episode re-surges to `ACTIVE`: each of its site activations sitting in
        `DRAINING` returns to `OPEN` in `created_at` ascending order, intake
        re-enables there, stays already cancelled are not resurrected, and
        closed activations stay closed."

        Design: Difficulty/non_linear_state_machine/episode_double_cycle_standby_standdown_and_deactivation_resurge
        """
        run = run_episode_double_cycle()
        assert run["st5"] == "DEACTIVATING"
        assert run["st6"] == "ACTIVE"       # re-breach during the drain
        assert run["sa_status"] == "OPEN"   # the drained site re-surged
