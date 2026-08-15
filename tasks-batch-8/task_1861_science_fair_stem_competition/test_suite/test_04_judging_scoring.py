"""Judging assignments, score sheets, and the normalization pipeline.

Covers: judge capacity bounds, the auto-assign selector ranking and empty-pool
fallback, recuse/release compensation, judge ownership on score submission,
the JUDGING-phase guard, Z_SCORE vs MIN_MAX divergence, per-pool
re-derivation, the min-max tie constant, quorum boundaries on the provisional
aggregate, input-set filtering, and double-submission rejection.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    add_active_judge,
    add_category,
    add_mentor,
    api_client,
    assert_score_sheet,
    assign_judge,
    begin_judging,
    close_registration,
    conflict_payload,
    create_edition,
    fd_headers,
    get_assignment,
    get_judge,
    get_project,
    get_sheet,
    judge_project_fully,
    make_judge_headers,
    open_registration,
    record_inspection,
    register_project,
    schedule_booth,
    setup_judging,
    setup_registration_closed,
    submit_project,
    submit_score,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

EPS = 1e-9


def _dual_variant_scored():
    """Two editions with identical raw data: one Z_SCORE, one MIN_MAX, each
    with two projects judged by two judges (J1: PA=70/PB=90, J2: PA=88/PB=100).
    Returns {"z": (pa_id, pb_id), "m": (pa_id, pb_id)}."""
    ids = {}
    for key, algorithm in (("z", "Z_SCORE"), ("m", "MIN_MAX")):
        ctx = setup_judging(num_projects=2, algorithm=algorithm, name=f"{algorithm} Edition")
        pa, pb = ctx["projects"]
        j1, j2 = ctx["judges"]
        judge_project_fully(pa["id"], [(j1, 70), (j2, 88)])
        judge_project_fully(pb["id"], [(j1, 90), (j2, 100)])
        ids[key] = (pa["id"], pb["id"])
    return ids


class TestDualVariantNormalization:
    def test_z_score_edition_final_aggregates(self, api):
        """PRD §3.5: "otherwise each sheet's `normalized_score` is its
        `raw_score` minus the pool mean, divided by the pool standard
        deviation, rounded half-up to three decimal places."
        PRD §3.5: "When the submitted count reaches `max_judges_per_project`
        exactly, the same mean, rounded half-up to two decimals, is written to
        `final_aggregate`".

        Design: Difficulty/dual_variant_calc/score_normalization_z_vs_minmax_diverge
        """
        ids = _dual_variant_scored()
        paz, pbz = ids["z"]

        # J1 pool [70, 90] -> mean 80, sd 10 -> z-scores -1.000 / +1.000.
        # J2 pool [88, 100] -> mean 94, sd 6 -> z-scores -1.000 / +1.000.
        pa = get_project(paz)
        pb = get_project(pbz)
        assert pa["final_aggregate"] == pytest.approx(-1.00, abs=EPS), (
            f"Z_SCORE PA final aggregate must be -1.00, got {pa['final_aggregate']}"
        )
        assert pb["final_aggregate"] == pytest.approx(1.00, abs=EPS), (
            f"Z_SCORE PB final aggregate must be 1.00, got {pb['final_aggregate']}"
        )

    def test_min_max_edition_diverges_on_identical_raws(self, api):
        """PRD §3.5: "each sheet's `normalized_score` is its `raw_score` minus
        the pool's minimum raw score, divided by the spread between the pool's
        maximum and minimum, rounded half-up to three decimal places".
        PRD §3.5: "The two variants are not interchangeable: identical judge
        pools with identical raw scores produce different normalized values
        under the two algorithms, most visibly where a one-score pool maps to
        0.000 under `Z_SCORE` but 0.500 under `MIN_MAX`."

        Design: Difficulty/dual_variant_calc/score_normalization_z_vs_minmax_diverge
        """
        ids = _dual_variant_scored()
        paz, _pbz = ids["z"]
        pam, pbm = ids["m"]

        # MIN_MAX pools [70, 90] and [88, 100] -> 0.000 / 1.000 per judge.
        pa_m = get_project(pam)
        pb_m = get_project(pbm)
        pa_z = get_project(paz)
        assert pa_m["final_aggregate"] == pytest.approx(0.00, abs=EPS), (
            f"MIN_MAX PA final aggregate must be 0.00, got {pa_m['final_aggregate']}"
        )
        assert pb_m["final_aggregate"] == pytest.approx(1.00, abs=EPS), (
            f"MIN_MAX PB final aggregate must be 1.00, got {pb_m['final_aggregate']}"
        )
        assert pa_z["final_aggregate"] != pa_m["final_aggregate"], (
            "identical raw data must yield different aggregates across the two variants"
        )


class TestPoolRederivation:
    def test_existing_sheet_rederived_when_pool_grows(self, api):
        """PRD §3.5: "Normalization is per-judge and per-edition, and it is
        never incremental: every new submission re-derives the
        `normalized_score` of every sheet in the judge's current submitted
        pool, because the pool itself changed."

        Design: Corner/calculations/normalized_score_pool_rederivation_drift
        """
        ctx = setup_judging(
            num_projects=2, max_judges=3, quorum_pct=66,
            judges_spec=[
                {"full_name": "J1", "max_assignments": 9},
                {"full_name": "J2", "max_assignments": 9},
                {"full_name": "J3", "max_assignments": 9},
            ],
            name="ReDer Edition",
        )
        px, py = ctx["projects"]
        j1, j2, _j3 = ctx["judges"]
        xa1 = assign_judge(px["id"], j1["id"])
        assign_judge(px["id"], j2["id"])
        ya1 = assign_judge(py["id"], j1["id"])

        sheet = submit_score(xa1["id"], j1["id"], 80)
        assert_score_sheet(sheet)
        assert sheet["normalized_score"] == pytest.approx(0.000, abs=EPS), (
            "a single-score Z_SCORE pool has sd 0 and normalizes to 0.000"
        )

        submit_score(ya1["id"], j1["id"], 70)
        drifted = get_sheet(sheet["id"])
        assert drifted["normalized_score"] == pytest.approx(1.000, abs=EPS), (
            "pool [80, 70] has mean 75, sd 5, so the earlier sheet must be "
            f"re-derived to 1.000, got {drifted['normalized_score']}"
        )


class TestMinMaxTieConstant:
    def test_single_score_pool_maps_to_half(self, api):
        """PRD §3.5: "if the maximum equals the minimum (a single-sheet pool is
        the common case), every sheet maps to 0.500."

        Design: Corner/calculations/min_max_single_score_pool_tie_value
        """
        ctx = setup_judging(num_projects=1, algorithm="MIN_MAX", name="MM Edition")
        project = ctx["projects"][0]
        judge = ctx["judges"][0]
        assignment = assign_judge(project["id"], judge["id"])

        sheet = submit_score(assignment["id"], judge["id"], 42)
        assert sheet["normalized_score"] == pytest.approx(0.500, abs=EPS), (
            "a single-score MIN_MAX pool must map to the 0.500 tie value"
        )
        # Quorum is ceil(2 * 50 / 100) = 1, so one sheet publishes a provisional.
        after = get_project(project["id"])
        assert after["provisional_aggregate"] == pytest.approx(0.50, abs=EPS)


class TestQuorumBoundary:
    def _setup_quorum(self):
        """Z_SCORE edition (3 judges/project, quorum 66 -> 2 sheets) in
        JUDGING; PX carries assignments from J1/J2/J3; J2 has already scored
        PY=75, priming J2's pool."""
        ctx = setup_judging(
            num_projects=2, max_judges=3, quorum_pct=66,
            judges_spec=[
                {"full_name": "J1", "max_assignments": 5},
                {"full_name": "J2", "max_assignments": 5},
                {"full_name": "J3", "max_assignments": 5},
            ],
            name="Quorum Edition",
        )
        px, py = ctx["projects"]
        j1, j2, j3 = ctx["judges"]
        xa1 = assign_judge(px["id"], j1["id"])
        xa2 = assign_judge(px["id"], j2["id"])
        assign_judge(px["id"], j3["id"])
        ya2 = assign_judge(py["id"], j2["id"])
        submit_score(ya2["id"], j2["id"], 75)
        return px, j1, j2, xa1, xa2

    def test_below_quorum_provisional_is_null(self, api):
        """PRD §3.5: "The `provisional_aggregate` — that mean rounded half-up
        to two decimal places — is published only once the number of submitted
        sheets reaches the quorum, defined as `max_judges_per_project`
        multiplied by `min_quorum_ratio_pct`, divided by 100, and rounded up to
        a whole number; below quorum, `provisional_aggregate` stays null."

        Design: Difficulty/boundary_precision_check/quorum_threshold_boundary_provisional_aggregate
        """
        px, j1, _j2, xa1, _xa2 = self._setup_quorum()
        submit_score(xa1["id"], j1["id"], 80)

        after = get_project(px["id"])
        assert after["provisional_aggregate"] is None, (
            "quorum is ceil(3*66/100)=2; one sheet must leave provisional_aggregate null"
        )

    def test_at_quorum_provisional_published(self, api):
        """PRD §3.5: "The `provisional_aggregate` — that mean rounded half-up
        to two decimal places — is published only once the number of submitted
        sheets reaches the quorum, defined as `max_judges_per_project`
        multiplied by `min_quorum_ratio_pct`, divided by 100, and rounded up to
        a whole number; below quorum, `provisional_aggregate` stays null."

        Design: Difficulty/boundary_precision_check/quorum_threshold_boundary_provisional_aggregate
        """
        px, j1, j2, xa1, xa2 = self._setup_quorum()
        submit_score(xa1["id"], j1["id"], 80)
        submit_score(xa2["id"], j2["id"], 85)

        after = get_project(px["id"])
        # J1 pool [80] -> 0.000; J2 pool [75, 85] -> mean 80, sd 5 -> 1.000.
        assert after["provisional_aggregate"] == pytest.approx(0.50, abs=EPS), (
            f"at quorum the provisional mean must be 0.50, got {after['provisional_aggregate']}"
        )
        assert after["judging_status"] == "ASSIGNED", (
            "three sheets are required for JUDGED; two sheets leave the project ASSIGNED"
        )


