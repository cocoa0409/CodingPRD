"""Scoring model: provisional vs official variants, panel-size branching,
trim, the provisional minimum-sheet rule, ranking tie-breaks, quorum, sheet
reopen, and the post-official lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    apply_safety_deduction,
    appeal_deduction,
    assert_performance,
    get_success_data,
    make_head_judge_headers,
    make_judge_headers,
    make_performance_official,
    make_safety_judge_headers,
    mark_performance_performed,
    resolve_appeal,
    setup_live_event_with_checked_in_teams,
    setup_official_performance,
    submit_full_panel,
    submit_sheet_for_judge,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["event_director_headers"]


class TestDualVariantDivergence:
    def test_score_variants_trim_and_appeal_inclusion_diverge(self, api):
        """PRD §3.6: "The **OFFICIAL** variant, used at confirm-official and
        on any post-official deduction overturn, adds one twist: when the
        panel supplies at least 5 submitted sheets for a category, exactly one
        highest and one lowest value (a single occurrence of each) are removed
        from that category's values before averaging. The **PROVISIONAL**
        variant, used while the performance is `PERFORMED` or `SCORED`, never
        trims — it averages however many `SUBMITTED` sheets exist"
        PRD §3.6: "PROVISIONAL counts deductions in `APPLIED`, `UNDER_APPEAL`,
        or `UPHELD` status; OFFICIAL counts only `APPLIED` and `UPHELD`"

        Design: Difficulty/dual_variant_calc/score_variants_trim_and_appeal_inclusion_diverge
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}],
            panel_count=5)
        perf = ctx["teams"][0]["performance"]
        safety_id = ctx["safety"]["id"]
        head_id = ctx["head"]["id"]

        # TIME 7s x 0.5 = 3.50, BOUNDARY 3 x 0.25 = 0.75 (system deductions).
        mark_performance_performed(perf["id"], safety_id,
                                   actual_duration_seconds=157,
                                   boundary_violations=3)
        # SAFETY 1 x 2.0 = 2.00, appealed then REJECTED -> UPHELD (counts in
        # both variants, keeping the deduction sets equal).
        deduction = apply_safety_deduction(perf["id"], safety_id)
        appeal = appeal_deduction(deduction["id"], "coach-1")
        resolve_appeal(appeal["id"], head_id, "REJECTED")

        panel_scores = [
            (8.0, 7.5, 7.0, 8.5),
            (8.0, 8.0, 7.5, 8.5),
            (8.5, 8.0, 7.5, 9.0),
            (9.0, 8.5, 8.0, 9.0),
            (10.0, 9.5, 9.0, 9.5),
        ]
        for judge, score in zip(ctx["panel"], panel_scores):
            submit_sheet_for_judge(perf["id"], judge["id"], *score)

        make_performance_official(perf["id"], head_id)
        final = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert_performance(final)
        # PROVISIONAL (no trim): base 84.40 - 6.25 = 78.15.
        assert final["provisional_score"] == pytest.approx(78.15, abs=0.001)
        # OFFICIAL (one high + one low trimmed per category): 83.00 - 6.25.
        assert final["official_score"] == pytest.approx(76.75, abs=0.001)
        assert final["official_score"] != final["provisional_score"]

    def test_provisional_includes_under_appeal_but_official_excludes(self, api):
        """PRD §3.6: "Consequently, a deduction under appeal lowers the
        provisional score but not the official score, and identical raw data
        yields different final scores between variants whenever an appeal is
        in flight."
        PRD §3.6: "OFFICIAL counts only `APPLIED` and `UPHELD`, excluding
        `UNDER_APPEAL` deductions as unresolved."

        Design: Difficulty/dual_variant_calc/score_variants_trim_and_appeal_inclusion_diverge
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
        perf = ctx["teams"][0]["performance"]
        safety_id = ctx["safety"]["id"]
        head_id = ctx["head"]["id"]

        mark_performance_performed(perf["id"], safety_id, 150, 0)
        submit_full_panel(perf["id"], ctx["panel"], 8.0)  # base 80.00
        deduction = apply_safety_deduction(perf["id"], safety_id)  # 2.00 pts
        appeal = appeal_deduction(deduction["id"], "coach-1")  # UNDER_APPEAL

        # While the appeal is in flight the provisional score counts it.
        mid = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert mid["status"] == "SCORED"
        assert mid["provisional_score"] == pytest.approx(78.00, abs=0.001)

        # Overturning the appeal restores the points; the OVERTURNED deduction
        # then counts in no variant, so the official score equals the base.
        resolve_appeal(appeal["id"], head_id, "ACCEPTED")
        final_perf = make_performance_official(perf["id"], head_id)
        assert final_perf["official_score"] == pytest.approx(80.00, abs=0.001)


class TestPanelSizeBranching:
    def test_score_aggregation_branching_on_panel_size(self, api):
        """PRD §3.6: "when the panel supplies at least 5 submitted sheets for
        a category, exactly one highest and one lowest value (a single
        occurrence of each) are removed from that category's values before
        averaging."
        PRD §3.5: "If `actual_duration_seconds` exceeds the division's
        `routine_time_limit_seconds`, a `SYSTEM` deduction of `type` `TIME` is
        created with `quantity` equal to the number of full seconds over the
        limit and `rate_applied` snapshotted from the division's
        `time_deduction_per_second`. If `boundary_violations` is greater than
        zero, a `SYSTEM` deduction of `type` `BOUNDARY` is created with
        `quantity` equal to `boundary_violations` and `rate_applied`
        snapshotted from `boundary_deduction_points`."

        Design: Difficulty/combinatorial_formula/score_aggregation_branching_on_panel_size
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
        perf = ctx["teams"][0]["performance"]
        safety_id = ctx["safety"]["id"]

        mark_performance_performed(perf["id"], safety_id,
                                   actual_duration_seconds=157,
                                   boundary_violations=3)
        deductions, _ = validate_paginated(
            api.list_performance_deductions(perf["id"], DIRECTOR))
        points = sorted(d["points"] for d in deductions)
        assert points == [0.75, 3.50]

        scores = [(8.0, 7.5, 7.0, 8.0), (8.5, 8.0, 7.5, 8.0),
                  (9.0, 8.5, 8.0, 9.0)]
        for judge, score in zip(ctx["panel"], scores):
            submit_sheet_for_judge(perf["id"], judge["id"], *score)

        final = make_performance_official(perf["id"], ctx["head"]["id"])
        # 3 sheets: no trim. Base = (0.3*8.5 + 0.3*8.0 + 0.2*7.5 +
        # 0.2*8.3333...) * 10 = 81.17; 81.17 - 4.25 = 76.92.
        assert final["official_score"] == pytest.approx(76.92, abs=0.001)

    def test_provisional_score_null_below_two_sheet_minimum(self, api):
        """PRD §3.6: "The **PROVISIONAL** variant, used while the performance
        is `PERFORMED` or `SCORED`, never trims — it averages however many
        `SUBMITTED` sheets exist — and it produces no value at all (a null
        `provisional_score`) while fewer than 2 submitted sheets remain."

        Design: Corner/calculations/provisional_score_null_below_two_sheet_minimum
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
        perf = ctx["teams"][0]["performance"]
        mark_performance_performed(perf["id"], ctx["safety"]["id"], 150, 0)

        # 0 submitted sheets: null.
        state = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert state["provisional_score"] is None

        # 1 submitted sheet: still null.
        submit_sheet_for_judge(perf["id"], ctx["panel"][0]["id"], 8.0)
        state = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert state["provisional_score"] is None

        # 2 submitted sheets (flat 8.0): provisional appears at 80.00.
        submit_sheet_for_judge(perf["id"], ctx["panel"][1]["id"], 8.0)
        state = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert state["provisional_score"] == pytest.approx(80.00, abs=0.001)


class TestRanking:
    def test_ranking_tie_break_prefers_fewer_deduction_points(self, api):
        """PRD §3.7: "Ordering is a four-level total order: higher
        `official_score` first; ties broken by fewer total deduction points
        counted under the OFFICIAL rule (deductions in `APPLIED` or
        `UPHELD`); then by the OFFICIAL-variant base score's
        `building_execution` category average, higher first; and finally by
        earlier `scheduled_start`."

        Design: Corner/calculations/ranking_tie_break_prefers_fewer_deduction_points
        """
        ctx = setup_live_event_with_checked_in_teams([
            {"coach_id": "coach-a", "name": "TA", "organization": "GymA",
             "athlete_name": "Ann", "athlete_dob": "2010-05-01"},
            {"coach_id": "coach-b", "name": "TB", "organization": "GymB",
             "athlete_name": "Bob", "athlete_dob": "2010-06-01"},
        ])
        team_a, team_b = ctx["teams"][0], ctx["teams"][1]
        safety_id = ctx["safety"]["id"]
        head_id = ctx["head"]["id"]

        # tA: base 82.00 minus a 2.00 SAFETY deduction -> 80.00.
        mark_performance_performed(team_a["performance"]["id"], safety_id, 150, 0)
        apply_safety_deduction(team_a["performance"]["id"], safety_id)
        submit_full_panel(team_a["performance"]["id"], ctx["panel"], 8.2)
        # tB: clean base 80.00.
        mark_performance_performed(team_b["performance"]["id"], safety_id, 149, 0)
        submit_full_panel(team_b["performance"]["id"], ctx["panel"], 8.0)

        final_a = make_performance_official(team_a["performance"]["id"], head_id)
        final_b = make_performance_official(team_b["performance"]["id"], head_id)
        assert final_a["official_score"] == pytest.approx(80.00, abs=0.001)
        assert final_b["official_score"] == pytest.approx(80.00, abs=0.001)

        standings, _ = validate_paginated(
            api.get_division_standings(ctx["division"]["id"], DIRECTOR))
        assert standings[0]["team_id"] == team_b["team"]["id"]
        assert standings[0]["rank_in_division"] == 1
        assert standings[1]["team_id"] == team_a["team"]["id"]
        assert standings[1]["rank_in_division"] == 2

    def test_standings_computed_read_reflects_ranks(self, api):
        """PRD §3.7: "A division's standings read returns its ranked
        `OFFICIAL` performances in `rank_in_division` ascending order."
        PRD §3.3: "When the team's performance later becomes `OFFICIAL`, the
        system automatically moves the team from `CHECKED_IN` to `COMPETED`."

        Design: Corner/endpoints/standings_computed_read_reflects_ranks
        """
        ctx = setup_official_performance(sheet_score=8.0)
        team = ctx["teams"][0]["team"]

        standings, _ = validate_paginated(
            api.get_division_standings(ctx["division"]["id"], DIRECTOR))
        assert len(standings) == 1
        assert standings[0]["team_id"] == team["id"]
        assert standings[0]["rank_in_division"] == 1
        assert standings[0]["official_score"] == pytest.approx(80.00, abs=0.001)
        assert standings[0]["status"] == "OFFICIAL"

        team_after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert team_after["reg_status"] == "COMPETED"


class TestQuorumAndReopen:
    def test_confirm_official_before_quorum_rejected(self, api):
        """PRD §3.7: "from `PERFORMED` — meaning the panel quorum is
        incomplete — `ERR_QUORUM_NOT_MET`"

        Design: Corner/errors/confirm_official_before_quorum_rejected
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
        perf = ctx["teams"][0]["performance"]
        mark_performance_performed(perf["id"], ctx["safety"]["id"], 150, 0)
        submit_sheet_for_judge(perf["id"], ctx["panel"][0]["id"], 8.0)

        resp = api.confirm_official(
            perf["id"], make_head_judge_headers(ctx["head"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
        state = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert state["status"] == "PERFORMED"

    def test_sheet_reopen_breaks_quorum_and_reverts_performance(self, api):
        """PRD §3.5: "Editing a `SUBMITTED` sheet reopens it to `DRAFT`"
        PRD §3.5: "Conversely, when a submitted sheet is reopened to `DRAFT`
        and quorum is lost, the performance automatically drops from `SCORED`
        back to `PERFORMED`, and the provisional score is recomputed over the
        remaining `SUBMITTED` sheets — nulling out entirely if fewer than 2
        remain."

        Design: Corner/state_machines/sheet_reopen_breaks_quorum_and_reverts_performance
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
        perf = ctx["teams"][0]["performance"]
        mark_performance_performed(perf["id"], ctx["safety"]["id"], 150, 0)
        sheets = submit_full_panel(perf["id"], ctx["panel"], 8.0)

        state = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert state["status"] == "SCORED"

        last = sheets[-1]
        reopened = get_success_data(api.patch_score_sheet(
            last["id"], {"overall_impression": 9.0},
            make_judge_headers(ctx["panel"][-1]["id"])))
        assert reopened["status"] == "DRAFT"

        reverted = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert reverted["status"] == "PERFORMED"

    def test_sheet_patch_after_official_rejected_and_deduction_on_official_rejected(self, api):
        """PRD §3.5: "once the performance is `OFFICIAL` every sheet is
        `LOCKED`, and any edit or submit attempt is rejected with
        `ERR_SCORE_SHEET_LOCKED`."
        PRD §3.5: "against an `OFFICIAL`, `EXCLUDED`, or `CANCELLED`
        performance it is `ERR_PERFORMANCE_INVALID_STATE`."

        Design: Corner/errors/sheet_patch_after_official_rejected_and_deduction_on_official_rejected
        """
        ctx = setup_official_performance(sheet_score=8.0)
        perf = ctx["teams"][0]["performance"]

        sheets, _ = validate_paginated(
            api.list_performance_score_sheets(perf["id"], DIRECTOR))
        resp = api.patch_score_sheet(
            sheets[0]["id"], {"overall_impression": 9.0},
            make_judge_headers(ctx["panel"][0]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCORE_SHEET_LOCKED)

        resp = api.create_deduction(
            perf["id"],
            {"type": "SAFETY", "quantity": 1, "skill_tier": 4},
            make_safety_judge_headers(ctx["safety"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_INVALID_STATE)


class TestTrimBoundary:
    def test_trim_applies_at_five_sheets_but_not_four(self, api):
        """PRD §3.6: "when the panel supplies at least 5 submitted sheets for
        a category, exactly one highest and one lowest value (a single
        occurrence of each) are removed from that category's values before
        averaging."
        PRD §2.7: "The rounding order for scores is pinned: per-category
        averages are **never** rounded; exactly one round-half-up to 2 decimal
        places is applied after the weighted sum is computed and scaled."

        Design: Difficulty/combinatorial_formula/score_aggregation_branching_on_panel_size
        """
        # 5-judge panel: with sheets (BD,BE,TD,OI) all flat per judge at
        # 8.0, 8.0, 8.0, 9.0, 10.0 — trimming one high (10.0) and one low
        # (8.0) per category leaves (8.0, 8.0, 9.0) -> avg 25/3.
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}],
            panel_count=5)
        perf = ctx["teams"][0]["performance"]
        mark_performance_performed(perf["id"], ctx["safety"]["id"], 150, 0)
        for judge, score in zip(ctx["panel"], [8.0, 8.0, 8.0, 9.0, 10.0]):
            submit_sheet_for_judge(perf["id"], judge["id"], score)

        final = make_performance_official(perf["id"], ctx["head"]["id"])
        # Trimmed avg per category: 25/3; weighted sum 25/3; scaled 250/3 =
        # 83.3333... -> one round-half-up -> 83.33.
        assert final["official_score"] == pytest.approx(83.33, abs=0.001)

        # Provisional (no trim): mean of all five = 8.6 per category ->
        # 86.00. The two variants diverge on identical sheet data.
        assert final["provisional_score"] == pytest.approx(86.00, abs=0.001)


class TestPanelGateRejections:
    def test_judge_panel_membership_certification_and_duplicate_sheet(self, api):
        """PRD §3.5: "Two panel checks apply at creation, in this order: the
        acting judge's `id` must appear in the division's `judge_ids` (else
        `ERR_JUDGE_NOT_ON_PANEL`), and no existing sheet may already exist
        for this (performance, judge) pair (else `ERR_DUPLICATE_SCORE_SHEET`).
        Certification is enforced at both creation and again at submission:
        the division's `level` must appear in the judge's `certified_levels`,
        else `ERR_JUDGE_NOT_CERTIFIED`."

        Design: Corner/validations/judge_panel_membership_certification_and_duplicate_sheet
        """
        # Panel: j1 (level 3), j2 (level 2 only — on-panel but uncertified),
        # j3 (level 3). j4 (level 3) exists but is NOT on the panel. Build the
        # scenario explicitly so the panel mixes certifications.
        from test_helpers import (
            add_roster_entry,
            check_in_team,
            create_athlete,
            create_division,
            create_event,
            create_judge,
            create_team,
            lock_roster,
            open_registration,
            submit_and_verify_music,
        )
        event = create_event()
        j1 = create_judge("J1", (3,))
        j2 = create_judge("J2", (2,))
        j3 = create_judge("J3", (3,))
        j4 = create_judge("J4", (3,))
        safety = create_judge("JS", (3,))
        division = create_division(event["id"], [j1["id"], j2["id"], j3["id"]])
        open_registration(event["id"])
        athlete = create_athlete("Ann", "2010-05-01", "coach-1")
        team = create_team(event["id"], division["id"], "coach-1")
        add_roster_entry(team["id"], athlete["id"], "coach-1")
        lock_roster(team["id"], "coach-1")
        submit_and_verify_music(team["id"], "coach-1", "LIC-1")
        get_success_data(api.close_registration(event["id"], DIRECTOR))
        division = get_success_data(api.get_division(division["id"], DIRECTOR))
        get_success_data(api.generate_schedule(
            division["id"], division["version"], DIRECTOR))
        get_success_data(api.go_live(event["id"], DIRECTOR))
        check_in_team(team["id"], "coach-1", [athlete["id"]])
        perfs, _ = validate_paginated(
            api.list_team_performances(team["id"], DIRECTOR))
        perf = perfs[0]
        mark_performance_performed(perf["id"], safety["id"], 150, 0)

        # j1 creates a sheet (legal), then a second sheet from j1 is a
        # duplicate.
        validate_success(api.create_score_sheet(
            perf["id"],
            {"building_difficulty": 8.0, "building_execution": 8.0,
             "tumbling_difficulty": 8.0, "overall_impression": 8.0},
            make_judge_headers(j1["id"])), 201)

        # Off-panel judge j4: ERR_JUDGE_NOT_ON_PANEL.
        resp = api.create_score_sheet(
            perf["id"],
            {"building_difficulty": 8.0, "building_execution": 8.0,
             "tumbling_difficulty": 8.0, "overall_impression": 8.0},
            make_judge_headers(j4["id"]))
        validate_error(resp, ApiErrorId.ERR_JUDGE_NOT_ON_PANEL)

        # On-panel but uncertified judge j2 (level 2 only, division level 3):
        # ERR_JUDGE_NOT_CERTIFIED.
        resp = api.create_score_sheet(
            perf["id"],
            {"building_difficulty": 8.0, "building_execution": 8.0,
             "tumbling_difficulty": 8.0, "overall_impression": 8.0},
            make_judge_headers(j2["id"]))
        validate_error(resp, ApiErrorId.ERR_JUDGE_NOT_CERTIFIED)

        # j1's second sheet on the same performance: ERR_DUPLICATE_SCORE_SHEET.
        resp = api.create_score_sheet(
            perf["id"],
            {"building_difficulty": 7.5, "building_execution": 7.5,
             "tumbling_difficulty": 7.5, "overall_impression": 7.5},
            make_judge_headers(j1["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORE_SHEET)
