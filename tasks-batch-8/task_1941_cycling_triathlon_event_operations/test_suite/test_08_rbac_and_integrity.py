"""Role-based access control, ownership checks, validation ordering, and
sub-resource reachability."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_athlete,
    create_athlete_payload,
    create_aid_station_payload,
    create_event,
    create_paid_registration,
    create_permit_payload,
    create_permitted_event,
    create_road_segment_payload,
    create_safety_assessment_payload,
    create_volunteer_assignment_payload,
    create_wave_payload,
    get_success_data,
    make_athlete_headers,
    make_race_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

RD = TEST_USERS["race_director_headers"]
PC = TEST_USERS["permit_coordinator_headers"]
REFEREE = TEST_USERS["referee_headers"]
TIMER = TEST_USERS["timer_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


class TestRbac:
    def test_referee_cannot_create_wave(self, api, race_director_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".
        PRD §4: `POST /events/{id}/waves` is authorized for RaceDirector only.

        Design: Corner/rbac/rbac_referee_cannot_create_wave
        """
        event = create_event()
        resp = api.create_wave(
            event["id"],
            create_wave_payload(division="ELITE",
                                scheduled_start_time="2026-10-15T07:30:00Z",
                                capacity=5, draft_legal=True,
                                age_band_min=18, age_band_max=99),
            REFEREE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_timer_cannot_assess_penalty(self, api, race_director_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".
        PRD §4: `POST /registrations/{id}/penalties` is authorized for Referee
        only.

        Design: Corner/rbac/rbac_timer_cannot_assess_penalty
        """
        event = create_event()
        athlete = create_athlete(event["id"])
        registration = get_success_data(api.create_registration(
            event["id"],
            {"athlete_id": athlete["id"], "division": "AGE_GROUP",
             "entry_fee_cents": 10000},
            make_athlete_headers(athlete["id"])))
        resp = api.create_penalty(registration["id"], {"kind": "EQUIPMENT"},
                                  TIMER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_athlete_cannot_touch_others_registration(self, api,
                                                      race_director_headers):
        """PRD §2.1: "an `Athlete`-role caller may only act on their own
        records: registering themselves (the payload's `athlete_id` must equal
        `X-User-ID`), and paying, withdrawing, checking a bike in or out, or
        filing an appeal only where the registration's `athlete_id` — for an
        appeal, the penalized registration's `athlete_id` — equals
        `X-User-ID`. Any mismatch is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §3.4: "Payment moves `ENTERED` to `PAID`, again gated on an
        `ACTIVE` license; the athlete or a `RaceDirector` may record it."

        Design: Corner/rbac/rbac_athlete_cannot_touch_others_registration
        """
        event = create_event()
        a1 = create_athlete(event["id"], license_number="USAT-1")
        a2 = create_athlete(event["id"], full_name="Bob B",
                            birth_date="1992-05-05", license_number="USAT-2")
        registration = get_success_data(api.create_registration(
            event["id"],
            {"athlete_id": a1["id"], "division": "AGE_GROUP",
             "entry_fee_cents": 10000},
            make_athlete_headers(a1["id"])))

        resp = api.pay_registration(registration["id"],
                                    make_athlete_headers(a2["id"]))
        # Athlete A2 paying A1's registration is an ownership mismatch.
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

        paid = validate_success(
            api.pay_registration(registration["id"], race_director_headers))
        assert paid["status"] == "PAID", \
            "a RaceDirector may record payment for anyone"

    def test_permit_coordinator_cannot_allocate_water(self, api,
                                                      race_director_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".
        PRD §4: `POST /events/{id}/allocate-water` is authorized for
        RaceDirector only.

        Design: Corner/rbac/rbac_permit_coordinator_cannot_allocate_water
        """
        event = create_event()
        resp = api.allocate_water(event["id"], PC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_race_director_cannot_confirm_volunteer_assignment(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".
        PRD §4: `POST /volunteer-assignments/{id}/confirm` is authorized for
        VolunteerCoordinator only — the denial proves exclusivity even against
        the broad RaceDirector role.

        Design: Corner/rbac/rbac_volunteer_coordinator_exclusive_assignment_ops
        """
        event = create_event()
        station = get_success_data(api.create_aid_station(
            event["id"], create_aid_station_payload(), RD))
        assignment = get_success_data(api.create_volunteer_assignment(
            station["id"], create_volunteer_assignment_payload(), VC))
        resp = api.confirm_volunteer_assignment(assignment["id"], RD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestCrossEntityIntegrity:
    def test_confirm_requires_event_published(self, api):
        """PRD §3.4: "Confirmation is where the wave selector runs, and it is
        a `RaceDirector`-only action guarded by three preconditions evaluated
        in order: the event posture must be `PUBLISHED`
        (`ERR_EVENT_POSTURE`), the logical clock must be strictly earlier than
        24 hours before the event's `start_date` (`ERR_CONFIRM_WINDOW_CLOSED`),
        and the athlete's license must still be `ACTIVE`
        (`ERR_ATHLETE_SUSPENDED`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_event_published
        """
        rd = make_race_director_headers()
        event = create_permitted_event()  # DRAFT -> PERMITTED only
        athlete, registration = create_paid_registration(event["id"])
        assert registration["status"] == "PAID"

        resp = api.confirm_registration(registration["id"], rd)
        validate_error(resp, ApiErrorId.ERR_EVENT_POSTURE.value)

        after = validate_success(api.get_registration(registration["id"], rd))
        assert after["status"] == "PAID", \
            "a posture-blocked confirm leaves the registration PAID"

    def test_confirm_after_publish_succeeds(self, api):
        """PRD §3.4: "the event posture must be `PUBLISHED`
        (`ERR_EVENT_POSTURE`)" — once the event reaches PUBLISHED (with the
        clock comfortably before the deadline), the same confirm succeeds and
        the selector assigns the wave.

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_event_published
        """
        rd = make_race_director_headers()
        from test_helpers import create_published_event
        ctx = create_published_event()
        athlete, registration = create_paid_registration(ctx["event"]["id"])
        confirmed = validate_success(
            api.confirm_registration(registration["id"], rd))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["wave_id"] == ctx["waves"][0]["id"]


class TestValidationOrdering:
    def test_existence_checked_before_state(self, api):
        """PRD §2.10: "Next comes left-to-right path existence
        (`ERR_NOT_FOUND`), then request-body validation... then state-machine
        from-state validity (`ERR_INVALID_STATE`)" — existence precedes state.
        PRD §2.9: "Endpoints that address nested resources validate path
        identifiers left to right — event first, then the child within that
        event, then any grandchild — and reject the request with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        correspond to an existing resource."

        Design: Corner/validations/existence_checked_before_state
        """
        create_event()  # non-empty DB, but no such permit id
        resp = api.approve_permit(NON_EXISTENT_UUID, PC)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
        assert err["error_id"] != ApiErrorId.ERR_INVALID_STATE.value


class TestEndpoints:
    def test_clock_default_is_fixed_launch_time(self, api):
        """PRD §2.5: "Before any operator intervention the clock reads exactly
        `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."
        With a 2026-10-15 start, that fixed instant is 75 days out, so the
        75% tier applies: "Sixty or more days out, the refundable base is 75
        percent of `entry_fee_cents`" (§3.4) — base 15000, fee 1500, estimate
        13500.

        Design: Corner/endpoints/clock_default_is_fixed_launch_time
        """
        rd = make_race_director_headers()
        event = create_event(water_pool_units=100)
        athlete, registration = create_paid_registration(
            event["id"], entry_fee_cents=20000)
        withdrawn = validate_success(api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-1"}))
        assert withdrawn["refund_estimate_cents"] == 13500, (
            "75 days out at the fixed default clock -> 75% tier; "
            "a wall-clock-driven implementation could not produce 13500")

    def test_fk_reverse_reachability_subresources(self, api,
                                                  race_director_headers):
        """PRD §4 lists each child collection under its parent: "List road
        segments of an event", "List permits of a segment", "List athletes of
        an event", "List registrations of an athlete", "List volunteer
        assignments of a station", "List safety assessments of an event",
        "List bike checks of a registration", "List penalties of a
        registration", "List timing records of a registration", and "Get the
        (single) result of a registration as a 0- or 1-element array".

        Design: Corner/endpoints/fk_reverse_reachability_subresources
        """
        event = create_event()
        event_id = event["id"]
        segment = get_success_data(api.create_road_segment(
            event_id, create_road_segment_payload(), PC))
        permit = get_success_data(api.create_permit(
            segment["id"], create_permit_payload(), PC))
        athlete = get_success_data(api.create_athlete(
            event_id, create_athlete_payload(), RD))
        registration = get_success_data(api.create_registration(
            event_id,
            {"athlete_id": athlete["id"], "division": "AGE_GROUP",
             "entry_fee_cents": 10000},
            make_athlete_headers(athlete["id"])))
        station = get_success_data(api.create_aid_station(
            event_id, create_aid_station_payload(), RD))
        assignment = get_success_data(api.create_volunteer_assignment(
            station["id"], create_volunteer_assignment_payload(), VC))
        assessment = get_success_data(api.create_safety_assessment(
            event_id, create_safety_assessment_payload(), RD))

        def ids(data):
            return [item["id"] for item in data]

        segments, _ = validate_paginated(api.list_road_segments(
            event_id, race_director_headers))
        assert ids(segments) == [segment["id"]]

        permits, _ = validate_paginated(api.list_permits(
            segment["id"], race_director_headers))
        assert ids(permits) == [permit["id"]]

        athletes, _ = validate_paginated(api.list_athletes(
            event_id, race_director_headers))
        assert ids(athletes) == [athlete["id"]]

        registrations, _ = validate_paginated(api.list_athlete_registrations(
            athlete["id"], race_director_headers))
        assert ids(registrations) == [registration["id"]]

        assignments, _ = validate_paginated(api.list_volunteer_assignments(
            station["id"], race_director_headers))
        assert ids(assignments) == [assignment["id"]]

        assessments, _ = validate_paginated(api.list_safety_assessments(
            event_id, race_director_headers))
        assert ids(assessments) == [assessment["id"]]

        # Collections with nothing created yet come back as empty arrays.
        for list_call in (
            lambda: api.list_bike_checks(registration["id"],
                                         race_director_headers),
            lambda: api.list_penalties(registration["id"],
                                       race_director_headers),
            lambda: api.list_timing_records(registration["id"],
                                            race_director_headers),
            lambda: api.get_registration_results(registration["id"],
                                                 race_director_headers),
        ):
            data, _ = validate_paginated(list_call())
            assert data == [], "empty sub-resource list returns an empty array"