class TestAggregateInputSetFiltering:
    def test_unsubmitted_assignments_never_enter_aggregate(self, api):
        """PRD §3.5: "The system collects the `normalized_score` values across
        the project's own submitted sheets and takes their mean."
        PRD §3.5: "below quorum, `provisional_aggregate` stays null."

        Design: Corner/cross_cutting_layers/derived_field_aggregate_input_set_filtering
        """
        ctx = setup_judging(
            num_projects=1, max_judges=3, quorum_pct=66,
            judges_spec=[
                {"full_name": "JD1", "max_assignments": 5},
                {"full_name": "JD2", "max_assignments": 5},
                {"full_name": "JD3", "max_assignments": 5},
            ],
            name="DR Edition",
        )
        project = ctx["projects"][0]
        j1, j2, j3 = ctx["judges"]
        a1 = assign_judge(project["id"], j1["id"])
        assign_judge(project["id"], j2["id"])
        assign_judge(project["id"], j3["id"])
        submit_score(a1["id"], j1["id"], 80)

        after = get_project(project["id"])
        assert after["provisional_aggregate"] is None, (
            "only SUBMITTED sheets enter the aggregate; 1 of 2 quorum sheets keeps it null"
        )
        assert after["final_aggregate"] is None


class TestJudgeCapacityBoundary:
    def _setup_capacity(self):
        ctx = setup_judging(
            num_projects=2,
            judges_spec=[{"full_name": "JCap", "max_assignments": 1}],
            name="Cap Edition",
        )
        return ctx["projects"][0], ctx["projects"][1], ctx["judges"][0]

    def test_first_assignment_at_capacity_boundary_accepted(self, api):
        """PRD §3.4: "Assignment creation enforces, in pipeline order, the
        segregation-of-duties conflict check at priority 5, then capacity and
        duplication at priority 7 — a judge at their `max_assignments` cap, or
        a duplicate non-terminal assignment for the same judge–project pair, is
        rejected with `ERR_CONSTRAINT_VIOLATION`".

        Design: Difficulty/boundary_precision_check/judge_capacity_boundary_assignment
        """
        p1, _p2, judge = self._setup_capacity()
        assignment = assign_judge(p1["id"], judge["id"])
        assert assignment["status"] == "ASSIGNED"
        assert get_judge(judge["id"])["active_assignment_count"] == 1, (
            "the first assignment moves the load 0 -> 1, at but not over the cap of 1"
        )

    def test_second_assignment_over_cap_rejected(self, api):
        """PRD §3.4: "a judge at their `max_assignments` cap, or a duplicate
        non-terminal assignment for the same judge–project pair, is rejected
        with `ERR_CONSTRAINT_VIOLATION`".

        Design: Difficulty/boundary_precision_check/judge_capacity_boundary_assignment
        """
        p1, p2, judge = self._setup_capacity()
        assign_judge(p1["id"], judge["id"])

        resp = api_client.create_judging_assignment(p2["id"], {"judge_id": judge["id"]}, fd_headers())
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION, 422)
        assert get_judge(judge["id"])["active_assignment_count"] == 1


