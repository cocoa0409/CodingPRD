"""Result flags and finalization gates: exclusion before ranking, flag
cascades, the AUTO DNF sweep, and the finalize docket checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_race,
    create_protest_payload,
    find_awards,
    get_race,
    get_result_for_registration,
    ingest_reads,
    list_flags,
    publish_race,
    set_clock,
    setup_single_finisher_published_race,
    start_waves,
    validate_error,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
OF = TEST_USERS["race_official_headers"]

WAVE_7AM = {"key": "w1", "wave_index": 1,
            "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 100}
SSF_10K = [
    {"key": "start", "point_index": 1, "kind": "START", "distance_km": 0.0},
    {"key": "split5", "point_index": 2, "kind": "SPLIT", "distance_km": 5.0},
    {"key": "finish", "point_index": 3, "kind": "FINISH", "distance_km": 10.0},
]


def _pq_scenario(api):
    """P leads on gun (1805000) and chip (1800000); Q trails (1866000/1860000).
    Both M 35-39. A MANUAL DQ on P is RAISED after publication."""
    ctx = build_race(
        name="Eval Order 10K", distance_km=10.0, cutoff_minutes=120,
        points=SSF_10K, waves=[WAVE_7AM],
        chips=[{"key": "cp", "chip_code": "CHIP-P"},
               {"key": "cq", "chip_code": "CHIP-Q"}],
        registrations=[
            {"key": "p", "wave": "w1", "bib_number": "501",
             "participant_name": "Runner P", "birth_date": "1990-02-02",
             "gender": "M", "chip": "cp"},
            {"key": "q", "wave": "w1", "bib_number": "502",
             "participant_name": "Runner Q", "birth_date": "1991-04-04",
             "gender": "M", "chip": "cq"},
        ])
    start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
    ingest_reads(ctx, [
        {"point": "start", "chip": "cp", "ts": "2026-08-01T07:00:05.000Z"},
        {"point": "split5", "chip": "cp", "ts": "2026-08-01T07:15:05.000Z"},
        {"point": "finish", "chip": "cp", "ts": "2026-08-01T07:30:05.000Z"},
        {"point": "start", "chip": "cq", "ts": "2026-08-01T07:00:06.000Z"},
        {"point": "split5", "chip": "cq", "ts": "2026-08-01T07:15:36.000Z"},
        {"point": "finish", "chip": "cq", "ts": "2026-08-01T07:31:06.000Z"},
    ])
    publish_race(ctx, "2026-08-01T09:00:00Z")
    flag = validate_success(api.create_result_flag(
        {"registration_id": ctx["regs"]["p"]["id"], "flag_type": "DQ",
         "detail": "course marshal report"}, OF), 201)
    ctx["flag_id"] = flag["id"]
    return ctx


class TestExclusionBeforeRankEvaluationOrder:
    def test_confirmed_dq_excludes_and_rederives_ranks(self, api):
        """PRD §3.6: "Publication runs a full recompute of the race in four
        pinned phases — the order matters, because flags drive exclusions and
        exclusions drive ranks."
        PRD §3.7: "A confirmation while the race is `PROVISIONAL_PUBLISHED` or
        `AMENDMENT_OPEN` triggers the flag cascade: the subject's result —
        whether `PROVISIONAL` or `OFFICIAL` — moves to `EXCLUDED`, its
        `exclusion_reason` takes the flag's `flag_type`, its ranks are nulled,
        and ranks and awards across the race are recomputed."

        Design: Difficulty/combinatorial_formula/exclusion_before_rank_evaluation_order
        """
        ctx = _pq_scenario(api)
        # Pre-confirmation: P leads both rankings.
        res_p = get_result_for_registration(ctx["regs"]["p"]["id"])
        assert res_p["overall_rank_gun"] == 1 and res_p["age_group_rank_chip"] == 1

        validate_success(
            api.resolve_result_flag(ctx["flag_id"], "CONFIRMED", OF), 200)
        res_p = get_result_for_registration(ctx["regs"]["p"]["id"])
        assert res_p["status"] == "EXCLUDED"
        assert res_p["exclusion_reason"] == "DQ"
        assert res_p["overall_rank_gun"] is None
        assert res_p["age_group_rank_chip"] is None

        res_q = get_result_for_registration(ctx["regs"]["q"]["id"])
        assert res_q["overall_rank_gun"] == 1
        assert res_q["age_group_rank_chip"] == 1

    def test_confirmed_dq_swaps_place_one_awards(self, api):
        """PRD §3.6: "When a recompute changes the winner of a
        category-and-place pairing, the existing non-`REVOKED` award moves to
        `REVOKED` and a replacement row is created `PROJECTED`; an award whose
        winner is unchanged is kept exactly as it is."

        Design: Difficulty/combinatorial_formula/exclusion_before_rank_evaluation_order
        """
        ctx = _pq_scenario(api)
        race_id = ctx["race"]["id"]
        p_id, q_id = ctx["regs"]["p"]["id"], ctx["regs"]["q"]["id"]
        pre_overall = find_awards(race_id, "OVERALL_M", place=1, status="PROJECTED")
        assert pre_overall[0]["registration_id"] == p_id

        validate_success(
            api.resolve_result_flag(ctx["flag_id"], "CONFIRMED", OF), 200)

        revoked = find_awards(race_id, "OVERALL_M", place=1, status="REVOKED")
        assert len(revoked) == 1 and revoked[0]["registration_id"] == p_id
        projected = find_awards(race_id, "OVERALL_M", place=1, status="PROJECTED")
        assert len(projected) == 1
        assert projected[0]["registration_id"] == q_id
        assert projected[0]["basis_time_ms"] == 1866000

        ag_revoked = find_awards(race_id, "AG_M_35_39", place=1, status="REVOKED")
        assert len(ag_revoked) == 1 and ag_revoked[0]["registration_id"] == p_id
        ag_projected = find_awards(race_id, "AG_M_35_39", place=1, status="PROJECTED")
        assert len(ag_projected) == 1
        assert ag_projected[0]["registration_id"] == q_id
        assert ag_projected[0]["basis_time_ms"] == 1860000


def _tu_scenario(api):
    """T's SPLIT5k arrives 300s after her start (floor 600s): the ingest pace
    check raises an AUTO COURSE_CUT_SUSPECT. U's reads are clean."""
    ctx = build_race(
        name="Flag Cascade 10K", distance_km=10.0, cutoff_minutes=120,
        points=SSF_10K, waves=[WAVE_7AM],
        chips=[{"key": "ct", "chip_code": "CHIP-T"},
               {"key": "cu", "chip_code": "CHIP-U"}],
        registrations=[
            {"key": "t", "wave": "w1", "bib_number": "901",
             "participant_name": "Runner T", "birth_date": "1996-01-01",
             "gender": "F", "chip": "ct"},
            {"key": "u", "wave": "w1", "bib_number": "902",
             "participant_name": "Runner U", "birth_date": "1997-02-02",
             "gender": "F", "chip": "cu"},
        ])
    start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
    ingest_reads(ctx, [
        {"point": "start", "chip": "ct", "ts": "2026-08-01T07:00:05.000Z"},
        {"point": "split5", "chip": "ct", "ts": "2026-08-01T07:05:05.000Z"},
        {"point": "finish", "chip": "ct", "ts": "2026-08-01T07:30:05.000Z"},
        {"point": "start", "chip": "cu", "ts": "2026-08-01T07:00:06.000Z"},
        {"point": "split5", "chip": "cu", "ts": "2026-08-01T07:15:36.000Z"},
        {"point": "finish", "chip": "cu", "ts": "2026-08-01T07:31:06.000Z"},
    ])
    publish_race(ctx, "2026-08-01T09:00:00Z")
    flags, _meta = list_flags(ctx["regs"]["t"]["id"],
                              flag_type="COURSE_CUT_SUSPECT", status="RAISED")
    assert len(flags) == 1, "the ingest pace check raised one AUTO flag"
    ctx["flag_id"] = flags[0]["id"]
    return ctx


