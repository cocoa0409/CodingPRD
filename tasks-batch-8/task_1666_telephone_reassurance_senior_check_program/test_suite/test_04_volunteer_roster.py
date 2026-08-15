"""Volunteer roster: registration, training, confidentiality, reliability, lapse."""
from test_helpers import (
    ApiErrorId,
    add_call_schedule,
    create_assignment,
    create_certified_volunteer,
    create_confidentiality_agreement_payload,
    create_program,
    create_training_record_payload,
    create_volunteer,
    create_volunteer_payload,
    enroll_participant,
    get_assignment,
    log_call,
    make_volunteer_headers,
    set_clock,
    setup_calling_environment,
    validate_error,
    validate_success,
)


class TestVolunteerRegistration:
    def test_volunteer_max_weekly_minutes_out_of_range_rejected(self, api, coordinator_headers):
        """PRD §3.4: "`languages` (ISO 639-1 codes the volunteer can call in) defaults to English only, and `max_weekly_minutes` — the weekly cap on assigned slot-plus-buffer minutes — defaults to 240 and must lie between 60 and 600."
        PRD §2.6: "Independently of this ordering, a malformed payload — a missing required field, an unknown field, an invalid enum value, a `window_start` that is not before its `window_end`, or an out-of-range value — is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/volunteer_max_weekly_minutes_out_of_range_rejected
        """
        create_program()
        resp = api.create_volunteer(
            create_volunteer_payload(full_name="Vol Min", max_weekly_minutes=30),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        ok = api.create_volunteer(
            create_volunteer_payload(full_name="Vol Max", max_weekly_minutes=600),
            coordinator_headers,
        )
        volunteer = validate_success(ok, 201)
        assert volunteer["max_weekly_minutes"] == 600, "600 is the inclusive upper bound"


class TestTrainingAndConfidentiality:
    def test_training_record_status_computed_against_clock(self, api, coordinator_headers):
        """PRD §3.4: "A record's status is computed against the logical clock: `VALID` while the clock has not passed `valid_until`, `EXPIRED` once the clock is strictly past it."

        Design: Corner/entities/training_record_status_computed_against_clock
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol Tr")
        # The logical clock is at the 2026-08-01 default; valid_until is past.
        resp = api.create_training_record(
            volunteer["id"],
            create_training_record_payload(
                module="LISTENING_SKILLS",
                completed_at="2026-01-01T00:00:00Z",
                valid_until="2026-07-01T00:00:00Z",
            ),
            coordinator_headers,
        )
        record = validate_success(resp, 201)
        assert record["status"] == "EXPIRED", (
            "status is computed from valid_until vs the logical clock, never taken from input"
        )

    def test_agreement_signing_supersedes_prior_active(self, api, coordinator_headers):
        """PRD §3.4: "Exactly one agreement per volunteer is `ACTIVE` at any time — a new signature moves the previously `ACTIVE` agreement to `SUPERSEDED`."

        Design: Corner/entities/agreement_signing_supersedes_prior_active
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol Ag")
        headers = make_volunteer_headers(volunteer["id"])
        ag1 = validate_success(
            api.sign_confidentiality_agreement(
                volunteer["id"],
                create_confidentiality_agreement_payload(valid_until="2027-01-01T00:00:00Z"),
                headers,
            ),
            201,
        )
        ag2 = validate_success(
            api.sign_confidentiality_agreement(
                volunteer["id"],
                create_confidentiality_agreement_payload(valid_until="2027-06-01T00:00:00Z"),
                headers,
            ),
            201,
        )
        assert ag2["status"] == "ACTIVE"
        agreements = validate_success(
            api.list_confidentiality_agreements(volunteer["id"], coordinator_headers)
        )
        by_id = {a["id"]: a for a in agreements}
        assert by_id[ag1["id"]]["status"] == "SUPERSEDED"
        assert by_id[ag2["id"]]["status"] == "ACTIVE"
        active = [a for a in agreements if a["status"] == "ACTIVE"]
        assert len(active) == 1, "exactly one ACTIVE agreement per volunteer is conserved"


class TestVolunteerRbac:
    def test_coordinator_cannot_sign_agreement_for_volunteer(self, api, coordinator_headers):
        """PRD §3.4: "Confidentiality agreements are the volunteer's own act: a `VolunteerCaller` signs under their own record (ownership enforced per §2.1) by supplying the `policy_version` being signed and a `valid_until`; `signed_at` is stamped by the server."
        PRD §2.1: "A caller whose role is not listed for an endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/coordinator_cannot_sign_agreement_for_volunteer
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol Sign")
        resp = api.sign_confidentiality_agreement(
            volunteer["id"],
            create_confidentiality_agreement_payload(valid_until="2027-01-01T00:00:00Z"),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        own = api.sign_confidentiality_agreement(
            volunteer["id"],
            create_confidentiality_agreement_payload(valid_until="2027-01-01T00:00:00Z"),
            make_volunteer_headers(volunteer["id"]),
        )
        agreement = validate_success(own, 201)
        assert agreement["status"] == "ACTIVE"

    def test_intake_worker_cannot_certify_volunteer(self, api, intake_headers, coordinator_headers):
        """PRD §2.1: "A caller whose role is not listed for an endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.4: "Certification is the gate that turns training into duty, moving a volunteer from `IN_TRAINING` (or from `LAPSED`, on recertification) to `ACTIVE`."

        Design: Corner/rbac/intake_worker_cannot_certify_volunteer
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol IW")
        validate_success(api.begin_training(volunteer["id"], coordinator_headers))
        for module in ("SAFETY_PROTOCOL", "LISTENING_SKILLS", "MANDATED_REPORTING"):
            validate_success(
                api.create_training_record(
                    volunteer["id"], create_training_record_payload(module=module),
                    coordinator_headers,
                ),
                201,
            )
        validate_success(
            api.sign_confidentiality_agreement(
                volunteer["id"], create_confidentiality_agreement_payload(),
                make_volunteer_headers(volunteer["id"]),
            ),
            201,
        )
        resp = api.certify_volunteer(volunteer["id"], intake_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["status"] == "IN_TRAINING"


class TestVolunteerTerminalState:
    def test_volunteer_reactivate_from_separated_rejected(self, api, coordinator_headers):
        """PRD §3.4: "Separation is permanent: from any status except `SEPARATED` — the terminal state — a coordinator may separate a volunteer, which cancels every future-dated `SCHEDULED` assignment of theirs with `cancel_reason` `MANUAL`."
        PRD §3.4: "Reactivation returns an `INACTIVE` volunteer to `ACTIVE` only after re-running the same training and confidentiality currency checks as certification (`ERR_VOLUNTEER_NOT_CERTIFIED` and `ERR_CONFIDENTIALITY_NOT_CURRENT` respectively)."

        Design: Corner/state_machines/volunteer_reactivate_from_separated_rejected
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol Sep")
        separated = validate_success(api.separate_volunteer(volunteer["id"], coordinator_headers))
        assert separated["status"] == "SEPARATED"
        err1 = api.reactivate_volunteer(volunteer["id"], coordinator_headers)
        validate_error(err1, ApiErrorId.ERR_INVALID_STATE, 409)
        err2 = api.begin_training(volunteer["id"], coordinator_headers)
        validate_error(err2, ApiErrorId.ERR_INVALID_STATE, 409)


class TestReliabilityMinimumHistory:
    def test_reliability_null_below_minimum_history(self, api, coordinator_headers):
        """PRD §3.4: "When the pool holds fewer than ten assignments, `reliability_windowed` and `reliability_streak_adj` are null and the tier remains `SILVER`."
        PRD §3.4: "The tier in turn sets `max_concurrent_assignments`: 12 for `GOLD`, 10 for `SILVER`, 8 for `BRONZE`, and 4 for `PROBATION`."

        Design: Corner/calculations/reliability_null_below_minimum_history
        """
        program, participant, volunteer = setup_calling_environment(
            schedules=(("MON", "09:00", "11:00"), ("TUE", "09:00", "11:00"),
                       ("WED", "09:00", "11:00")),
            volunteer_weekdays=("MON", "TUE", "WED"),
        )
        a1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        a2 = create_assignment(participant["id"], volunteer["id"], "2026-08-04")
        a3 = create_assignment(participant["id"], volunteer["id"], "2026-08-05")
        set_clock("2026-08-05T12:00:00Z")
        log_call(a1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "REACHED_OK", duration_seconds=100)
        log_call(a2["id"], volunteer["id"], "2026-08-04T09:05:00Z", "REACHED_OK", duration_seconds=100)
        log_call(a3["id"], volunteer["id"], "2026-08-05T09:05:00Z", "REACHED_OK", duration_seconds=100)
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after.get("reliability_windowed") is None, "denominator 3 < 10 keeps it null"
        assert after.get("reliability_streak_adj") is None
        assert after["reliability_tier"] == "SILVER"
        assert after["max_concurrent_assignments"] == 10


class TestReliabilityWindowedVsStreakAdjusted:
    """Same 10-assignment history (8 COMPLETED, 1 UNREACHED, 1 EXPIRED as the
    most recent row): windowed 90.0, streak-adjusted 85.0, tier SILVER."""

    def _setup_history(self, api, coordinator_headers):
        """Five LOW participants P1..P5 with MON schedules; one volunteer with
        MON availability; 2026-08-03 five logged calls (4 REACHED_OK +
        1 NO_ANSWER); 2026-08-10 four logged REACHED_OK and one slot left
        unlogged, expired by the 2026-08-11 closeout."""
        program = create_program(total_capacity=20, max_reserve_slots=0)
        participants = []
        windows = [("09:00", "11:00"), ("10:00", "12:00"), ("10:00", "12:00"),
                   ("11:00", "13:00"), ("12:00", "14:00")]
        for i in range(5):
            p = enroll_participant({"full_name": f"P{i+1}"})
            add_call_schedule(p["id"], weekday="MON",
                              window_start=windows[i][0], window_end=windows[i][1])
            participants.append(p)
        volunteer = create_certified_volunteer(weekdays=("MON",))
        day1, day2 = [], []
        hours = ["09:00", "10:00", "11:00", "12:00", "13:00"]
        for i, p in enumerate(participants):
            day1.append(create_assignment(p["id"], volunteer["id"], "2026-08-03",
                                          window_start=hours[i], window_end=f"{int(hours[i][:2]):02d}:30"))
            day2.append(create_assignment(p["id"], volunteer["id"], "2026-08-10",
                                          window_start=hours[i], window_end=f"{int(hours[i][:2]):02d}:30"))
        set_clock("2026-08-03T14:00:00Z")
        for i in range(4):
            log_call(day1[i]["id"], volunteer["id"],
                     f"2026-08-03T{hours[i][:2]}:05:00Z", "REACHED_OK")
        log_call(day1[4]["id"], volunteer["id"], "2026-08-03T13:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        set_clock("2026-08-10T14:00:00Z")
        for i in range(4):
            log_call(day2[i]["id"], volunteer["id"],
                     f"2026-08-10T{hours[i][:2]}:05:00Z", "REACHED_OK")
        # day2[4] (13:00-13:30) is left unlogged; the 08-11 closeout expires it.
        set_clock("2026-08-11T08:00:00Z")
        closeout = validate_success(api.daily_closeout(program["id"], coordinator_headers))
        assert day2[4]["id"] in closeout["expired_assignment_ids"]
        return program, volunteer

    def test_reliability_windowed_counts_unreached_as_showed_up(self, api, coordinator_headers):
        """PRD §3.4: "With ten or more, the showed-up count is the pool's `COMPLETED` and `UNREACHED` rows — an `UNREACHED` row is a participant-side miss, not a volunteer no-show — and `reliability_windowed` is the showed-up count divided by the pool size, multiplied by 100, rounded half-up to one decimal place."
        PRD §3.4: "`reliability_tier` bands the windowed value: `GOLD` at 95.0 or above, `SILVER` at 80.0 or above, `BRONZE` at 60.0 or above, and `PROBATION` below that."

        Design: Difficulty/dual_variant_calc/reliability_windowed_vs_streak_adjusted_diverge
        """
        program, volunteer = self._setup_history(api, coordinator_headers)
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["reliability_windowed"] == 90.0, (
            f"9 showed-up of 10 in the trailing 28 days = 90.0, got {after['reliability_windowed']}"
        )
        assert after["reliability_tier"] == "SILVER", "90.0 falls in [80.0, 95.0)"

    def test_reliability_streak_adjusted_subtracts_trailing_expired_miss(self, api, coordinator_headers):
        """PRD §3.4: "The streak is the length of the trailing run of `EXPIRED` rows when the pool is ordered by `scheduled_date` ascending, then `window_start` ascending, then `created_at` ascending; `reliability_streak_adj` is `reliability_windowed` minus 5 points per consecutive trailing miss, floored at zero, and is strictly below `reliability_windowed` whenever the most recent rows contain an unbroken expired run."

        Design: Difficulty/dual_variant_calc/reliability_windowed_vs_streak_adjusted_diverge
        """
        program, volunteer = self._setup_history(api, coordinator_headers)
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["reliability_streak_adj"] == 85.0, (
            "90.0 - 5 x 1 trailing EXPIRED miss (2026-08-10 13:00) = 85.0"
        )
        assert after["reliability_streak_adj"] < after["reliability_windowed"], (
            "identical rows, two divergent metrics"
        )


class TestReliabilityBronzeFloor:
    """6 showed-up of 10 -> windowed exactly 60.0 (the inclusive BRONZE floor);
    four trailing EXPIRED misses pull streak-adjusted to 40.0."""

    def _setup_bronze_history(self, api, coordinator_headers):
        program = create_program(total_capacity=10, max_reserve_slots=0)
        m1 = enroll_participant({"full_name": "MB1"})
        add_call_schedule(m1["id"], weekday="MON", window_start="09:00", window_end="11:00")
        add_call_schedule(m1["id"], weekday="TUE", window_start="09:00", window_end="11:00")
        m2 = enroll_participant({"full_name": "MB2"})
        add_call_schedule(m2["id"], weekday="MON", window_start="11:00", window_end="13:00")
        add_call_schedule(m2["id"], weekday="TUE", window_start="11:00", window_end="13:00")
        m3 = enroll_participant({"full_name": "MB3"})
        add_call_schedule(m3["id"], weekday="MON", window_start="13:00", window_end="15:00")
        add_call_schedule(m3["id"], weekday="TUE", window_start="13:00", window_end="15:00")
        volunteer = create_certified_volunteer(
            weekdays=("MON", "TUE"),
            volunteer_overrides={"max_weekly_minutes": 600},
        )
        slots = [
            (m1, "2026-08-03", "09:00", "09:30"), (m1, "2026-08-03", "10:00", "10:30"),
            (m2, "2026-08-03", "11:00", "11:30"), (m2, "2026-08-03", "12:00", "12:30"),
            (m3, "2026-08-03", "13:00", "13:30"),
            (m1, "2026-08-04", "09:00", "09:30"),
        ]
        logged = []
        for p, date, start, end in slots:
            logged.append(create_assignment(p["id"], volunteer["id"], date,
                                            window_start=start, window_end=end))
        # Four further 08-04 assignments are left unlogged and expire.
        unlogged = []
        for p, start, end in [(m1, "10:00", "10:30"), (m2, "11:00", "11:30"),
                              (m2, "12:00", "12:30"), (m3, "13:00", "13:30")]:
            unlogged.append(create_assignment(p["id"], volunteer["id"], "2026-08-04",
                                              window_start=start, window_end=end))
        set_clock("2026-08-04T14:00:00Z")
        for a, (p, date, start, end) in zip(logged, slots):
            log_call(a["id"], volunteer["id"], f"{date}T{start[:2]}:05:00Z", "REACHED_OK",
                     duration_seconds=120)
        set_clock("2026-08-05T08:00:00Z")
        closeout = validate_success(api.daily_closeout(program["id"], coordinator_headers))
        for a in unlogged:
            assert a["id"] in closeout["expired_assignment_ids"]
        return program, volunteer

    def test_windowed_sixty_is_bronze_not_probation(self, api, coordinator_headers):
        """PRD §3.4: "`reliability_tier` bands the windowed value: `GOLD` at 95.0 or above, `SILVER` at 80.0 or above, `BRONZE` at 60.0 or above, and `PROBATION` below that."

        Design: Corner/calculations/reliability_tier_bronze_floor_boundary
        """
        program, volunteer = self._setup_bronze_history(api, coordinator_headers)
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["reliability_windowed"] == 60.0, (
            f"6 showed-up of 10 = 60.0, got {after['reliability_windowed']}"
        )
        assert after["reliability_tier"] == "BRONZE", "60.0 is the inclusive BRONZE floor"

    def test_streak_adjusted_subtracts_four_trailing_misses(self, api, coordinator_headers):
        """PRD §3.4: "The streak is the length of the trailing run of `EXPIRED` rows when the pool is ordered by `scheduled_date` ascending, then `window_start` ascending, then `created_at` ascending; `reliability_streak_adj` is `reliability_windowed` minus 5 points per consecutive trailing miss, floored at zero, and is strictly below `reliability_windowed` whenever the most recent rows contain an unbroken expired run."

        Design: Corner/calculations/reliability_tier_bronze_floor_boundary
        """
        program, volunteer = self._setup_bronze_history(api, coordinator_headers)
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["reliability_streak_adj"] == 40.0, (
            "60.0 - 5 x 4 trailing EXPIRED misses (the unlogged 2026-08-04 rows) = 40.0"
        )


class TestTrainingLapseCloseoutCascade:
    """Closeout finds SAFETY_PROTOCOL EXPIRED -> volunteer LAPSED -> future
    SCHEDULED assignment CANCELLED (VOLUNTEER_LAPSED) -> participant
    coverage_deficient recomputed true."""

    def _setup_lapse_scenario(self, api, coordinator_headers):
        program = create_program(total_capacity=5, max_reserve_slots=0)
        participant = enroll_participant({"full_name": "Lap P"})
        add_call_schedule(participant["id"], weekday="TUE",
                          window_start="09:00", window_end="11:00")
        volunteer = create_volunteer(full_name="Vol L")
        validate_success(api.begin_training(volunteer["id"], coordinator_headers))
        # SAFETY_PROTOCOL lapses 2026-08-05; the other modules run to 2027.
        validate_success(api.create_training_record(
            volunteer["id"],
            create_training_record_payload(module="SAFETY_PROTOCOL",
                                           completed_at="2026-06-01T00:00:00Z",
                                           valid_until="2026-08-05T00:00:00Z"),
            coordinator_headers,
        ), 201)
        for module in ("LISTENING_SKILLS", "MANDATED_REPORTING"):
            validate_success(api.create_training_record(
                volunteer["id"], create_training_record_payload(module=module),
                coordinator_headers,
            ), 201)
        validate_success(api.sign_confidentiality_agreement(
            volunteer["id"], create_confidentiality_agreement_payload(),
            make_volunteer_headers(volunteer["id"]),
        ), 201)
        validate_success(api.certify_volunteer(volunteer["id"], coordinator_headers))
        validate_success(api.create_availability_window(
            volunteer["id"],
            {"weekday": "TUE", "window_start": "08:00", "window_end": "17:00",
             "effective_from": "2026-08-01"},
            coordinator_headers,
        ), 201)
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-11")
        set_clock("2026-08-10T08:00:00Z")
        return program, participant, volunteer, assignment

    def test_closeout_lapses_volunteer_with_expired_training(self, api, coordinator_headers):
        """PRD §3.4: "When the daily closeout finds an `ACTIVE` volunteer whose required training record has expired, whose `ACTIVE` agreement has expired, or whose agreement's `policy_version` no longer matches the program's `current_policy_version`, the volunteer moves `ACTIVE` → `LAPSED`; every future-dated `SCHEDULED` assignment of theirs is cancelled with `cancel_reason` `VOLUNTEER_LAPSED`, and each such cancellation marks the affected participant `coverage_deficient` (§3.5)."

        Design: Difficulty/transitive_cascade/training_lapse_closeout_cascade
        """
        program, participant, volunteer, assignment = self._setup_lapse_scenario(
            api, coordinator_headers
        )
        closeout = validate_success(api.daily_closeout(program["id"], coordinator_headers))
        assert volunteer["id"] in closeout["lapsed_volunteer_ids"]
        records = validate_success(
            api.list_training_records(volunteer["id"], coordinator_headers,
                                      params={"module": "SAFETY_PROTOCOL"})
        )
        assert records[0]["status"] == "EXPIRED", (
            "clock 2026-08-10 is strictly past valid_until 2026-08-05"
        )
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["status"] == "LAPSED"

    def test_lapse_cancels_future_assignment_and_marks_coverage(self, api, coordinator_headers):
        """PRD §3.4: "every future-dated `SCHEDULED` assignment of theirs is cancelled with `cancel_reason` `VOLUNTEER_LAPSED`, and each such cancellation marks the affected participant `coverage_deficient` (§3.5)."
        PRD §3.5: "`coverage_deficient` turns true when the planned level falls below the required level, or when a future-dated `SCHEDULED` assignment was cancelled without replacement."

        Design: Difficulty/transitive_cascade/training_lapse_closeout_cascade
        """
        program, participant, volunteer, assignment = self._setup_lapse_scenario(
            api, coordinator_headers
        )
        validate_success(api.daily_closeout(program["id"], coordinator_headers))
        cancelled = get_assignment(assignment["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "VOLUNTEER_LAPSED"
        after = validate_success(api.get_participant(participant["id"], coordinator_headers))
        assert after["coverage_deficient"] is True, (
            "future coverage was removed without replacement"
        )