class TestAutoAssignSelector:
    def test_selector_prefers_expertise_over_lower_load(self, api):
        """PRD §3.4: "Eligible judges are ranked by expertise match first: a
        judge whose `expertise_category_ids` contains the project's
        `category_id` ranks above one without it. Ties break on the lower
        `active_assignment_count`, and any remaining tie breaks on the earlier
        judge `created_at`."

        Design: Corner/endpoints/auto_assign_selector_picks_expert_least_loaded
        """
        # Manual assembly: the expert judge's expertise must reference the real
        # category id, and judges are activated while REGISTRATION_CLOSED.
        edition = create_edition(name="Sel Edition", max_judges=3)
        category = add_category(edition["id"], code="PHYS", name="Physics")
        mentor = add_mentor(full_name="Mentor Sel")
        open_registration(edition["id"])
        p = register_project(edition["id"], category["id"], mentor["id"], title="SP")
        d1 = register_project(edition["id"], category["id"], mentor["id"], title="Distractor1")
        d2 = register_project(edition["id"], category["id"], mentor["id"], title="Distractor2")
        for project in (p, d1, d2):
            submit_project(project["id"], mentor["id"])
        close_registration(edition["id"])
        jexp = add_active_judge(
            edition["id"], full_name="JExpert", max_assignments=9, expertise=[category["id"]]
        )
        jgen = add_active_judge(edition["id"], full_name="JGeneral", max_assignments=9)
        for i, project in enumerate((p, d1, d2)):
            schedule_booth(project["id"], hall="A", booth_number=i + 1)
            record_inspection(project["id"], "PASS")
        begin_judging(edition["id"])
        # Load the expert with two distractor assignments (load 2 vs 0).
        assign_judge(d1["id"], jexp["id"])
        assign_judge(d2["id"], jexp["id"])

        assignment = validate_success(
            api_client.create_judging_assignment(p["id"], {}, fd_headers()), 201
        )
        assert assignment["judge_id"] == jexp["id"], (
            "expertise match ranks above load: the expert (load 2) must beat the "
            f"generalist (load 0); got judge {assignment['judge_id']} vs expert {jexp['id']} "
            f"(generalist {jgen['id']})"
        )
        assert get_judge(jexp["id"])["active_assignment_count"] == 3

    def test_empty_eligible_pool_returns_no_eligible_judge(self, api):
        """PRD §3.4: "If the eligible set is empty, the request fails with
        `ERR_NO_ELIGIBLE_JUDGE` (409)."

        Design: Corner/endpoints/auto_assign_empty_pool_returns_no_eligible_judge
        """
        ctx = setup_judging(
            num_projects=1,
            judges_spec=[{"full_name": "JC", "max_assignments": 5}],
            name="EmptyPool Edition",
        )
        project = ctx["projects"][0]
        judge = ctx["judges"][0]
        validate_success(
            api_client.declare_conflict(
                judge["id"], conflict_payload(project["id"], reason="mentor at same school"),
                fd_headers(),
            ),
            201,
        )

        resp = api_client.create_judging_assignment(project["id"], {}, fd_headers())
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_JUDGE, 409)


