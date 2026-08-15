"""Transition-area bike check-in/check-out security and race start
preconditions."""
from test_helpers import (
    ApiErrorId,
    assert_bike_check,
    check_in_bike,
    create_confirmed_registration,
    create_published_event,
    get_result_of,
    get_success_data,
    make_athlete_headers,
    make_race_director_headers,
    setup_finished_race,
    setup_live_race,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestBikeCheckIn:
    def test_duplicate_bike_checkin_rejected(self, api):
        """PRD §3.5: "Bike check-in — by the athlete or a `RaceDirector` —
        requires the event to be `PUBLISHED` (`ERR_EVENT_POSTURE`), the
        logical clock strictly earlier than the event's `start_date`
        (`ERR_CHECKIN_WINDOW_CLOSED`), and no other `CHECKED_IN` bike check on
        the same registration (`ERR_DUPLICATE_BIKE_CHECKIN`)."

        Design: Corner/validations/duplicate_bike_checkin_rejected
        """
        rd = make_race_director_headers()
        ctx = create_published_event(water_pool_units=100)
        athlete, registration = create_confirmed_registration(
            ctx["event"]["id"], entry_fee_cents=10000)
        first = check_in_bike(registration, athlete, bib_code="BIB-1")
        assert first["status"] == "CHECKED_IN"

        resp = api.check_in_bike(registration["id"], "BIB-2",
                                 make_athlete_headers(athlete["id"]))
        # §3.5 names ERR_DUPLICATE_BIKE_CHECKIN for a second CHECKED_IN record,
        # but §2.10 evaluates from-state validity (ERR_INVALID_STATE: the
        # registration is RACKED, not CONFIRMED) before business constraints.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_DUPLICATE_BIKE_CHECKIN.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

        after = validate_success(api.get_registration(registration["id"], rd))
        assert after["status"] == "RACKED"
        checks = get_success_data(api.list_bike_checks(registration["id"], rd))
        assert len(checks) == 1
        assert checks[0]["bib_code"] == "BIB-1"

    def test_checkin_window_closed(self, api):
        """PRD §3.5: "the logical clock strictly earlier than the event's
        `start_date` (`ERR_CHECKIN_WINDOW_CLOSED`)".

        Design: Corner/errors/error_checkin_window_closed
        """
        rd = make_race_director_headers()
        ctx = create_published_event(water_pool_units=100)
        athlete, registration = create_confirmed_registration(
            ctx["event"]["id"], entry_fee_cents=10000)
        get_success_data(api.set_clock("2026-10-15T08:30:00Z", rd))
        resp = api.check_in_bike(registration["id"], "BIB-1",
                                 make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value)

        after = validate_success(api.get_registration(registration["id"], rd))
        assert after["status"] == "CONFIRMED", \
            "a rejected check-in leaves the registration CONFIRMED"
        checks = get_success_data(api.list_bike_checks(registration["id"], rd))
        assert checks == [], "no BikeCheck created"
        results = get_success_data(api.get_registration_results(
            registration["id"], rd))
        assert results == [], "no Result created"

    def test_immediate_visibility_of_side_effects(self, api):
        """PRD §3.4: "Otherwise the first-ranked wave is assigned: the
        registration moves to `CONFIRMED`, its `wave_id` is set, its
        `age_at_event` is stamped".
        PRD §3.5: "A successful check-in presents a `bib_code`, creates the
        BikeCheck record (carrying the registration's `registration_id`) in
        `CHECKED_IN` status with `checked_in_at` stamped from the clock, moves
        the registration from `CONFIRMED` to `RACKED`, and creates the
        athlete's Result one-for-one with the registration: `PROVISIONAL`, all
        five splits null, `penalty_seconds_total` zero."

        Design: Corner/consistency_model/immediate_visibility_of_side_effects
        """
        rd = make_race_director_headers()
        ctx = create_published_event(water_pool_units=100)
        event_id = ctx["event"]["id"]
        wave = ctx["waves"][0]
        from test_helpers import create_paid_registration
        athlete, paid = create_paid_registration(event_id, entry_fee_cents=10000)
        confirmed = validate_success(api.confirm_registration(paid["id"], rd))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["wave_id"] == wave["id"]
        assert confirmed["age_at_event"] == 36, \
            "2026 - 1990 = 36 stamped on the confirm response itself"

        bike_check = validate_success(api.check_in_bike(
            confirmed["id"], "BIB-1", make_athlete_headers(athlete["id"])),
            expected_status=201)
        assert_bike_check(bike_check)
        assert bike_check["status"] == "CHECKED_IN"
        assert bike_check["registration_id"] == confirmed["id"]

        reg_after = validate_success(api.get_registration(confirmed["id"], rd))
        assert reg_after["status"] == "RACKED", \
            "the follow-up read shows RACKED with no lag"

        result = get_result_of(confirmed["id"])
        assert result["status"] == "PROVISIONAL"
        assert result["penalty_seconds_total"] == 0


class TestBikeCheckOut:
    def test_checkout_state_beats_bib_mismatch(self, api):
        """PRD §3.5: "Check-out is permitted only once the registration is
        `FINISHED` or `DNF` (`ERR_INVALID_STATE`) and only when the presented
        `bib_code` equals the open check-in's `bib_code` (`ERR_BIB_MISMATCH`)".
        PRD §2.10: "then state-machine from-state validity
        (`ERR_INVALID_STATE`)... and finally the operation-specific business
        constraints: bib-code match, duplicate bike check-in, permit-window
        conflict, volunteer-shift overlap, the draft-legal-wave restriction,
        the refund-destination requirement, and the water-deallocation
        precondition." — the state check is evaluated before the bib check.

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_vs_bib_referential
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        assert registration["status"] == "RACING"

        # Wrong bib AND wrong state: the state violation must surface.
        resp = api.check_out_bike(registration["id"], "BIB-999",
                                  make_athlete_headers(athlete["id"]))
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert err["error_id"] != ApiErrorId.ERR_BIB_MISMATCH.value

        checks = get_success_data(api.list_bike_checks(
            registration["id"], make_race_director_headers()))
        assert checks[0]["status"] == "CHECKED_IN"
        assert checks[0]["checked_out_at"] is None

    def test_checkout_wrong_bib_when_finished(self, api):
        """PRD §3.5: "only when the presented `bib_code` equals the open
        check-in's `bib_code` (`ERR_BIB_MISMATCH`)".

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_vs_bib_referential
        """
        # FINISHED satisfies the state check; a wrong bib then hits the
        # referential check on its own.
        ctx = setup_finished_race()
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        assert registration["status"] == "FINISHED"
        resp = api.check_out_bike(registration["id"], "BIB-WRONG",
                                  make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_BIB_MISMATCH.value)
        checks = get_success_data(api.list_bike_checks(
            registration["id"], make_race_director_headers()))
        assert checks[0]["status"] == "CHECKED_IN", \
            "a bib mismatch leaves the check-in open"

    def test_bib_mismatch_satisfaction_path(self, api):
        """PRD §3.5: "Check-out is permitted only once the registration is
        `FINISHED` or `DNF` (`ERR_INVALID_STATE`) and only when the presented
        `bib_code` equals the open check-in's `bib_code` (`ERR_BIB_MISMATCH`);
        it moves the record to `CHECKED_OUT`, terminal, and stamps
        `checked_out_at`."

        Design: Corner/errors/error_bib_mismatch_satisfaction_path
        """
        ctx = setup_finished_race()
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]

        wrong = api.check_out_bike(registration["id"], "BIB-WRONG",
                                   make_athlete_headers(athlete["id"]))
        validate_error(wrong, ApiErrorId.ERR_BIB_MISMATCH.value)
        checks = get_success_data(api.list_bike_checks(
            registration["id"], make_race_director_headers()))
        assert checks[0]["status"] == "CHECKED_IN"

        ok = validate_success(api.check_out_bike(
            registration["id"], "BIB-1", make_athlete_headers(athlete["id"])))
        assert ok["status"] == "CHECKED_OUT"
        assert ok["checked_out_at"] is not None
