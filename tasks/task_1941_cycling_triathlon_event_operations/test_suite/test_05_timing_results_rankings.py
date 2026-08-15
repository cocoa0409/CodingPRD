"""Chip timing, result replay, rankings, and result corrections."""
from test_helpers import (
    STANDARD_SPLITS,
    ApiErrorId,
    assert_version_incremented,
    check_in_bike,
    create_confirmed_registration,
    create_published_event,
    create_safety_assessment_payload,
    create_timing_record_payload,
    get_result_of,
    get_success_data,
    make_athlete_headers,
    make_race_director_headers,
    record_and_validate_splits,
    setup_finished_race,
    setup_finalized_event,
    setup_live_race,
    TEST_USERS,
    validate_error,
    validate_success,
)

TIMER = TEST_USERS["timer_headers"]
RD = TEST_USERS["race_director_headers"]


class TestSplitReplay:
    def test_split_replay_excludes_unvalidated_records(self, api):
        """PRD §3.6: "Every validation or invalidation replays the athlete's
        result from scratch: the projection walks the registration's
        `VALIDATED` records in `recorded_at` ascending order — `RECORDED` and
        `INVALIDATED` records never enter the computation — and measures each
        split against the wave's `actual_start_time`."
        PRD §3.6: "A split whose leg has no `VALIDATED` record stays null, and
        `provisional_total_seconds` — the sum of the five splits, excluding
        all penalties, even confirmed ones — remains null until a `FINISH`
        record is validated."

        Design: Corner/calculations/split_replay_excludes_unvalidated_records
        """
        ctx = setup_live_race(num_athletes=1)
        registration = ctx["registrations"][0]

        swim = get_success_data(api.create_timing_record(
            registration["id"],
            create_timing_record_payload(discipline="SWIM",
                                         recorded_at="2026-10-15T08:15:00Z"),
            TIMER))
        get_success_data(api.validate_timing_record(swim["id"], TIMER))
        bike = get_success_data(api.create_timing_record(
            registration["id"],
            create_timing_record_payload(discipline="BIKE",
                                         recorded_at="2026-10-15T09:16:00Z"),
            TIMER))
        # BIKE left RECORDED (never validated).

        result = get_result_of(registration["id"])
        assert result["swim_seconds"] == 900, "08:15:00 - 08:00:00 = 900"
        assert result["bike_seconds"] is None, \
            "a RECORDED (never validated) read never enters the replay"
        assert result["provisional_total_seconds"] is None, \
            "no FINISH validated yet"

        get_success_data(api.invalidate_timing_record(swim["id"], TIMER))
        replayed = get_result_of(registration["id"])
        assert replayed["swim_seconds"] is None, \
            "after invalidation the SWIM split reverts to null"

    def test_finish_validate_then_invalidate_reverts_to_racing(self, api):
        """PRD §3.6: "When a `FINISH` record becomes `VALIDATED`, the
        registration moves from `RACING` to `FINISHED`, the result's
        `finish_timestamp` takes the record's `recorded_at`, the provisional
        total is computed, and division ranks are recomputed. Conversely,
        invalidating a `FINISH` record while the registration is `FINISHED`
        reverts it to `RACING` and returns the provisional totals to null."

        Design: Corner/state_machines/finish_invalidate_reverts_to_racing
        """
        ctx = setup_finished_race()
        registration = ctx["registrations"][0]
        finish_record = ctx["records"][-1]
        assert finish_record["discipline"] == "FINISH"
        assert registration["status"] == "FINISHED"
        finished_result = get_result_of(registration["id"])
        assert finished_result["provisional_total_seconds"] == 6390
        assert finished_result["finish_timestamp"] == "2026-10-15T09:46:30Z"

        get_success_data(api.invalidate_timing_record(finish_record["id"], TIMER))
        reverted = validate_success(api.get_registration(registration["id"], RD))
        assert reverted["status"] == "RACING", \
            "invalidating the FINISH read reverts FINISHED to RACING"
        result = get_result_of(registration["id"])
        assert result["provisional_total_seconds"] is None
        assert result["finish_timestamp"] is None

    def test_validate_from_invalidated_rejected(self, api):
        """PRD §3.6: "invalidating moves a `RECORDED` or `VALIDATED` record to
        `INVALIDATED`, which is terminal."
        PRD §2.10: "then state-machine from-state validity
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/timing_validate_from_invalidated_rejected
        """
        ctx = setup_live_race(num_athletes=1)
        registration = ctx["registrations"][0]
        record = get_success_data(api.create_timing_record(
            registration["id"],
            create_timing_record_payload(discipline="SWIM",
                                         recorded_at="2026-10-15T08:15:00Z"),
            TIMER))
        get_success_data(api.invalidate_timing_record(record["id"], TIMER))

        resp = api.validate_timing_record(record["id"], TIMER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_timing_record(record["id"], TIMER))
        assert after["status"] == "INVALIDATED"