class TestAssignmentExitRamps:
    def test_recuse_restores_judge_load(self, api):
        """PRD §3.5: "A judge may recuse from their own `ASSIGNED` assignment:
        the assignment moves to `RECUSED`, the judge's
        `active_assignment_count` drops by 1, a conflict row for the
        judge–project pair is created if none exists (feeding future selector
        runs), and if the project is left with zero remaining `ASSIGNED`
        assignments its `judging_status` falls back to `UNASSIGNED`."

        Design: Difficulty/compensating_invariant/judge_load_invariant_assign_recuse
        """
        ctx = setup_judging(num_projects=1, name="Inv1 Edition")
        project, judge = ctx["projects"][0], ctx["judges"][0]

        assignment = assign_judge(project["id"], judge["id"])
        assert get_judge(judge["id"])["active_assignment_count"] == 1

        recused = validate_success(
            api_client.recuse_assignment(assignment["id"], make_judge_headers(judge["id"]))
        )
        assert recused["status"] == "RECUSED"
        assert get_judge(judge["id"])["active_assignment_count"] == 0, (
            "recusal is the compensating action: the judge's load returns to 0"
        )

    def test_recuse_creates_conflict_and_unassigns_project(self, api):
        """PRD §3.5: "A judge may recuse from their own `ASSIGNED` assignment:
        the assignment moves to `RECUSED`, the judge's
        `active_assignment_count` drops by 1, a conflict row for the
        judge–project pair is created if none exists (feeding future selector
        runs), and if the project is left with zero remaining `ASSIGNED`
        assignments its `judging_status` falls back to `UNASSIGNED`."

        Design: Difficulty/compensating_invariant/judge_load_invariant_assign_recuse
        """
        ctx = setup_judging(num_projects=1, name="Inv1 Edition")
        project, judge = ctx["projects"][0], ctx["judges"][0]
        assignment = assign_judge(project["id"], judge["id"])
        validate_success(api_client.recuse_assignment(assignment["id"], make_judge_headers(judge["id"])))

        conflicts, meta = validate_paginated(api_client.list_judge_conflicts(judge["id"], fd_headers()))
        assert meta["total_count"] == 1, "recusal must leave exactly one conflict row as audit residue"
        assert conflicts[0]["project_id"] == project["id"]
        assert get_project(project["id"])["judging_status"] == "UNASSIGNED", (
            "with zero remaining ASSIGNED assignments the project falls back to UNASSIGNED"
        )

    def test_release_decrements_load_and_unassigns(self, api):
        """PRD §3.5: "A `FairDirector` may instead release an assignment — the
        no-show case — which is only permitted while the edition is in
        `JUDGING`; release moves the assignment to `RELEASED` with the same
        workload decrement and the same possible fallback of the project to
        `UNASSIGNED`."

        Design: Corner/endpoints/release_assignment_decrements_judge_load
        """
        ctx = setup_judging(num_projects=1, name="Rel Edition")
        project, judge = ctx["projects"][0], ctx["judges"][0]
        assignment = assign_judge(project["id"], judge["id"])

        released = validate_success(api_client.release_assignment(assignment["id"], fd_headers()))
        assert released["status"] == "RELEASED"
        assert get_judge(judge["id"])["active_assignment_count"] == 0
        assert get_project(project["id"])["judging_status"] == "UNASSIGNED"


