"""Read ingest: phase gate, classification, dedupe, append-only shape, the
course-cut pace floor, and the publish-time missing-split sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_timing_read,
    build_race,
    create_timing_read_payload,
    get_result_for_registration,
    ingest_reads,
    list_flags,
    publish_race,
    start_waves,
    validate_error,
    validate_paginated,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
OP = TEST_USERS["timing_operator_headers"]
CLERK = TEST_USERS["registration_clerk_headers"]

SF_POINTS_5K = [
    {"key": "start", "point_index": 1, "kind": "START", "distance_km": 0.0},
    {"key": "finish", "point_index": 2, "kind": "FINISH", "distance_km": 5.0},
]
WAVE_7AM = {"key": "w1", "wave_index": 1,
            "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 10}


class TestIngestPhaseGate:
    def test_read_ingest_closed_phase_rejected(self, api):
        """PRD §3.5: "Ingest is gated on the race being in `IN_PROGRESS`,
        `PROVISIONAL_PUBLISHED`, or `AMENDMENT_OPEN` — late reads remain
        admissible while results are provisional — and this gate is evaluated
        before deduplication: outside those three states, ingest fails with
        `ERR_READ_INGEST_CLOSED`."

        Design: Corner/state_machines/read_ingest_closed_phase_rejected
        """
        ctx = build_race(
            name="Closed 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=[{"key": "start", "point_index": 1, "kind": "START",
                     "distance_km": 0.0}],
            waves=(), chips=[{"key": "c1", "chip_code": "CHIP-Z1"}],
            registrations=(), lock=False)
        resp = api.create_timing_read(
            create_timing_read_payload(ctx["points"]["start"]["id"],
                                       ctx["chips"]["c1"]["id"],
                                       "2026-08-01T07:00:05.000Z"),
            OP)
        validate_error(resp, ApiErrorId.ERR_READ_INGEST_CLOSED, expected_status=409)


class TestIngestClassification:
    def test_read_rejected_for_unassigned_chip(self, api):
        """PRD §3.5: "A read becomes `SCORED` when its chip is currently
        assigned to a `CHECKED_IN` registration of the same race as the timing
        point; otherwise it becomes `REJECTED` with `reject_reason` set to
        `CHIP_NOT_CHECKED_IN`."

        Design: Corner/state_machines/read_rejected_for_unassigned_chip
        """
        ctx = build_race(
            name="Reject 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=SF_POINTS_5K, waves=[WAVE_7AM],
            chips=[{"key": "ua", "chip_code": "CHIP-UA"}],
            registrations=(), lock=True)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})

        read = validate_success(api.create_timing_read(
            create_timing_read_payload(ctx["points"]["start"]["id"],
                                       ctx["chips"]["ua"]["id"],
                                       "2026-08-01T07:00:05.000Z"),
            OP), 201)
        assert read["status"] == "REJECTED"
        assert read["reject_reason"] == "CHIP_NOT_CHECKED_IN"

    def test_duplicate_read_rejected(self, api):
        """PRD §3.5: "An exact duplicate, meaning the same point, chip, and
        timestamp already present on the log, fails with `ERR_DUPLICATE_READ`."

        Design: Corner/state_machines/duplicate_read_rejected
        """
        ctx = build_race(
            name="Dup 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=SF_POINTS_5K, waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-DP"}],
            registrations=[{"key": "r1", "wave": "w1", "bib_number": "740",
                            "participant_name": "D Upe", "birth_date": "1990-01-01",
                            "gender": "M", "chip": "c1"}],
            lock=True)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [{"point": "start", "chip": "c1",
                            "ts": "2026-08-01T07:00:05.000Z"}])

        resp = api.create_timing_read(
            create_timing_read_payload(ctx["points"]["start"]["id"],
                                       ctx["chips"]["c1"]["id"],
                                       "2026-08-01T07:00:05.000Z"),
            OP)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_READ, expected_status=409)
        _data, meta = validate_paginated(api.list_timing_reads(
            OP, params={"chip_id": ctx["chips"]["c1"]["id"]}))
        assert meta["total_count"] == 1, "the log stays append-only with one row"

    def test_timing_read_immutable_no_version(self, api):
        """PRD §2.5: "The **TimingRead** log is append-only: a read carries only
        `id` and `created_at`; both `updated_at` and `version` are absent."
        PRD §3.5: "at ingest both `reject_reason` and `adjusted_by_correction_id`
        are null unless classification sets the former."

        Design: Corner/entities/timing_read_immutable_no_version
        """
        ctx = build_race(
            name="Immutable 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=SF_POINTS_5K, waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-IM"}],
            registrations=[{"key": "r1", "wave": "w1", "bib_number": "810",
                            "participant_name": "Imm Utable",
                            "birth_date": "1990-01-01", "gender": "M", "chip": "c1"}],
            lock=True)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [{"point": "start", "chip": "c1",
                            "ts": "2026-08-01T07:00:05.000Z", "key": "r"}])

        read = validate_success(
            api.get_timing_read(ctx["reads"]["r"]["id"], OP), 200)
        assert_timing_read(read)  # includes: no updated_at, no version keys
        assert read["status"] == "SCORED"
        assert read["reject_reason"] is None
        assert read["adjusted_by_correction_id"] is None


class TestCourseCutFloorBoundary:
    def _boundary_scenario(self, api):
        ctx = build_race(
            name="Boundary 5K", distance_km=5.0, course_type="CERTIFIED_COURSE",
            cutoff_minutes=90, points=SF_POINTS_5K, waves=[WAVE_7AM],
            chips=[{"key": "cc", "chip_code": "CHIP-C"},
                   {"key": "cd", "chip_code": "CHIP-D"}],
            registrations=[
                {"key": "rc", "wave": "w1", "bib_number": "211",
                 "participant_name": "Runner C", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "cc"},
                {"key": "rd", "wave": "w1", "bib_number": "212",
                 "participant_name": "Runner D", "birth_date": "1991-01-01",
                 "gender": "M", "chip": "cd"},
            ],
            lock=True)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "cc", "ts": "2026-08-01T07:00:10.000Z"},
            {"point": "start", "chip": "cd", "ts": "2026-08-01T07:00:10.000Z"},
        ])
        return ctx

    def test_elapsed_exactly_at_floor_raises_no_flag(self, api):
        """PRD §3.5: "the elapsed time between the start read and this read is
        compared against a floor: the point's `distance_km` multiplied by a
        minimum pace of two minutes per kilometer, expressed in milliseconds. An
        elapsed time strictly below the floor is physically implausible and
        raises an automatic `COURSE_CUT_SUSPECT` flag in `RAISED` state with
        `origin` `AUTO`; an elapsed time exactly equal to the floor raises
        nothing."

        Design: Difficulty/boundary_precision_check/course_cut_floor_exact_equality
        """
        ctx = self._boundary_scenario(api)
        # 5.0 km x 120 s/km x 1000 = 600000 ms; C finishes in exactly 600000 ms.
        finish_read = validate_success(api.create_timing_read(
            create_timing_read_payload(ctx["points"]["finish"]["id"],
                                       ctx["chips"]["cc"]["id"],
                                       "2026-08-01T07:10:10.000Z"),
            OP), 201)
        assert finish_read["status"] == "SCORED"
        flags, meta = list_flags(ctx["regs"]["rc"]["id"])
        assert meta["total_count"] == 0, "elapsed == floor raises nothing"

    def test_elapsed_one_ms_below_floor_raises_flag(self, api):
        """PRD §3.5: "the elapsed time between the start read and this read is
        compared against a floor: the point's `distance_km` multiplied by a
        minimum pace of two minutes per kilometer, expressed in milliseconds. An
        elapsed time strictly below the floor is physically implausible and
        raises an automatic `COURSE_CUT_SUSPECT` flag in `RAISED` state with
        `origin` `AUTO`; an elapsed time exactly equal to the floor raises
        nothing."

        Design: Difficulty/boundary_precision_check/course_cut_floor_exact_equality
        """
        ctx = self._boundary_scenario(api)
        # D finishes in 599999 ms — one millisecond under the 600000 ms floor.
        validate_success(api.create_timing_read(
            create_timing_read_payload(ctx["points"]["finish"]["id"],
                                       ctx["chips"]["cd"]["id"],
                                       "2026-08-01T07:10:09.999Z"),
            OP), 201)
        flags, meta = list_flags(ctx["regs"]["rd"]["id"])
        assert meta["total_count"] == 1
        assert flags[0]["flag_type"] == "COURSE_CUT_SUSPECT"
        assert flags[0]["status"] == "RAISED"
        assert flags[0]["origin"] == "AUTO"


class TestMissingSplitSweep:
    def test_missing_split_sweep_raises_flag(self, api):
        """PRD §3.6: "The missing-split sweep then examines each `CHECKED_IN`
        athlete's progress: taking the furthest timing point, by `point_index`,
        at which the athlete has a `SCORED` read, any `SPLIT` point before it
        without a `SCORED` read for that athlete raises an automatic
        `COURSE_CUT_SUSPECT`."
        PRD §3.6: "These flags are raised, not confirmed — they exclude nobody
        until a `RaceOfficial` confirms them (§3.7), because the exclusion phase
        honors only `CONFIRMED` flags."

        Design: Corner/calculations/missing_split_sweep_raises_flag
        """
        ctx = build_race(
            name="Sweep 10K", distance_km=10.0, course_type="CERTIFIED_COURSE",
            cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "split5", "point_index": 2, "kind": "SPLIT",
                 "distance_km": 5.0},
                {"key": "finish", "point_index": 3, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-MS"}],
            registrations=[{"key": "r1", "wave": "w1", "bib_number": "820",
                            "participant_name": "M Sweep", "birth_date": "1990-01-01",
                            "gender": "M", "chip": "c1"}],
            lock=True)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        # START + FINISH only: the SPLIT at point_index 2 is skipped entirely.
        ingest_reads(ctx, [
            {"point": "start", "chip": "c1", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "c1", "ts": "2026-08-01T07:40:05.000Z"},
        ])
        publish_race(ctx, "2026-08-01T09:00:00Z")

        flags, meta = list_flags(ctx["regs"]["r1"]["id"])
        assert meta["total_count"] == 1
        assert flags[0]["flag_type"] == "COURSE_CUT_SUSPECT"
        assert flags[0]["origin"] == "AUTO"
        assert flags[0]["status"] == "RAISED"

        result = get_result_for_registration(ctx["regs"]["r1"]["id"])
        assert result is not None
        assert result["status"] == "PROVISIONAL", "a RAISED flag excludes nobody"
        assert result["completed_splits"] == 0
        assert result["chip_time_ms"] == 2400000
