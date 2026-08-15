"""Publication: time derivation, gun vs chip rankings, tie-breaks, rank
compaction, qualifying standard, the race cutoff, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_award,
    assert_result,
    build_race,
    create_correction_payload,
    find_awards,
    get_race,
    get_result_for_registration,
    ingest_reads,
    parse_iso,
    publish_race,
    race_version,
    set_clock,
    setup_divergence_race,
    start_waves,
    validate_error,
    validate_paginated,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
OP = TEST_USERS["timing_operator_headers"]
CLERK = TEST_USERS["registration_clerk_headers"]
OF = TEST_USERS["race_official_headers"]
SP = TEST_USERS["spectator_headers"]

WAVE_7AM = {"key": "w1", "wave_index": 1,
            "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 100}


class TestGunVsChipAwardDivergence:
    def test_identical_finish_data_ranks_differently_by_basis(self, api):
        """PRD §3.6: "`chip_time_ms` is the difference between the finishing
        anchor and the starting anchor; if either anchor is missing,
        `chip_time_ms` is null. `gun_time_ms` is the difference between the
        finishing anchor and the wave's `actual_start_time`"
        PRD §3.6: "The two rankings legitimately disagree. The gun ranking
        answers who crossed the finish line first on the wave's actual-start
        basis, so a later-wave athlete with a faster `chip_time_ms` still loses
        to an earlier-wave athlete with a faster `gun_time_ms`."

        Design: Difficulty/dual_variant_calc/gun_vs_chip_award_divergence
        """
        ctx = setup_divergence_race()
        res_a = get_result_for_registration(ctx["regs"]["a"]["id"])
        res_b = get_result_for_registration(ctx["regs"]["b"]["id"])
        assert_result(res_a)
        assert_result(res_b)
        assert res_a["chip_time_ms"] == 1920000  # 07:32:05 - 07:00:05
        assert res_a["gun_time_ms"] == 1925000   # 07:32:05 - 07:00:00 (wave 1)
        assert res_b["chip_time_ms"] == 1910000  # 07:42:20 - 07:10:30
        assert res_b["gun_time_ms"] == 1940000   # 07:42:20 - 07:10:00 (wave 2)
        # Gun basis: the earlier-wave athlete A wins despite the slower chip.
        assert res_a["overall_rank_gun"] == 1
        assert res_b["overall_rank_gun"] == 2
        # Chip basis (per gender x age_group): B ran faster mat-to-mat.
        assert res_a["age_group_rank_chip"] == 2
        assert res_b["age_group_rank_chip"] == 1

    def test_divergent_winners_crowned_in_awards_and_not_qualified(self, api):
        """PRD §3.6: "The overall categories are allocated on the `GUN` basis,
        candidates taken in `overall_rank_gun` ascending order; the age-group
        categories on the `CHIP` basis, candidates taken in
        `age_group_rank_chip` ascending order."
        PRD §3.6: "Each award row records its `category`, its `place`, the
        winner's `registration_id`, the `basis`, and the winning time as
        `basis_time_ms` — the winner's `gun_time_ms` under the `GUN` basis or
        `chip_time_ms` under the `CHIP` basis — along with its `race_id`."
        PRD §3.6: "a result is marked `qualified` when the race defines
        `qualifying_standard_ms`, the result is not excluded, and its
        `chip_time_ms` is less than or equal to the standard — the boundary is
        inclusive."

        Design: Difficulty/dual_variant_calc/gun_vs_chip_award_divergence
        """
        ctx = setup_divergence_race()
        race_id = ctx["race"]["id"]

        overall = find_awards(race_id, "OVERALL_M", place=1, status="PROJECTED")
        assert len(overall) == 1
        assert_award(overall[0])
        assert overall[0]["registration_id"] == ctx["regs"]["a"]["id"]
        assert overall[0]["basis"] == "GUN"
        assert overall[0]["basis_time_ms"] == 1925000

        age_group = find_awards(race_id, "AG_M_35_39", place=1, status="PROJECTED")
        assert len(age_group) == 1
        assert age_group[0]["registration_id"] == ctx["regs"]["b"]["id"]
        assert age_group[0]["basis"] == "CHIP"
        assert age_group[0]["basis_time_ms"] == 1910000

        # Both chips (1920000 / 1910000) exceed the 1800000 standard.
        res_a = get_result_for_registration(ctx["regs"]["a"]["id"])
        res_b = get_result_for_registration(ctx["regs"]["b"]["id"])
        assert res_a["qualified"] is False
        assert res_b["qualified"] is False


class TestQualifyingStandardBoundary:
    def test_qualifying_standard_inclusive_boundary(self, api):
        """PRD §3.6: "a result is marked `qualified` when the race defines
        `qualifying_standard_ms`, the result is not excluded, and its
        `chip_time_ms` is less than or equal to the standard — the boundary is
        inclusive."

        Design: Corner/calculations/qualifying_standard_inclusive_boundary
        """
        ctx = build_race(
            name="Qual 10K", distance_km=10.0, cutoff_minutes=120,
            qualifying_standard_ms=1800000,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "cq1", "chip_code": "CHIP-Q1"},
                   {"key": "cq2", "chip_code": "CHIP-Q2"}],
            registrations=[
                {"key": "q1", "wave": "w1", "bib_number": "830",
                 "participant_name": "Q One", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "cq1"},
                {"key": "q2", "wave": "w1", "bib_number": "831",
                 "participant_name": "Q Two", "birth_date": "1991-01-01",
                 "gender": "M", "chip": "cq2"},
            ])
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "cq1", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "cq1", "ts": "2026-08-01T07:30:05.000Z"},
            {"point": "start", "chip": "cq2", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "cq2", "ts": "2026-08-01T07:30:05.001Z"},
        ])
        publish_race(ctx, "2026-08-01T09:00:00Z")

        res_q1 = get_result_for_registration(ctx["regs"]["q1"]["id"])
        res_q2 = get_result_for_registration(ctx["regs"]["q2"]["id"])
        assert res_q1["chip_time_ms"] == 1800000
        assert res_q1["qualified"] is True, "equality qualifies (inclusive boundary)"
        assert res_q2["chip_time_ms"] == 1800001
        assert res_q2["qualified"] is False, "one millisecond over the standard"
        # Rankings are unaffected by the qualifying flag.
        assert res_q1["overall_rank_gun"] == 1
        assert res_q2["overall_rank_gun"] == 2


class TestTieBreak:
    def test_gun_and_chip_tie_broken_by_finish_timestamp(self, api):
        """PRD §3.6: "The gun ranking considers every eligible — that is,
        non-excluded — registration whose `gun_time_ms` is not null, ordered by
        `gun_time_ms` ascending, with ties broken by `finish_timestamp`
        ascending and then by the registration's `created_at` ascending;
        `overall_rank_gun` is assigned 1 through N strictly, forming a gap-free
        sequence. The chip ranking is computed within each pairing of `gender`
        and `age_group` over eligible registrations whose `chip_time_ms` is not
        null, applying the identical tie-break chain to `chip_time_ms`"

        Design: Corner/calculations/gun_and_chip_tie_broken_by_finish_timestamp
        """
        ctx = build_race(
            name="Tie 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[
                {"key": "w1", "wave_index": 1,
                 "scheduled_start_time": "2026-08-01T07:00:00Z",
                 "max_capacity": 10},
                {"key": "w2", "wave_index": 2,
                 "scheduled_start_time": "2026-08-01T07:10:00Z",
                 "max_capacity": 10},
            ],
            chips=[{"key": "ca", "chip_code": "CHIP-TA"},
                   {"key": "cb", "chip_code": "CHIP-TB"}],
            registrations=[
                {"key": "a", "wave": "w1", "bib_number": "840",
                 "participant_name": "Tie A", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "ca"},
                {"key": "b", "wave": "w2", "bib_number": "841",
                 "participant_name": "Tie B", "birth_date": "1991-01-01",
                 "gender": "M", "chip": "cb"},
            ])
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z", "w2": "2026-08-01T07:10:00Z"})
        # Identical chip times (1805000) and identical gun times (1810000).
        ingest_reads(ctx, [
            {"point": "start", "chip": "ca", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "ca", "ts": "2026-08-01T07:30:10.000Z"},
            {"point": "start", "chip": "cb", "ts": "2026-08-01T07:10:05.000Z"},
            {"point": "finish", "chip": "cb", "ts": "2026-08-01T07:40:10.000Z"},
        ])
        publish_race(ctx, "2026-08-01T09:00:00Z")

        res_a = get_result_for_registration(ctx["regs"]["a"]["id"])
        res_b = get_result_for_registration(ctx["regs"]["b"]["id"])
        assert res_a["chip_time_ms"] == 1805000
        assert res_b["chip_time_ms"] == 1805000
        assert res_a["gun_time_ms"] == 1810000
        assert res_b["gun_time_ms"] == 1810000
        # A's finish_timestamp (07:30:10) is earlier than B's (07:40:10).
        assert res_a["overall_rank_gun"] == 1
        assert res_b["overall_rank_gun"] == 2
        assert res_a["age_group_rank_chip"] == 1
        assert res_b["age_group_rank_chip"] == 2


class TestRankCompaction:
    def test_rank_compaction_after_exclusion(self, api):
        """PRD §3.6: "`overall_rank_gun` is assigned 1 through N strictly,
        forming a gap-free sequence."
        PRD §3.7: "A confirmation while the race is `PROVISIONAL_PUBLISHED` or
        `AMENDMENT_OPEN` triggers the flag cascade: the subject's result —
        whether `PROVISIONAL` or `OFFICIAL` — moves to `EXCLUDED`, its
        `exclusion_reason` takes the flag's `flag_type`, its ranks are nulled,
        and ranks and awards across the race are recomputed."

        Design: Corner/calculations/rank_compaction_after_exclusion
        """
        ctx = build_race(
            name="Compact 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-C1"},
                   {"key": "c2", "chip_code": "CHIP-C2"},
                   {"key": "c3", "chip_code": "CHIP-C3"}],
            registrations=[
                {"key": "r1", "wave": "w1", "bib_number": "850",
                 "participant_name": "C One", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "c1"},
                {"key": "r2", "wave": "w1", "bib_number": "851",
                 "participant_name": "C Two", "birth_date": "1991-01-01",
                 "gender": "M", "chip": "c2"},
                {"key": "r3", "wave": "w1", "bib_number": "852",
                 "participant_name": "C Three", "birth_date": "1992-01-01",
                 "gender": "M", "chip": "c3"},
            ])
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "c1", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "c1", "ts": "2026-08-01T07:28:25.000Z"},
            {"point": "start", "chip": "c2", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "c2", "ts": "2026-08-01T07:30:05.000Z"},
            {"point": "start", "chip": "c3", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "c3", "ts": "2026-08-01T07:31:45.000Z"},
        ])
        publish_race(ctx, "2026-08-01T09:00:00Z")

        flag = validate_success(api.create_result_flag(
            {"registration_id": ctx["regs"]["r2"]["id"], "flag_type": "DQ",
             "detail": "cut barrier"}, OF), 201)
        validate_success(api.resolve_result_flag(flag["id"], "CONFIRMED", OF), 200)

        res_c1 = get_result_for_registration(ctx["regs"]["r1"]["id"])
        res_c2 = get_result_for_registration(ctx["regs"]["r2"]["id"])
        res_c3 = get_result_for_registration(ctx["regs"]["r3"]["id"])
        assert res_c1["overall_rank_gun"] == 1
        assert res_c2["status"] == "EXCLUDED"
        assert res_c2["exclusion_reason"] == "DQ"
        assert res_c2["overall_rank_gun"] is None
        # The slowest finisher compacts into rank 2 — no gap is left behind.
        assert res_c3["overall_rank_gun"] == 2


class TestResultInputSet:
    def test_withdrawn_registration_not_in_result_set(self, api):
        """PRD §3.6: "On first publication, a **Result** row is created
        `PROVISIONAL` for every `CHECKED_IN` registration"

        Design: Corner/calculations/withdrawn_registration_not_in_result_set
        """
        ctx = build_race(
            name="Filter 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-FL"}],
            registrations=[
                {"key": "rin", "wave": "w1", "bib_number": "860",
                 "participant_name": "F In", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "c1"},
                {"key": "rout", "wave": "w1", "bib_number": "861",
                 "participant_name": "F Out", "birth_date": "1991-01-01",
                 "gender": "M", "pay": False, "confirm": False},
            ])
        # Withdrawal is still permitted while the race is TIMING_LOCKED.
        validate_success(
            api.withdraw_registration(ctx["regs"]["rout"]["id"], CLERK), 200)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "c1", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "c1", "ts": "2026-08-01T07:30:05.000Z"},
        ])
        publish_race(ctx, "2026-08-01T09:00:00Z")

        data, meta = validate_paginated(api.list_results(
            OF, params={"registration_id": ctx["regs"]["rout"]["id"]}))
        assert meta["total_count"] == 0, "WITHDRAWN athletes produce no Result row"
        res_in = get_result_for_registration(ctx["regs"]["rin"]["id"])
        assert res_in is not None
        assert res_in["overall_rank_gun"] == 1


class TestPublishCutoff:
    def test_publish_before_cutoff_rejected(self, api):
        """PRD §3.6: "The cutoff requires the logical now to have reached the
        earliest `actual_start_time` among the started waves plus
        `course_time_limit_minutes`; the boundary is inclusive, so a publish
        attempted earlier fails with `ERR_RACE_CUTOFF_NOT_REACHED` while a
        publish at exactly the cutoff proceeds."

        Design: Corner/state_machines/publish_before_cutoff_rejected
        """
        ctx = build_race(
            name="Cutoff 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM], chips=(), registrations=())
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        # One second before 07:00:00 + 120 minutes.
        set_clock("2026-08-01T08:59:59Z")
        version = race_version(ctx)
        resp = api.publish_results(ctx["race"]["id"], version, RD)
        validate_error(resp, ApiErrorId.ERR_RACE_CUTOFF_NOT_REACHED,
                       expected_status=409)
        race = get_race(ctx)
        assert race["status"] == "IN_PROGRESS"


class TestReverseReferences:
    def test_fk_reverse_lists_resolve(self, api):
        """PRD §3.2: "The registration addressed by `reg_id` can be read back at
        any time, and the registration listing can be filtered by `race_id`,
        `wave_id`, `chip_id`, `lifecycle_status`, or `bib_number`."
        PRD §3.5: "the read addressed by `read_id` can be fetched directly or
        listed with filters on `timing_point_id`, `chip_id`, `status`, or
        `adjusted_by_correction_id`."

        Design: Corner/endpoints/fk_reverse_lists_resolve
        """
        ctx = build_race(
            name="Reverse 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 5.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-RK"}],
            registrations=[{"key": "r1", "wave": "w1", "bib_number": "910",
                            "participant_name": "R Kay", "birth_date": "1990-01-01",
                            "gender": "M", "chip": "c1"}])
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [{"point": "start", "chip": "c1",
                            "ts": "2026-08-01T07:00:05.000Z", "key": "r"}])

        race_id = ctx["race"]["id"]
        waves, waves_meta = validate_paginated(api.list_race_waves(race_id, RD))
        assert waves_meta["total_count"] == 1
        assert waves[0]["id"] == ctx["waves"]["w1"]["id"]
        points, points_meta = validate_paginated(
            api.list_race_timing_points(race_id, RD))
        assert points_meta["total_count"] == 2

        regs, regs_meta = validate_paginated(api.list_registrations(
            CLERK, params={"chip_id": ctx["chips"]["c1"]["id"]}))
        assert regs_meta["total_count"] == 1
        assert regs[0]["id"] == ctx["regs"]["r1"]["id"]

        reads, reads_meta = validate_paginated(api.list_timing_reads(
            OP, params={"chip_id": ctx["chips"]["c1"]["id"]}))
        assert reads_meta["total_count"] == 1
        assert reads[0]["id"] == ctx["reads"]["r"]["id"]
        assert reads[0]["status"] == "SCORED"


class TestSpectatorReads:
    def test_spectator_read_access_allowed(self, api):
        """PRD §2.1: "A `Spectator` is a public viewer with read-only access to
        race detail, the live board, results, awards, and certifications."
        PRD §3.9: "The board answers with an `entries` array and a
        `generated_at` stamp taken from the logical clock"

        Design: Corner/rbac/spectator_read_access_allowed
        """
        ctx = build_race(
            name="Public 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 5.0},
            ],
            waves=[WAVE_7AM], chips=(), registrations=())
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        race_id = ctx["race"]["id"]

        race = validate_success(api.get_race(race_id, SP), 200)
        assert race["status"] == "IN_PROGRESS"
        board = validate_success(api.get_live_board(race_id, SP), 200)
        assert board["entries"] == []
        assert parse_iso(board["generated_at"]) == parse_iso("2026-08-01T07:00:00Z")
        results, results_meta = validate_paginated(
            api.list_results(SP, params={"race_id": race_id}))
        assert results_meta["total_count"] == 0
        _awards, awards_meta = validate_paginated(api.list_race_awards(race_id, SP))
        assert awards_meta["total_count"] == 0


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected_412(self, api):
        """PRD §2.8: "If the race's current `version` has advanced beyond that
        observed value — for example because a correction was adjudicated, or
        results were published, since the client's last read — the request is
        rejected with `ERR_STALE_RACE_VERSION` (HTTP 412), preventing the client
        from acting on a view of the race it has not observed."
        PRD §3.6: "The race moves to `PROVISIONAL_PUBLISHED`, and its `version`
        increments by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_412
        """
        ctx = build_race(
            name="OCC 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-OC"}],
            registrations=[{"key": "r1", "wave": "w1", "bib_number": "920",
                            "participant_name": "O Cee", "birth_date": "1990-01-01",
                            "gender": "M", "chip": "c1"}])
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "c1", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "c1", "ts": "2026-08-01T07:30:05.000Z",
             "key": "fin"},
        ])
        set_clock("2026-08-01T09:00:00Z")
        race_v = race_version(ctx)
        race_id = ctx["race"]["id"]

        # Stale publish: the observed-minus-one version is rejected.
        resp1 = api.publish_results(race_id, race_v - 1, RD)
        validate_error(resp1, ApiErrorId.ERR_STALE_RACE_VERSION, expected_status=412)

        # Fresh publish succeeds and advances the version by exactly one.
        published = validate_success(api.publish_results(race_id, race_v, RD), 200)
        assert published["status"] == "PROVISIONAL_PUBLISHED"
        assert published["version"] == race_v + 1

        corr = validate_success(api.create_correction(
            create_correction_payload(race_id, ctx["reads"]["fin"]["id"],
                                      "ADJUST_READ_TIME", "occ probe",
                                      corrected_timestamp="2026-08-01T07:30:06.000Z"),
            OF), 201)

        # Stale adjudicate: the pre-publish version is no longer current.
        resp2 = api.adjudicate_correction(corr["id"], "APPROVED", race_v, OF)
        validate_error(resp2, ApiErrorId.ERR_STALE_RACE_VERSION, expected_status=412)

        # Fresh adjudicate with the post-publish version succeeds.
        approved = validate_success(
            api.adjudicate_correction(corr["id"], "APPROVED", race_v + 1, OF), 200)
        assert approved["status"] == "APPROVED"
        race = get_race(ctx)
        assert race["status"] == "AMENDMENT_OPEN"
        assert race["version"] == race_v + 2
