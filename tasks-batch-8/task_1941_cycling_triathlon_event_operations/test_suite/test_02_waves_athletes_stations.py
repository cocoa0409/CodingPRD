"""Waves and occupancy, athlete roster, aid-station readiness, water
logistics, and volunteer staffing."""
from test_helpers import (
    ApiErrorId,
    assert_aid_station,
    assert_athlete,
    assert_volunteer_assignment,
    assert_water_pool_invariant,
    assert_wave,
    create_aid_station_payload,
    create_athlete_payload,
    create_event,
    create_permitted_event,
    create_published_event,
    create_paid_registration,
    create_confirmed_registration,
    create_volunteer_assignment_payload,
    create_wave_payload,
    get_success_data,
    make_athlete_headers,
    make_race_director_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestWaveCreation:
    def test_wave_creation_defaults_open_empty(self, api, race_director_headers):
        """PRD §3.2: "A new wave opens in `OPEN` status with `assigned_count`
        at 0 and belongs to its event via `event_id`."

        Design: Corner/entities/wave_creation_defaults_open_empty
        """
        event = create_event()
        wave = validate_success(api.create_wave(
            event["id"],
            create_wave_payload(label="W1", division="ELITE",
                                scheduled_start_time="2026-10-15T07:30:00Z",
                                capacity=5, draft_legal=True,
                                age_band_min=18, age_band_max=99),
            race_director_headers), expected_status=201)
        assert_wave(wave)
        assert wave["status"] == "OPEN"
        assert wave["assigned_count"] == 0
        assert wave["actual_start_time"] is None

    def test_wave_invalid_division_rejected(self, api, race_director_headers):
        """PRD §3.2: "a `division` of either `AGE_GROUP` or `ELITE`".
        PRD §2.10: "then request-body validation: required fields, enum
        membership, field formats, datetime ordering where an end must be
        strictly later than its start, and the `reduced_seconds` range on
        appeal decisions, all under `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/wave_invalid_enum_division_returns_400
        """
        event = create_event()
        resp = api.create_wave(
            event["id"],
            create_wave_payload(division="PRO"),
            race_director_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_wave_assigned_count_is_server_computed(self, api,
                                                   race_director_headers):
        """PRD §3.2: "A wave's occupancy is derived, not declared:
        `assigned_count` counts the registrations whose `wave_id` points at
        the wave and whose status is one of `CONFIRMED`, `RACKED`, `RACING`,
        `FINISHED`, or `DSQ`."

        Design: Corner/entities/computed_field_input_ignored
        """
        event = create_event()
        wave = validate_success(api.create_wave(
            event["id"],
            create_wave_payload(label="W1", division="ELITE",
                                scheduled_start_time="2026-10-15T07:30:00Z",
                                capacity=5, draft_legal=True,
                                age_band_min=18, age_band_max=99),
            race_director_headers), expected_status=201)
        assert wave["assigned_count"] == 0, \
            "assigned_count is derived server-side and starts at 0"

    def test_wave_reopen_only_from_closed(self, api, race_director_headers):
        """PRD §3.2: "A `RaceDirector` may also close an `OPEN` wave manually,
        moving it to `CLOSED`, and later reopen it — reopening requires
        `assigned_count` below `capacity` and is rejected with
        `ERR_INVALID_STATE` otherwise". Reopening a wave that is not `CLOSED`
        targets an invalid from-state.

        Design: Corner/state_machines/wave_reopen_only_from_closed
        """
        event = create_event()
        wave = get_success_data(api.create_wave(
            event["id"],
            create_wave_payload(division="ELITE",
                                scheduled_start_time="2026-10-15T07:30:00Z",
                                capacity=5, draft_legal=True,
                                age_band_min=18, age_band_max=99),
            race_director_headers))
        assert wave["status"] == "OPEN"
        resp = api.reopen_wave(wave["id"], race_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_wave(wave["id"], race_director_headers))
        assert after["status"] == "OPEN"


class TestWaveOccupancy:
    def test_wave_full_auto_transition_at_capacity(self, api,
                                                  race_director_headers):
        """PRD §3.2: "When the count reaches `capacity` the wave flips
        automatically from `OPEN` to `FULL`".

        Design: Corner/complexity_layers/wave_full_auto_transition_at_capacity
        """
        ctx = create_published_event(wave_overrides=[{"capacity": 2}])
        event_id = ctx["event"]["id"]
        wave = ctx["waves"][0]
        _, r1 = create_paid_registration(event_id, license_number="USAT-1")
        _, r2 = create_paid_registration(event_id, full_name="Bob B",
                                         birth_date="1992-05-05",
                                         license_number="USAT-2")

        get_success_data(api.confirm_registration(r1["id"], race_director_headers))
        after_one = validate_success(api.get_wave(wave["id"], race_director_headers))
        assert after_one["assigned_count"] == 1
        assert after_one["status"] == "OPEN", "1 < capacity 2 leaves the wave OPEN"

        get_success_data(api.confirm_registration(r2["id"], race_director_headers))
        after_two = validate_success(api.get_wave(wave["id"], race_director_headers))
        assert after_two["assigned_count"] == 2
        assert after_two["status"] == "FULL", \
            "assigned_count reaching capacity flips the wave to FULL"

    def test_wave_roster_count_invariant_confirm_then_withdraw(self, api):
        """PRD §3.2: "A wave's occupancy is derived, not declared:
        `assigned_count` counts the registrations whose `wave_id` points at
        the wave and whose status is one of `CONFIRMED`, `RACKED`, `RACING`,
        `FINISHED`, or `DSQ`."
        PRD §3.4: "A withdrawal from `CONFIRMED` or `RACKED` additionally
        frees the wave slot — `assigned_count` drops by one and a `FULL` wave
        reopens to `OPEN`".

        Design: Difficulty/compensating_invariant/wave_roster_count_invariant
        """
        rd = make_race_director_headers()
        ctx = create_published_event(wave_overrides=[{"capacity": 3}])
        event_id = ctx["event"]["id"]
        wave = ctx["waves"][0]
        athlete, registration = create_paid_registration(event_id)

        before = validate_success(api.get_wave(wave["id"], rd))
        assert before["assigned_count"] == 0

        get_success_data(api.confirm_registration(registration["id"], rd))
        after_confirm = validate_success(api.get_wave(wave["id"], rd))
        assert after_confirm["assigned_count"] == 1, "confirm adds one slot"

        get_success_data(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-1"}))
        after_withdraw = validate_success(api.get_wave(wave["id"], rd))
        assert after_withdraw["assigned_count"] == 0, \
            "withdraw compensates the confirm: 0 -> 1 -> 0"

        roster = get_success_data(api.list_wave_registrations(wave["id"], rd))
        from test_helpers import assert_wave_roster_invariant
        assert_wave_roster_invariant(after_withdraw, roster)

    def test_wave_roster_count_excludes_withdrawn_registrations(self, api):
        """PRD §3.2: "`assigned_count` counts the registrations whose
        `wave_id` points at the wave and whose status is one of `CONFIRMED`,
        `RACKED`, `RACING`, `FINISHED`, or `DSQ`." A WITHDRAWN registration is
        outside that set and must not be counted.

        Design: Difficulty/compensating_invariant/wave_roster_count_invariant
        """
        rd = make_race_director_headers()
        ctx = create_published_event(wave_overrides=[{"capacity": 2}])
        event_id = ctx["event"]["id"]
        wave = ctx["waves"][0]
        athlete, registration = create_confirmed_registration(event_id)
        get_success_data(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-1"}))
        wave_after = validate_success(api.get_wave(wave["id"], rd))
        assert wave_after["assigned_count"] == 0
        assert wave_after["status"] == "OPEN"


class TestAthletes:
    def test_athlete_creation_sets_active_license(self, api,
                                                  race_director_headers):
        """PRD §3.2: "a `RaceDirector` creates each athlete record with a
        `full_name`, a `birth_date` as an ISO `YYYY-MM-DD` date, and the
        athlete's USA Triathlon `license_number`; the record carries the
        event's `event_id` and starts with `license_status` `ACTIVE`."

        Design: Corner/entities/athlete_creation_sets_active_license
        """
        event = create_event()
        athlete = validate_success(api.create_athlete(
            event["id"], create_athlete_payload(), race_director_headers),
            expected_status=201)
        assert_athlete(athlete)
        assert athlete["license_status"] == "ACTIVE"
        assert athlete["event_id"] == event["id"]

    def test_suspended_athlete_cannot_register(self, api,
                                               race_director_headers):
        """PRD §3.4: "The athlete's license must be `ACTIVE` at creation
        (`ERR_ATHLETE_SUSPENDED`)."

        Design: Corner/validations/suspended_athlete_cannot_register
        """
        event = create_event()
        athlete = get_success_data(api.create_athlete(
            event["id"], create_athlete_payload(), race_director_headers))
        get_success_data(api.update_athlete(
            athlete["id"], {"license_status": "SUSPENDED"},
            race_director_headers))
        resp = api.create_registration(
            event["id"],
            {"athlete_id": athlete["id"], "division": "AGE_GROUP",
             "entry_fee_cents": 10000},
            race_director_headers)
        validate_error(resp, ApiErrorId.ERR_ATHLETE_SUSPENDED.value)

    def test_athlete_suspend_cascades_withdrawals(self, api,
                                                  race_director_headers):
        """PRD §3.2: "Moving an athlete to `SUSPENDED` cascades through every
        registration of theirs in `ENTERED`, `PAID`, `CONFIRMED`,
        `WAITLISTED`, or `RACKED`, forcing each to `WITHDRAWN` with a tiered
        provisional refund computed per the withdrawal rule in §3.4; every
        freed wave slot recomputes its wave's `assigned_count` and status and
        triggers waitlist promotion."
        PRD §3.4: "Sixty or more days out, the refundable base is 75 percent
        of `entry_fee_cents`" — at the default clock 2026-08-01T00:00:00Z the
        2026-10-15 start is 75 days out, so a 20000-cent fee refunds
        15000 - 1500 = 13500.

        Design: Corner/state_machines/athlete_suspend_cascades_withdrawals
        """
        ctx = create_published_event(wave_overrides=[{"capacity": 2}],
                                     water_pool_units=100)
        event_id = ctx["event"]["id"]
        wave = ctx["waves"][0]
        athlete, registration = create_confirmed_registration(
            event_id, entry_fee_cents=20000)

        get_success_data(api.update_athlete(
            athlete["id"], {"license_status": "SUSPENDED"},
            race_director_headers))

        after = validate_success(
            api.get_registration(registration["id"], race_director_headers))
        assert after["status"] == "WITHDRAWN"
        assert after["refund_estimate_cents"] == 13500, \
            "75% tier at the default clock: base 15000, fee 1500"

        wave_after = validate_success(api.get_wave(wave["id"],
                                                   race_director_headers))
        assert wave_after["assigned_count"] == 0, "cascade freed the wave slot"


class TestAidStationsAndVolunteers:
    def test_aid_station_creation_unready(self, api, race_director_headers):
        """PRD §3.3: "A new station holds `allocated_water_units` 0 and
        `confirmed_volunteer_count` 0, and therefore reports
        `readiness_status` `UNDERSTAFFED`."

        Design: Corner/entities/aid_station_creation_unready
        """
        event = create_event()
        station = validate_success(api.create_aid_station(
            event["id"], create_aid_station_payload(), race_director_headers),
            expected_status=201)
        assert_aid_station(station)
        assert station["allocated_water_units"] == 0
        assert station["confirmed_volunteer_count"] == 0
        assert station["readiness_status"] == "UNDERSTAFFED"

    def test_volunteer_count_threshold_equals_required(self, api):
        """PRD §3.3: "If `confirmed_volunteer_count` is below
        `required_volunteers`, the station is `UNDERSTAFFED`... Otherwise it
        is `READY`. The boundaries are inclusive on the satisfied side: a
        count exactly equal to its requirement passes that test."

        Design: Difficulty/boundary_precision_check/volunteer_count_threshold_equals_required
        """
        rd = make_race_director_headers()
        vc = TEST_USERS["volunteer_coordinator_headers"]
        event = create_event(water_pool_units=500)
        station = get_success_data(api.create_aid_station(
            event["id"],
            create_aid_station_payload(required_volunteers=2,
                                       required_water_units=100),
            rd))
        get_success_data(api.allocate_water(event["id"], rd))

        a1 = get_success_data(api.create_volunteer_assignment(
            station["id"], create_volunteer_assignment_payload(
                volunteer_id="vol-1"), vc))
        get_success_data(api.confirm_volunteer_assignment(a1["id"], vc))
        at_one = validate_success(api.get_aid_station(station["id"], vc))
        assert at_one["confirmed_volunteer_count"] == 1
        assert at_one["readiness_status"] == "UNDERSTAFFED", \
            "required - 1 is still UNDERSTAFFED"

        a2 = get_success_data(api.create_volunteer_assignment(
            station["id"], create_volunteer_assignment_payload(
                volunteer_id="vol-2"), vc))
        get_success_data(api.confirm_volunteer_assignment(a2["id"], vc))
        at_two = validate_success(api.get_aid_station(station["id"], vc))
        assert at_two["confirmed_volunteer_count"] == 2
        assert at_two["readiness_status"] == "READY", \
            "count exactly equal to the requirement passes the staffing test"

    def test_volunteer_extra_confirm_keeps_ready(self, api):
        """PRD §3.3: "If `confirmed_volunteer_count` is below
        `required_volunteers`, the station is `UNDERSTAFFED`. Otherwise, if
        `allocated_water_units` is below `required_water_units`, the station
        is `WATER_SHORT`. Otherwise it is `READY`." Exceeding the requirement
        stays READY.

        Design: Difficulty/boundary_precision_check/volunteer_count_threshold_equals_required
        """
        rd = make_race_director_headers()
        vc = TEST_USERS["volunteer_coordinator_headers"]
        event = create_event(water_pool_units=500)
        station = get_success_data(api.create_aid_station(
            event["id"],
            create_aid_station_payload(required_volunteers=2,
                                       required_water_units=100),
            rd))
        get_success_data(api.allocate_water(event["id"], rd))
        for i in range(3):
            a = get_success_data(api.create_volunteer_assignment(
                station["id"],
                create_volunteer_assignment_payload(volunteer_id=f"vol-{i}"),
                vc))
            get_success_data(api.confirm_volunteer_assignment(a["id"], vc))
        current = validate_success(api.get_aid_station(station["id"], vc))
        assert current["confirmed_volunteer_count"] == 3
        assert current["readiness_status"] == "READY"

    def test_volunteer_shift_half_open_touching_allowed(self, api):
        """PRD §3.3: "Confirming a shift checks for double-booking across all
        of that volunteer's `CONFIRMED` assignments using half-open interval
        semantics: a conflict exists when the candidate's `shift_start` is
        strictly earlier than the other shift's `shift_end` and the other
        shift's `shift_start` is strictly earlier than the candidate's
        `shift_end`, and a conflicting confirmation is rejected with
        `ERR_SHIFT_OVERLAP`. Purely touching windows — one shift starting
        exactly when another ends — are allowed, and unlike the
        permit-corridor rule there is no buffer."

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_half_open_touching_allowed
        """
        rd = make_race_director_headers()
        vc = TEST_USERS["volunteer_coordinator_headers"]
        event = create_event(water_pool_units=500)
        station = get_success_data(api.create_aid_station(
            event["id"], create_aid_station_payload(), rd))
        base = get_success_data(api.create_volunteer_assignment(
            station["id"],
            create_volunteer_assignment_payload(
                volunteer_id="vol-1",
                shift_start="2026-10-15T06:00:00Z",
                shift_end="2026-10-15T10:00:00Z"),
            vc))
        get_success_data(api.confirm_volunteer_assignment(base["id"], vc))

        touching = get_success_data(api.create_volunteer_assignment(
            station["id"],
            create_volunteer_assignment_payload(
                volunteer_id="vol-1",
                shift_start="2026-10-15T10:00:00Z",
                shift_end="2026-10-15T14:00:00Z"),
            vc))
        confirmed = validate_success(
            api.confirm_volunteer_assignment(touching["id"], vc))
        assert_volunteer_assignment(confirmed)
        assert confirmed["status"] == "CONFIRMED", \
            "a shift starting exactly when another ends is allowed"

        overlapping = get_success_data(api.create_volunteer_assignment(
            station["id"],
            create_volunteer_assignment_payload(
                volunteer_id="vol-1",
                shift_start="2026-10-15T09:59:00Z",
                shift_end="2026-10-15T12:00:00Z"),
            vc))
        resp = api.confirm_volunteer_assignment(overlapping["id"], vc)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value)
        still = validate_success(
            api.get_volunteer_assignment(overlapping["id"], vc))
        assert still["status"] == "OFFERED"

    def test_volunteer_overlap_only_checked_for_same_volunteer(self, api):
        """PRD §3.3: "Confirming a shift checks for double-booking across all
        of that volunteer's `CONFIRMED` assignments" — the overlap check keys
        on `volunteer_id`, so identical windows for a different volunteer do
        not conflict.

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_half_open_touching_allowed
        """
        rd = make_race_director_headers()
        vc = TEST_USERS["volunteer_coordinator_headers"]
        event = create_event(water_pool_units=500)
        station = get_success_data(api.create_aid_station(
            event["id"], create_aid_station_payload(), rd))
        a1 = get_success_data(api.create_volunteer_assignment(
            station["id"], create_volunteer_assignment_payload(
                volunteer_id="vol-1"), vc))
        get_success_data(api.confirm_volunteer_assignment(a1["id"], vc))
        a2 = get_success_data(api.create_volunteer_assignment(
            station["id"], create_volunteer_assignment_payload(
                volunteer_id="vol-2"), vc))
        confirmed = validate_success(
            api.confirm_volunteer_assignment(a2["id"], vc))
        assert confirmed["status"] == "CONFIRMED", \
            "identical window for a different volunteer_id does not conflict"

    def test_no_show_degrades_readiness(self, api):
        """PRD §3.3: "Marking a no-show moves `CONFIRMED` to `NO_SHOW`, also
        terminal, decrementing the station's `confirmed_volunteer_count` by
        one and re-deriving readiness."

        Design: Corner/state_machines/no_show_degrades_readiness
        """
        rd = make_race_director_headers()
        vc = TEST_USERS["volunteer_coordinator_headers"]
        event = create_event(water_pool_units=500)
        station = get_success_data(api.create_aid_station(
            event["id"],
            create_aid_station_payload(required_volunteers=2,
                                       required_water_units=100),
            rd))
        get_success_data(api.allocate_water(event["id"], rd))
        assignments = []
        for i in (1, 2):
            a = get_success_data(api.create_volunteer_assignment(
                station["id"],
                create_volunteer_assignment_payload(volunteer_id=f"vol-{i}"),
                vc))
            get_success_data(api.confirm_volunteer_assignment(a["id"], vc))
            assignments.append(a)
        ready = validate_success(api.get_aid_station(station["id"], vc))
        assert ready["readiness_status"] == "READY"

        get_success_data(api.no_show_volunteer_assignment(
            assignments[0]["id"], vc))
        after = validate_success(api.get_aid_station(station["id"], vc))
        assert after["confirmed_volunteer_count"] == 1
        assert after["readiness_status"] == "UNDERSTAFFED", \
            "losing one of two required volunteers degrades READY to UNDERSTAFFED"


class TestWaterLogistics:
    def test_water_pool_conservation_invariant(self, api,
                                               race_director_headers):
        """PRD §3.3: "Stations are visited in `location_km` ascending order...
        each station receives the smaller of its remaining deficit
        (`required_water_units` minus its current `allocated_water_units`) and
        the water still remaining in the pool, floored at zero... when the
        walk ends, the event's `water_pool_remaining` — always
        `water_pool_units` minus the total allocated across all of the
        event's stations — is refreshed, readiness is re-derived at every
        station". And on return: "deallocation requires
        `allocated_water_units` above zero (`ERR_WATER_NOT_ALLOCATED`
        otherwise), zeroes the station's allocation, adds the prior
        allocation back to `water_pool_remaining`, and re-derives readiness."

        Design: Difficulty/compensating_invariant/water_pool_conservation_invariant
        """
        event = create_event(water_pool_units=1000)
        stations = [
            get_success_data(api.create_aid_station(
                event["id"],
                create_aid_station_payload(name=f"AS-{i}", location_km=km,
                                           required_volunteers=0,
                                           required_water_units=400),
                race_director_headers))
            for i, km in enumerate((10.0, 20.0, 30.0), start=1)
        ]
        get_success_data(api.allocate_water(event["id"], race_director_headers))

        event_after = validate_success(
            api.get_event(event["id"], race_director_headers))
        assert event_after["water_pool_remaining"] == 0, \
            "waterfall grants 400/400/200 by location_km ascending"

        stations_after = [validate_success(api.get_aid_station(
            s["id"], race_director_headers)) for s in stations]
        assert_water_pool_invariant(event_after, stations_after)
        assert [s["allocated_water_units"] for s in stations_after] == [400, 400, 200]
        assert stations_after[2]["readiness_status"] == "WATER_SHORT", \
            "200 allocated < 400 required"

        get_success_data(api.deallocate_water(stations[0]["id"],
                                              race_director_headers))
        event_final = validate_success(
            api.get_event(event["id"], race_director_headers))
        stations_final = [validate_success(api.get_aid_station(
            s["id"], race_director_headers)) for s in stations]
        assert_water_pool_invariant(event_final, stations_final)
        assert event_final["water_pool_remaining"] == 400, \
            "600 allocated + 400 remaining == 1000 total (zero drift)"

    def test_allocate_water_idempotent_when_stations_satisfied(self, api,
                                                               race_director_headers):
        """PRD §3.3: "each station receives the smaller of its remaining
        deficit (`required_water_units` minus its current
        `allocated_water_units`) and the water still remaining in the pool,
        floored at zero so a station already at or over its requirement
        neither gains nor loses water."

        Design: Difficulty/compensating_invariant/water_pool_conservation_invariant
        """
        event = create_event(water_pool_units=500)
        station = get_success_data(api.create_aid_station(
            event["id"],
            create_aid_station_payload(required_water_units=100),
            race_director_headers))
        get_success_data(api.allocate_water(event["id"], race_director_headers))
        get_success_data(api.allocate_water(event["id"], race_director_headers))
        after = validate_success(
            api.get_aid_station(station["id"], race_director_headers))
        assert after["allocated_water_units"] == 100, \
            "a second waterfall grants zero to a satisfied station"
        event_after = validate_success(
            api.get_event(event["id"], race_director_headers))
        assert event_after["water_pool_remaining"] == 400

    def test_deallocate_without_allocation_rejected(self, api,
                                                    race_director_headers):
        """PRD §3.3: "deallocation requires `allocated_water_units` above zero
        (`ERR_WATER_NOT_ALLOCATED` otherwise)".

        Design: Corner/validations/deallocate_without_allocation_rejected
        """
        event = create_event()
        station = get_success_data(api.create_aid_station(
            event["id"], create_aid_station_payload(), race_director_headers))
        resp = api.deallocate_water(station["id"], race_director_headers)
        validate_error(resp, ApiErrorId.ERR_WATER_NOT_ALLOCATED.value)