class TestSwimCancellationCascade:
    def test_swim_cancel_cascade_recomputes_results(self, api):
        """PRD §3.5: "Any transition into `SWIM_CANCELLED` recomputes every
        existing result of the event under the duathlon variant described in
        §3.6 — `swim_seconds` and `t1_seconds` become zero and the bike split
        is measured from the wave's `actual_start_time` — and recomputes
        division ranks."
        PRD §3.6: "Under the duathlon variant (swim cancelled), `swim_seconds`
        and `t1_seconds` are zero, `bike_seconds` runs from the wave's
        `actual_start_time` to the `BIKE` read, and `t2_seconds` and
        `run_seconds` are measured as in the standard variant."

        Design: Difficulty/transitive_cascade/swim_cancel_cascade_depth3
        """
        ctx = setup_finished_race()  # one FINISHED athlete, provisional 6390
        event_id = ctx["event"]["id"]
        registration = ctx["registrations"][0]

        get_success_data(api.create_safety_assessment(
            event_id,
            create_safety_assessment_payload(water_temp_celsius=10.0),
            RD))
        event = validate_success(api.get_event(event_id, RD))
        assert event["swim_status"] == "SWIM_CANCELLED", \
            "link 1: the assessment flipped the event's swim dimension"

        result = get_result_of(registration["id"])
        assert result["swim_seconds"] == 0, "link 2: duathlon zeroes the swim"
        assert result["t1_seconds"] == 0
        assert result["bike_seconds"] == 4560, \
            "link 2: bike measured from actual_start_time 08:00 to 09:16"
        assert result["t2_seconds"] == 30
        assert result["run_seconds"] == 1800
        assert result["provisional_total_seconds"] == 6390, \
            "link 2 output: 0+0+4560+30+1800"

    def test_swim_cancel_cascade_recomputes_division_rank(self, api):
        """PRD §3.5: "Any transition into `SWIM_CANCELLED` recomputes every
        existing result of the event under the duathlon variant described in
        §3.6 — `swim_seconds` and `t1_seconds` become zero and the bike split
        is measured from the wave's `actual_start_time` — and recomputes
        division ranks."
        PRD §3.6: "within each `division`, `division_rank` is the 1-based
        position by `effective_total_seconds` ascending over results whose
        registrations are not `DSQ` and whose effective totals are non-null".

        Design: Difficulty/transitive_cascade/swim_cancel_cascade_depth3
        """
        # Two finishers: R1 slower duathlon total, R2 faster. The cancellation
        # re-bases the bike split on actual_start_time, changing both totals
        # and with them the rank order.
        ctx = create_published_event(wave_overrides=[{"capacity": 4}],
                                     has_swim=True, water_pool_units=1000)
        event_id = ctx["event"]["id"]
        a1, r1 = create_confirmed_registration(event_id, license_number="USAT-1")
        a2, r2 = create_confirmed_registration(
            event_id, full_name="Bob B", birth_date="1992-05-05",
            license_number="USAT-2")
        get_success_data(api.create_safety_assessment(
            event_id, create_safety_assessment_payload(water_temp_celsius=20.0),
            RD))
        check_in_bike(r1, a1, bib_code="BIB-1")
        check_in_bike(r2, a2, bib_code="BIB-2")
        get_success_data(api.set_clock("2026-10-15T08:00:00Z", RD))
        get_success_data(api.start_event(event_id, RD))

        # Standard-variant totals: R1 = 6390, R2 = 6075 (R2 ahead).
        record_and_validate_splits(r1["id"], STANDARD_SPLITS)
        record_and_validate_splits(r2["id"], [
            ("SWIM", "2026-10-15T08:13:20Z"),   # 800
            ("T1", "2026-10-15T08:14:10Z"),     # 50
            ("BIKE", "2026-10-15T09:12:30Z"),   # 3500
            ("T2", "2026-10-15T09:12:55Z"),     # 25
            ("FINISH", "2026-10-15T09:41:15Z"), # 1700 -> 6075
        ])
        assert get_result_of(r1["id"])["division_rank"] == 2
        assert get_result_of(r2["id"])["division_rank"] == 1

        # Cancel the swim: duathlon re-bases bike on the 08:00 start.
        get_success_data(api.create_safety_assessment(
            event_id,
            create_safety_assessment_payload(water_temp_celsius=10.0),
            RD))
        r1_result = get_result_of(r1["id"])
        r2_result = get_result_of(r2["id"])
        # R1: 0+0+4560+30+1800 = 6390; R2: 0+0+4350+25+1700 = 6075
        # (R2 bike: 09:12:30 - 08:00:00 = 4350s).
        assert r1_result["provisional_total_seconds"] == 6390
        assert r2_result["provisional_total_seconds"] == 6075
        assert r2_result["division_rank"] == 1, \
            "link 3: ranks recomputed over the cascaded totals"
        assert r1_result["division_rank"] == 2