class TestFlagConfirmationCascade:
    def test_confirmed_course_cut_excludes_result_and_recomputes_ranks(self, api):
        """PRD §3.5: "An elapsed time strictly below the floor is physically
        implausible and raises an automatic `COURSE_CUT_SUSPECT` flag in
        `RAISED` state with `origin` `AUTO`"
        PRD §3.7: "A confirmation while the race is `PROVISIONAL_PUBLISHED` or
        `AMENDMENT_OPEN` triggers the flag cascade: the subject's result —
        whether `PROVISIONAL` or `OFFICIAL` — moves to `EXCLUDED`, its
        `exclusion_reason` takes the flag's `flag_type`, its ranks are nulled,
        and ranks and awards across the race are recomputed."

        Design: Difficulty/transitive_cascade/flag_confirmation_cascade
        """
        ctx = _tu_scenario(api)
        flag = validate_success(
            api.resolve_result_flag(ctx["flag_id"], "CONFIRMED", OF), 200)
        assert flag["status"] == "CONFIRMED"
        assert flag["origin"] == "AUTO"

        res_t = get_result_for_registration(ctx["regs"]["t"]["id"])
        assert res_t["status"] == "EXCLUDED"
        assert res_t["exclusion_reason"] == "COURSE_CUT_SUSPECT"
        assert res_t["overall_rank_gun"] is None

        res_u = get_result_for_registration(ctx["regs"]["u"]["id"])
        assert res_u["overall_rank_gun"] == 1
        assert res_u["age_group_rank_chip"] == 1

    def test_confirmed_course_cut_swaps_overall_f_place_one(self, api):
        """PRD §3.6: "When a recompute changes the winner of a
        category-and-place pairing, the existing non-`REVOKED` award moves to
        `REVOKED` and a replacement row is created `PROJECTED`; an award whose
        winner is unchanged is kept exactly as it is."

        Design: Difficulty/transitive_cascade/flag_confirmation_cascade
        """
        ctx = _tu_scenario(api)
        race_id = ctx["race"]["id"]
        t_id, u_id = ctx["regs"]["t"]["id"], ctx["regs"]["u"]["id"]
        pre = find_awards(race_id, "OVERALL_F", place=1, status="PROJECTED")
        assert pre[0]["registration_id"] == t_id

        validate_success(
            api.resolve_result_flag(ctx["flag_id"], "CONFIRMED", OF), 200)

        revoked = find_awards(race_id, "OVERALL_F", place=1, status="REVOKED")
        assert len(revoked) == 1 and revoked[0]["registration_id"] == t_id
        projected = find_awards(race_id, "OVERALL_F", place=1, status="PROJECTED")
        assert len(projected) == 1
        assert projected[0]["registration_id"] == u_id
        assert projected[0]["basis_time_ms"] == 1866000