class TestScoreSubmissionGuards:
    def test_judge_cannot_score_other_judges_assignment(self, api):
        """PRD §3.5: "A judge submits a score sheet against one of their own
        assignments still in `ASSIGNED` — ownership is checked, so scoring
        someone else's assignment is `ERR_FORBIDDEN`".

        Design: Corner/rbac/judge_cannot_submit_for_other_judges_assignment
        """
        ctx = setup_judging(num_projects=1, name="RBAC2 Edition")
        project = ctx["projects"][0]
        j1, j2 = ctx["judges"]
        assignment = assign_judge(project["id"], j1["id"])

        resp = api_client.submit_score_sheet(
            assignment["id"], {"raw_score": 70}, make_judge_headers(j2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_score_submission_requires_judging_phase(self, api):
        """PRD §3.5: "The edition must be in `JUDGING` at that moment, or the
        submission is rejected with `ERR_NOT_JUDGING_PHASE`".
        PRD §3.4: "the parent edition must be in `REGISTRATION_CLOSED` or
        `JUDGING` — pre-assignment before the judging phase opens is
        legitimate".

        Design: Corner/errors/error_not_judging_phase_on_early_score
        """
        ctx = setup_registration_closed(num_projects=1, name="Phase Edition")
        project = ctx["projects"][0]
        schedule_booth(project["id"], hall="A", booth_number=1)
        judge = add_active_judge(ctx["edition"]["id"], full_name="JPH", max_assignments=5)
        # Pre-assignment during REGISTRATION_CLOSED is legitimate.
        assignment = assign_judge(project["id"], judge["id"])

        resp = api_client.submit_score_sheet(
            assignment["id"], {"raw_score": 70}, make_judge_headers(judge["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_JUDGING_PHASE, 409)

    def test_double_score_submission_rejected(self, api):
        """PRD §3.5: "A judge submits a score sheet against one of their own
        assignments still in `ASSIGNED`".
        PRD §3.5: "`SUBMITTED`, `RECUSED`, and `RELEASED` are all terminal for
        the assignment."

        Design: Corner/state_machines/score_submission_idempotency_double_submit
        """
        ctx = setup_judging(num_projects=1, name="Idem Edition")
        project = ctx["projects"][0]
        judge = ctx["judges"][0]
        assignment = assign_judge(project["id"], judge["id"])
        submit_score(assignment["id"], judge["id"], 75)

        resp = api_client.submit_score_sheet(
            assignment["id"], {"raw_score": 99}, make_judge_headers(judge["id"])
        )
        # The PRD's terminal-source rule names projects, awards, and editions;
        # a second submission on a terminal assignment may surface as the
        # generic state error or the terminal-source error (both 409).
        validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL])
        assert resp.status_code == 409, f"expected 409, got {resp.status_code}"

        _sheets, meta = validate_paginated(
            api_client.list_score_sheets(fd_headers(), params={"judging_assignment_id": assignment["id"]})
        )
        assert meta["total_count"] == 1, "the rejected second submission must not create a sheet"
        assert get_assignment(assignment["id"])["status"] == "SUBMITTED"