class TestProvisionalVsOfficialTotals:
    def test_provisional_excludes_confirmed_penalty(self, api):
        """PRD §3.6: "`provisional_total_seconds` — the sum of the five
        splits, excluding all penalties, even confirmed ones — remains null
        until a `FINISH` record is validated."
        PRD §3.7: "It moves every result to `OFFICIAL`, sets each
        `official_total_seconds` to the provisional total plus
        `penalty_seconds_total`".

        Design: Difficulty/dual_variant_calc/result_total_provisional_excludes_confirmed_penalty
        """
        ctx = setup_finished_race()
        event_id = ctx["event"]["id"]
        registration = ctx["registrations"][0]
        # DRAFTING penalty assessed at the 08:00 race clock (120s, 0 priors);
        # default 60-minute appeal window expires 09:00.
        from test_helpers import assess_penalty
        penalty = assess_penalty(registration["id"], kind="DRAFTING",
                                 referee_id="ref-1")
        assert penalty["seconds"] == 120
        # Auto-confirm past the window, before finalize.
        get_success_data(api.set_clock("2026-10-15T09:00:00Z", RD))
        get_success_data(api.run_ops(event_id, RD))
        confirmed = validate_success(api.get_penalty(penalty["id"], RD))
        assert confirmed["status"] == "CONFIRMED"

        result = get_result_of(registration["id"])
        assert result["status"] == "PROVISIONAL"
        assert result["provisional_total_seconds"] == 6390, \
            "900+60+3600+30+1800; the CONFIRMED penalty is excluded"
        assert result["penalty_seconds_total"] == 120
        assert result["effective_total_seconds"] == 6390, \
            "while PROVISIONAL the effective total is the provisional total"

    def test_official_includes_confirmed_penalty(self, api):
        """PRD §3.6: "`official_total_seconds`, populated only while the
        result is `OFFICIAL`, is the provisional total plus
        `penalty_seconds_total`; for identical split data the two totals
        differ whenever a confirmed penalty exists."

        Design: Difficulty/dual_variant_calc/result_total_provisional_excludes_confirmed_penalty
        """
        ctx = setup_finished_race()
        event_id = ctx["event"]["id"]
        registration = ctx["registrations"][0]
        from test_helpers import assess_penalty
        assess_penalty(registration["id"], kind="DRAFTING", referee_id="ref-1")
        get_success_data(api.set_clock("2026-10-15T09:00:00Z", RD))
        get_success_data(api.run_ops(event_id, RD))
        get_success_data(api.finalize_event(event_id, RD))

        result = get_result_of(registration["id"])
        assert result["status"] == "OFFICIAL"
        assert result["provisional_total_seconds"] == 6390
        assert result["penalty_seconds_total"] == 120
        assert result["official_total_seconds"] == 6510, \
            "6390 + 120: the OFFICIAL variant includes the confirmed penalty"
        assert result["effective_total_seconds"] == 6510
        assert result["provisional_total_seconds"] != result["official_total_seconds"], \
            "identical timing data, two totals, split by the confirmed penalty"