class TestFinalizeDocketGates:
    def test_finalize_with_raised_dnf_blocked_then_cleared(self, api):
        """PRD §3.6: "Every `CHECKED_IN` registration with no `SCORED` finish
        read receives an automatic `DNF` flag in `RAISED` state, with at most
        one unresolved automatic `DNF` per registration."
        PRD §3.8: "the flag docket, which must hold zero `RAISED` flags on any
        registration of the race, failing with `ERR_FLAGS_OUTSTANDING`."
        PRD §3.6: "Exclusion is independent of timing data: a registration whose
        `chip_time_ms` is null is simply left unranked — no rank is assigned,
        but the registration is not excluded on that basis."

        Design: Corner/state_machines/finalize_with_raised_dnf_blocked_then_cleared
        """
        ctx = build_race(
            name="DNF 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "ck1", "chip_code": "CHIP-K1"},
                   {"key": "ck2", "chip_code": "CHIP-K2"}],
            registrations=[
                {"key": "k1", "wave": "w1", "bib_number": "701",
                 "participant_name": "K One", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "ck1"},
                {"key": "k2", "wave": "w1", "bib_number": "702",
                 "participant_name": "K Two", "birth_date": "1991-01-01",
                 "gender": "M", "chip": "ck2"},
            ])
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "ck1", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "ck1", "ts": "2026-08-01T07:30:05.000Z"},
            {"point": "start", "chip": "ck2", "ts": "2026-08-01T07:00:06.000Z"},
        ])
        publish_race(ctx, "2026-08-01T09:00:00Z")

        flags, meta = list_flags(ctx["regs"]["k2"]["id"], flag_type="DNF")
        assert meta["total_count"] == 1, "publish raised one AUTO DNF"
        assert flags[0]["origin"] == "AUTO" and flags[0]["status"] == "RAISED"

        set_clock("2026-08-01T09:30:00Z")
        resp = api.finalize_results(ctx["race"]["id"], RD)
        validate_error(resp, ApiErrorId.ERR_FLAGS_OUTSTANDING, expected_status=409)

        validate_success(api.resolve_result_flag(flags[0]["id"], "DISMISSED", OF), 200)
        race = validate_success(api.finalize_results(ctx["race"]["id"], RD), 200)
        assert race["status"] == "FINALIZED"

        res_k2 = get_result_for_registration(ctx["regs"]["k2"]["id"])
        assert res_k2["status"] == "OFFICIAL", "dismissed flag: unranked, not excluded"
        assert res_k2["chip_time_ms"] is None
        assert res_k2["overall_rank_gun"] is None
        res_k1 = get_result_for_registration(ctx["regs"]["k1"]["id"])
        assert res_k1["status"] == "OFFICIAL"
        assert res_k1["overall_rank_gun"] == 1

    def test_finalize_window_open_rejected(self, api):
        """PRD §3.8: "the window check, which requires the logical now to be at
        or after `protest_window_closes_at` — the boundary is inclusive, and an
        earlier attempt fails with `ERR_PROTEST_WINDOW_OPEN`"

        Design: Corner/state_machines/finalize_window_open_rejected
        """
        ctx = build_race(
            name="Early Finalize 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM], chips=(), registrations=())
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        publish_race(ctx, "2026-08-01T09:00:00Z")

        set_clock("2026-08-01T09:15:00Z")  # 15 minutes into the 30-minute window
        resp = api.finalize_results(ctx["race"]["id"], RD)
        validate_error(resp, ApiErrorId.ERR_PROTEST_WINDOW_OPEN, expected_status=409)
        race = get_race(ctx)
        assert race["status"] == "PROVISIONAL_PUBLISHED"

    def test_finalize_with_filed_protest_rejected(self, api):
        """PRD §3.8: "the protest docket, which must hold zero `FILED` protests
        for the race, failing with `ERR_PROTESTS_OUTSTANDING`"

        Design: Corner/validations/finalize_with_filed_protest_rejected
        """
        ctx = setup_single_finisher_published_race(name="Outstanding 10K")
        protest = validate_success(api.create_protest(
            create_protest_payload(
                ctx["race"]["id"], ctx["regs"]["r1"]["id"],
                ctx["reads"]["finish_read"]["id"], "ADJUST_READ_TIME",
                "pending review",
                corrected_timestamp="2026-08-01T07:30:00.000Z"),
            TEST_USERS["registration_clerk_headers"]), 201)

        set_clock("2026-08-01T09:31:00Z")  # window closed, protest still FILED
        resp = api.finalize_results(ctx["race"]["id"], RD)
        validate_error(resp, ApiErrorId.ERR_PROTESTS_OUTSTANDING, expected_status=409)

        validate_success(api.resolve_protest(protest["id"], "DISMISSED",
                                             TEST_USERS["race_official_headers"]), 200)
        race = validate_success(api.finalize_results(ctx["race"]["id"], RD), 200)
        assert race["status"] == "FINALIZED"
