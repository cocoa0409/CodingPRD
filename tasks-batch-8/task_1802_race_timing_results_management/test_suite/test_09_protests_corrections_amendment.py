"""Protests, corrections, and the race amendment loop: the protest window's
boundaries, spawned corrections, the null branches, kind actionability, and
the FINALIZED -> AMENDMENT_OPEN -> PROVISIONAL_PUBLISHED -> FINALIZED cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_award_singleton_per_category_place,
    build_race,
    create_correction_payload,
    create_protest_payload,
    find_awards,
    finalize_race,
    get_race,
    get_result_for_registration,
    make_race_official_headers,
    parse_iso,
    publish_race,
    race_version,
    set_clock,
    setup_divergence_race,
    setup_single_finisher_published_race,
    start_waves,
    ingest_reads,
    validate_error,
    validate_paginated,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
CLERK = TEST_USERS["registration_clerk_headers"]
OF = TEST_USERS["race_official_headers"]

WAVE_7AM = {"key": "w1", "wave_index": 1,
            "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 100}


class TestProtestWindowBoundaries:
    def test_filing_one_second_before_close_succeeds_then_finalize_at_close(self, api):
        """PRD §3.7: "Filing requires the logical now to fall strictly before
        `protest_window_closes_at`: filing at or after the close fails with
        `ERR_PROTEST_WINDOW_CLOSED`"
        PRD §3.6: "Publication then stamps `provisional_published_at` with the
        logical now and sets `protest_window_closes_at` thirty minutes later"
        PRD §3.8: "the window check, which requires the logical now to be at or
        after `protest_window_closes_at` — the boundary is inclusive, and an
        earlier attempt fails with `ERR_PROTEST_WINDOW_OPEN`"

        Design: Difficulty/boundary_precision_check/protest_window_strict_close_boundary
        """
        ctx = setup_single_finisher_published_race(name="Window 10K")
        race = get_race(ctx)
        assert parse_iso(race["protest_window_closes_at"]) == \
            parse_iso("2026-08-01T09:30:00Z"), "published 09:00 + thirty minutes"

        set_clock("2026-08-01T09:29:59Z")
        protest = validate_success(api.create_protest(
            create_protest_payload(ctx["race"]["id"], ctx["regs"]["r1"]["id"],
                                   ctx["reads"]["finish_read"]["id"],
                                   "EXCLUDE_READ", "late by one second is still open"),
            CLERK), 201)
        assert protest["status"] == "FILED"

        validate_success(api.resolve_protest(protest["id"], "DISMISSED", OF), 200)
        # Finalize at exactly the close: the window check is inclusive.
        race = finalize_race(ctx, "2026-08-01T09:30:00Z")["race"]
        assert race["status"] == "FINALIZED"

    def test_filing_exactly_at_close_rejected(self, api):
        """PRD §3.7: "Filing requires the logical now to fall strictly before
        `protest_window_closes_at`: filing at or after the close fails with
        `ERR_PROTEST_WINDOW_CLOSED`"

        Design: Difficulty/boundary_precision_check/protest_window_strict_close_boundary
        """
        ctx = setup_single_finisher_published_race(name="Window Closed 10K")
        set_clock("2026-08-01T09:30:00Z")  # exactly protest_window_closes_at
        resp = api.create_protest(
            create_protest_payload(ctx["race"]["id"], ctx["regs"]["r1"]["id"],
                                   ctx["reads"]["finish_read"]["id"],
                                   "EXCLUDE_READ", "exactly at close"),
            CLERK)
        validate_error(resp, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED,
                       expected_status=409)
        race = get_race(ctx)
        assert race["status"] == "PROVISIONAL_PUBLISHED"


def _amendment_cycle_setup(api):
    """Single-finisher race published at 09:00, finalized at 09:30 (inclusive
    window boundary), then a +60s finish-time correction is filed."""
    ctx = setup_single_finisher_published_race(name="Cycle 10K")
    finalize_race(ctx, "2026-08-01T09:30:00Z")
    corr = validate_success(api.create_correction(
        create_correction_payload(ctx["race"]["id"], ctx["reads"]["finish_read"]["id"],
                                  "ADJUST_READ_TIME", "finish line video review",
                                  corrected_timestamp="2026-08-01T07:31:05.000Z"),
        OF), 201)
    ctx["correction_id"] = corr["id"]
    return ctx


class TestRaceAmendmentCycleLoop:
    def test_correction_approval_amends_result_and_reopens_race(self, api):
        """PRD §3.7: "Second, the full four-phase recompute of §3.6 re-runs, and
        any `OFFICIAL` result whose computed fields change moves to `AMENDED`
        with its `revision` incremented by one."
        PRD §3.7: "Fourth, the race itself re-opens, moving from
        `PROVISIONAL_PUBLISHED` or `FINALIZED` into `AMENDMENT_OPEN` with
        `amendment_count` incremented by one"

        Design: Difficulty/non_linear_state_machine/race_amendment_cycle_loop
        """
        ctx = _amendment_cycle_setup(api)
        version = race_version(ctx)
        corr = validate_success(api.adjudicate_correction(
            ctx["correction_id"], "APPROVED", version, OF), 200)
        assert corr["status"] == "APPROVED"

        race = get_race(ctx)
        assert race["status"] == "AMENDMENT_OPEN"
        assert race["amendment_count"] == 1

        read = validate_success(
            api.get_timing_read(ctx["reads"]["finish_read"]["id"],
                                TEST_USERS["timing_operator_headers"]), 200)
        assert parse_iso(read["read_timestamp"]) == parse_iso("2026-08-01T07:31:05.000Z")
        assert read["adjusted_by_correction_id"] == ctx["correction_id"]
        assert read["status"] == "SCORED"

        result = get_result_for_registration(ctx["regs"]["r1"]["id"])
        assert result["status"] == "AMENDED"
        assert result["revision"] == 2
        assert result["chip_time_ms"] == 1860000  # 07:31:05 - 07:00:05
        assert result["gun_time_ms"] == 1865000   # 07:31:05 - 07:00:00

    def test_full_amendment_loop_recloses_and_keeps_unchanged_award(self, api):
        """PRD §3.6: "Re-publication moves every non-`EXCLUDED` result back to
        `PROVISIONAL` (including any that had been `AMENDED`)"
        PRD §3.8: "Finalization moves every `PROVISIONAL` result to `OFFICIAL`,
        every `PROJECTED` award to `CONFIRMED`, and stamps `finalized_at` with
        the logical now."
        PRD §3.6: "an award whose winner is unchanged is kept exactly as it is"

        Design: Difficulty/non_linear_state_machine/race_amendment_cycle_loop
        """
        ctx = _amendment_cycle_setup(api)
        race_id = ctx["race"]["id"]
        validate_success(api.adjudicate_correction(
            ctx["correction_id"], "APPROVED", race_version(ctx), OF), 200)

        publish_race(ctx, "2026-08-01T09:30:00Z")
        race = get_race(ctx)
        assert race["status"] == "PROVISIONAL_PUBLISHED"
        assert parse_iso(race["protest_window_closes_at"]) == \
            parse_iso("2026-08-01T10:00:00Z"), "the window re-opens on re-publish"
        result = get_result_for_registration(ctx["regs"]["r1"]["id"])
        assert result["status"] == "PROVISIONAL"

        finalize_race(ctx, "2026-08-01T10:07:00Z")
        race = get_race(ctx)
        assert race["status"] == "FINALIZED", "the amendment loop closes"
        result = get_result_for_registration(ctx["regs"]["r1"]["id"])
        assert result["status"] == "OFFICIAL"
        assert result["revision"] == 2

        # The single finisher never loses the category: kept CONFIRMED end-to-end.
        # PRD §3.6: "an award whose winner is unchanged is kept exactly as it
        # is" — the winner is unchanged by the correction, so the row survives;
        # whether its basis_time_ms refreshes to the corrected winning time is
        # not uniquely determined by the PRD, so no assertion is made on it.
        active = find_awards(race_id, "OVERALL_M", place=1, status="CONFIRMED")
        assert len(active) == 1
        assert active[0]["registration_id"] == ctx["regs"]["r1"]["id"]
        assert find_awards(race_id, "OVERALL_M", place=1, status="REVOKED") == []


class TestAwardSingletonPerCategoryPlace:
    def _amended_divergence_race(self, api, run_full_cycle):
        ctx = setup_divergence_race(finalize=True)
        corr = validate_success(api.create_correction(
            create_correction_payload(ctx["race"]["id"],
                                      ctx["reads"]["b_finish_read"]["id"],
                                      "ADJUST_READ_TIME", "photo review",
                                      corrected_timestamp="2026-08-01T07:44:20.000Z"),
            OF), 201)
        validate_success(api.adjudicate_correction(
            corr["id"], "APPROVED", race_version(ctx), OF), 200)
        if run_full_cycle:
            publish_race(ctx, "2026-08-01T09:30:00Z")
            finalize_race(ctx, "2026-08-01T10:07:00Z")
        return ctx

    def test_singleton_cardinality_and_confirmed_sets_after_cycle(self, api):
        """PRD §3.6: "At most one non-`REVOKED` award exists per race, category,
        and place at any moment."
        PRD §3.6: "Within each category, places 1 through 3 receive an award —
        or fewer when the eligible field runs shallower than three deep"
        PRD §3.8: "Finalization moves every `PROVISIONAL` result to `OFFICIAL`,
        every `PROJECTED` award to `CONFIRMED`"

        Design: Difficulty/compensating_invariant/award_singleton_per_category_place
        """
        ctx = self._amended_divergence_race(api, run_full_cycle=True)
        race_id = ctx["race"]["id"]
        all_awards, _meta = validate_paginated(
            api.list_race_awards(race_id, OF, params={"limit": 100}))
        assert_award_singleton_per_category_place(all_awards)

        ag_confirmed = find_awards(race_id, "AG_M_35_39", status="CONFIRMED")
        assert len(ag_confirmed) == 2, "min(3, 2 eligible) places confirmed"
        ag_by_place = {a["place"]: a for a in ag_confirmed}
        assert ag_by_place[1]["registration_id"] == ctx["regs"]["a"]["id"]
        assert ag_by_place[1]["basis_time_ms"] == 1920000
        assert ag_by_place[2]["registration_id"] == ctx["regs"]["b"]["id"]
        assert ag_by_place[2]["basis_time_ms"] == 2030000

        overall_confirmed = find_awards(race_id, "OVERALL_M", status="CONFIRMED")
        assert len(overall_confirmed) == 2
        overall_by_place = {a["place"]: a for a in overall_confirmed}
        assert overall_by_place[1]["registration_id"] == ctx["regs"]["a"]["id"]
        # A's row pre-dates the correction and A's gun time is untouched by it,
        # so kept-as-is and refreshed readings agree on 1925000.
        assert overall_by_place[1]["basis_time_ms"] == 1925000
        assert overall_by_place[2]["registration_id"] == ctx["regs"]["b"]["id"]
        # B's OVERALL place-2 row had an unchanged winner, so PRD §3.6's "kept
        # exactly as it is" leaves its basis_time_ms undetermined between the
        # pre-correction 1940000 and the corrected 2060000: not asserted.

        assert get_race(ctx)["status"] == "FINALIZED"

    def test_revoked_history_persists_from_the_swapped_rows(self, api):
        """PRD §3.6: "When a recompute changes the winner of a
        category-and-place pairing, the existing non-`REVOKED` award moves to
        `REVOKED` and a replacement row is created `PROJECTED`"
        PRD §3.6: "At most one non-`REVOKED` award exists per race, category,
        and place at any moment."

        Design: Difficulty/compensating_invariant/award_singleton_per_category_place
        """
        ctx = self._amended_divergence_race(api, run_full_cycle=True)
        race_id = ctx["race"]["id"]
        revoked = find_awards(race_id, status="REVOKED")
        assert len(revoked) == 2, "the two superseded rows persist as history"
        by_winner = {a["registration_id"]: a for a in revoked}
        # B's superseded AG place 1 and A's superseded AG place 2.
        assert by_winner[ctx["regs"]["b"]["id"]]["category"] == "AG_M_35_39"
        assert by_winner[ctx["regs"]["b"]["id"]]["place"] == 1
        assert by_winner[ctx["regs"]["a"]["id"]]["category"] == "AG_M_35_39"
        assert by_winner[ctx["regs"]["a"]["id"]]["place"] == 2


class TestProtestResolution:
    def test_protest_upheld_spawns_approved_correction(self, api):
        """PRD §3.7: "An upheld protest is executable: the system immediately
        creates a **Correction** that is already `APPROVED`, taking its `kind`
        from the protest's `requested_action`, carrying the same
        `timing_read_id` and `corrected_timestamp`, and with `protest_id`
        pointing back at the protest — and the full correction cascade described
        below runs."
        PRD §3.7: "Either way, the resolving official is recorded in
        `resolved_by_user_id`."

        Design: Corner/state_machines/protest_upheld_spawns_approved_correction
        """
        ctx = setup_single_finisher_published_race(name="Upheld 10K")
        protest = validate_success(api.create_protest(
            create_protest_payload(ctx["race"]["id"], ctx["regs"]["r1"]["id"],
                                   ctx["reads"]["finish_read"]["id"],
                                   "EXCLUDE_READ", "wrong athlete on chip"),
            CLERK), 201)

        resolved = validate_success(
            api.resolve_protest(protest["id"], "UPHELD", OF), 200)
        assert resolved["status"] == "UPHELD"
        assert resolved["resolved_by_user_id"] == "official-1"

        corrections, meta = validate_paginated(api.list_corrections(
            OF, params={"protest_id": protest["id"]}))
        assert meta["total_count"] == 1, "exactly one correction is spawned"
        spawned = corrections[0]
        assert spawned["status"] == "APPROVED", "spawned already approved, no adjudicate"
        assert spawned["kind"] == "EXCLUDE_READ"
        assert spawned["timing_read_id"] == ctx["reads"]["finish_read"]["id"]

        read = validate_success(api.get_timing_read(
            ctx["reads"]["finish_read"]["id"], TEST_USERS["timing_operator_headers"]), 200)
        assert read["status"] == "EXCLUDED"
        assert get_race(ctx)["status"] == "AMENDMENT_OPEN"
        result = get_result_for_registration(ctx["regs"]["r1"]["id"])
        assert result["chip_time_ms"] is None, "no scored finish anchor remains"
        assert result["overall_rank_gun"] is None

    def test_protest_dismissed_spawns_nothing(self, api):
        """PRD §3.7: "A dismissal closes the protest in `DISMISSED` with no
        further effect."

        Design: Corner/state_machines/protest_dismissed_spawns_nothing
        """
        ctx = setup_single_finisher_published_race(name="Dismissed 10K")
        protest = validate_success(api.create_protest(
            create_protest_payload(ctx["race"]["id"], ctx["regs"]["r1"]["id"],
                                   ctx["reads"]["finish_read"]["id"],
                                   "EXCLUDE_READ", "frivolous"),
            CLERK), 201)

        resolved = validate_success(
            api.resolve_protest(protest["id"], "DISMISSED", OF), 200)
        assert resolved["status"] == "DISMISSED"

        _corrections, meta = validate_paginated(api.list_corrections(
            OF, params={"protest_id": protest["id"]}))
        assert meta["total_count"] == 0
        assert get_race(ctx)["status"] == "PROVISIONAL_PUBLISHED"
        read = validate_success(api.get_timing_read(
            ctx["reads"]["finish_read"]["id"], TEST_USERS["timing_operator_headers"]), 200)
        assert read["status"] == "SCORED"

    def test_protest_resolve_sod_rejected(self, api):
        """PRD §2.9: "First, the official who resolves a protest must not be the
        clerk who filed it: protest resolution requires the acting `X-User-ID`
        to differ from the protest's recorded `filed_by_user_id`."
        PRD §3.7: "the segregation rule of §2.9 forbids the filer from resolving
        their own protest; the state check runs first, then the duty check,
        which rejects a colliding resolver with `ERR_SOD_VIOLATION`."

        Design: Corner/state_machines/protest_resolve_sod_rejected
        """
        ctx = setup_single_finisher_published_race(name="SoD Protest 10K")
        protest = validate_success(api.create_protest(
            create_protest_payload(ctx["race"]["id"], ctx["regs"]["r1"]["id"],
                                   ctx["reads"]["finish_read"]["id"],
                                   "EXCLUDE_READ", "sod test"),
            CLERK), 201)  # filed_by_user_id == "clerk-1"
        assert protest["filed_by_user_id"] == "clerk-1"

        resp = api.resolve_protest(protest["id"], "DISMISSED",
                                   make_race_official_headers("clerk-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
        after = validate_success(api.get_protest(protest["id"], OF), 200)
        assert after["status"] == "FILED"

    def test_protest_without_result_returns_400(self, api):
        """PRD §3.7: "Filing requires the logical now to fall strictly before
        `protest_window_closes_at`: filing at or after the close fails with
        `ERR_PROTEST_WINDOW_CLOSED`, and the window check runs before the
        referential checks, which reject a subject without a result, a read from
        another race, or a missing adjustment timestamp with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/protest_without_result_returns_400
        """
        ctx = build_race(
            name="NoResult 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-NR"}],
            registrations=[
                {"key": "rin", "wave": "w1", "bib_number": "896",
                 "participant_name": "N Hasone", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "c1"},
                {"key": "rout", "wave": "w1", "bib_number": "897",
                 "participant_name": "N Gone", "birth_date": "1991-01-01",
                 "gender": "M", "pay": False, "confirm": False},
            ])
        validate_success(api.withdraw_registration(ctx["regs"]["rout"]["id"], CLERK), 200)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "c1", "ts": "2026-08-01T07:00:05.000Z"},
            {"point": "finish", "chip": "c1", "ts": "2026-08-01T07:30:05.000Z",
             "key": "fin"},
        ])
        publish_race(ctx, "2026-08-01T09:00:00Z")

        resp = api.create_protest(
            create_protest_payload(ctx["race"]["id"], ctx["regs"]["rout"]["id"],
                                   ctx["reads"]["fin"]["id"],
                                   "EXCLUDE_READ", "no result exists"),
            CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestCorrectionBranches:
    def test_correction_kind_mismatch_returns_409(self, api):
        """PRD §3.7: "Not every kind is actionable on every read: `EXCLUDE_READ`
        requires the target read to be `SCORED`; `REINSTATE_READ` requires it to
        be `EXCLUDED`; and `ADJUST_READ_TIME` requires it to be `SCORED` with
        the corrected timestamp supplied. A mismatch fails with
        `ERR_CORRECTION_KIND_MISMATCH`, checked both at filing and again at
        adjudication."

        Design: Corner/validations/correction_kind_mismatch_returns_409
        """
        ctx = setup_single_finisher_published_race(name="Mismatch 10K")
        resp = api.create_correction(
            create_correction_payload(ctx["race"]["id"],
                                      ctx["reads"]["finish_read"]["id"],
                                      "REINSTATE_READ", "nothing to reinstate"),
            OF)
        validate_error(resp, ApiErrorId.ERR_CORRECTION_KIND_MISMATCH,
                       expected_status=409)

    def test_correction_rejected_has_no_effects(self, api):
        """PRD §3.7: "A `REJECTED` decision closes the correction in `REJECTED`
        and still advances the race `version` by one"

        Design: Corner/state_machines/correction_rejected_has_no_effects
        """
        ctx = setup_single_finisher_published_race(name="RejCorr 10K")
        corr = validate_success(api.create_correction(
            create_correction_payload(ctx["race"]["id"],
                                      ctx["reads"]["finish_read"]["id"],
                                      "EXCLUDE_READ", "spurious claim"),
            OF), 201)
        version_before = race_version(ctx)
        rejected = validate_success(api.adjudicate_correction(
            corr["id"], "REJECTED", version_before, OF), 200)
        assert rejected["status"] == "REJECTED"

        race = get_race(ctx)
        assert race["status"] == "PROVISIONAL_PUBLISHED"
        assert race["amendment_count"] == 0
        assert race["version"] == version_before + 1, "OCC bookkeeping still advances"

        read = validate_success(api.get_timing_read(
            ctx["reads"]["finish_read"]["id"], TEST_USERS["timing_operator_headers"]), 200)
        assert read["status"] == "SCORED"
        result = get_result_for_registration(ctx["regs"]["r1"]["id"])
        assert result["chip_time_ms"] == 1800000
        assert result["revision"] == 1