class TestResultCorrections:
    def test_stale_result_version_occ(self, api):
        """PRD §2.8: "Correcting an official result (the `POST
        /results/{id}/corrections` capability) requires
        `expected_result_version`, carrying the version of the Result the
        client last observed; a mismatch with the Result's current `version`
        is rejected with `ERR_STALE_RESULT_VERSION` (HTTP 412)."
        PRD §3.6: "A successful correction replaces the named split,
        recomputes both the provisional and official totals and the division
        ranks, leaves the result `OFFICIAL`, and increments the result's
        `version` by one."

        Design: Corner/errors/error_stale_result_version_occ
        """
        ctx = setup_finalized_event()
        registration = ctx["registrations"][0]
        result = get_result_of(registration["id"])
        assert result["status"] == "OFFICIAL"
        assert result["official_total_seconds"] == 6390, \
            "no penalties: official equals provisional"
        observed_version = result["version"]

        corrected = validate_success(api.correct_result(
            result["id"],
            {"expected_result_version": observed_version,
             "discipline": "BIKE", "corrected_seconds": 3500},
            TIMER))
        assert_version_incremented(corrected["version"], observed_version)
        assert corrected["bike_seconds"] == 3500
        assert corrected["official_total_seconds"] == 6290, \
            "6390 - 100 after BIKE corrected 3600 -> 3500"
        assert corrected["status"] == "OFFICIAL"

        stale = api.correct_result(
            result["id"],
            {"expected_result_version": observed_version,
             "discipline": "RUN", "corrected_seconds": 1700},
            TIMER)
        validate_error(stale, ApiErrorId.ERR_STALE_RESULT_VERSION.value)

        after = validate_success(api.get_result(result["id"], TIMER))
        assert after["bike_seconds"] == 3500
        assert after["run_seconds"] == 1800, "stale correction did not apply"

    def test_correction_on_provisional_result_rejected(self, api):
        """PRD §3.6: "The correction applies only to an `OFFICIAL` result —
        attempting it against a result in any other state is rejected with
        `ERR_INVALID_STATE` — and provisional results are corrected implicitly
        through timing-record validation and invalidation rather than through
        this capability."

        Design: Corner/errors/error_stale_result_version_occ
        """
        ctx = setup_finished_race()  # PROVISIONAL (not yet finalized)
        registration = ctx["registrations"][0]
        result = get_result_of(registration["id"])
        assert result["status"] == "PROVISIONAL"
        resp = api.correct_result(
            result["id"],
            {"expected_result_version": result["version"],
             "discipline": "BIKE", "corrected_seconds": 3500},
            TIMER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
