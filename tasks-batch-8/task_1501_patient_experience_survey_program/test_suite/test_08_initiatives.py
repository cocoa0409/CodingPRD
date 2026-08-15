"""Improvement initiatives: baseline pinning, the PUBLISHED-baseline gate,
window arithmetic, evaluation branching (PINNED vs ROLLING, MET vs MISSED),
unit-absent evaluation, and the replan loop (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_initiative,
    field_and_publish_cycle,
    create_initiative_payload,
    create_response_payload,
    get_cycle,
    get_initiative,
    get_success_data,
    import_cases,
    import_discharges,
    import_responses,
    make_active_initiative,
    make_cycle,
    make_program,
    make_provider,
    make_ticket,
    make_unit,
    make_vendor,
    make_vendor_headers,
    record_response,
    replan_initiative_payload,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    setup_published_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]


def _scored_cycle_at(api, name, topbox_count, low_count):
    """25-response MAIL cycle in SCORING (not published): adjusted 100 when
    low_count == 0."""
    ctx = setup_cycle_in_state(
        setup_program(name=name), "FIELDING",
        discharge_count=topbox_count + low_count)
    import_responses(ctx["case_ids"][0:topbox_count], ctx["vendor"]["id"],
                     mode_used="MAIL", score=4)
    if low_count:
        import_responses(ctx["case_ids"][topbox_count:], ctx["vendor"]["id"],
                         mode_used="MAIL", score=3)
    set_clock("2026-08-31T00:00:00Z")
    get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
    get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))
    return get_cycle(ctx["cycle"]["id"]), ctx


class TestActivationGates:
    def test_initiative_activate_gated_by_baseline_cycle_state(self, api):
        """PRD §3.8: "The baseline cycle must be `PUBLISHED`
        (`ERR_BASELINE_CYCLE_NOT_PUBLISHED`)."
        PRD §3.8: "A new initiative is `DRAFT` with `baseline_score`, both
        progress fields, and `achieved_at` all null."

        Design: Difficulty/cross_entity_state_dependency/initiative_activate_gated_by_baseline_cycle_state
        """
        c1, ctx = _scored_cycle_at(api, "P-CE2", 25, 0)
        assert c1["status"] == "SCORING"
        c2 = make_cycle(ctx["program"]["id"], label="Q2", cycle_index=2,
                        discharge_window_start="2026-07-01",
                        discharge_window_end="2026-07-31",
                        fielding_start_date="2026-09-01",
                        fielding_end_date="2026-09-30")
        initiative = get_success_data(api.create_initiative(
            create_initiative_payload(
                ctx["unit"]["id"], "OVERALL_RATING", c1["id"], c2["id"],
                target_score=90.0),
            ADMIN))

        res = api.activate_initiative(initiative["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_BASELINE_CYCLE_NOT_PUBLISHED)
        after = get_initiative(initiative["id"])
        assert after["status"] == "DRAFT"
        assert after["baseline_score"] is None

    def test_baseline_scoring_not_enough_must_be_published(self, api):
        """PRD §3.8: "Activation moves the initiative from `DRAFT` to `ACTIVE`
        (from any other status, `ERR_INVALID_STATE`) under four guards. The
        baseline cycle must be `PUBLISHED`
        (`ERR_BASELINE_CYCLE_NOT_PUBLISHED`)."
        PRD §3.8: "Activation pins the `baseline_score`: the unit's published
        adjusted top-box percentage for the domain, read from the baseline
        cycle's `scored_unit_breakdown` and frozen for the life of the
        initiative."

        Design: Difficulty/cross_entity_state_dependency/initiative_activate_gated_by_baseline_cycle_state
        """
        c1, ctx = _scored_cycle_at(api, "P-CE2B", 25, 0)
        c2 = make_cycle(ctx["program"]["id"], label="Q2", cycle_index=2,
                        discharge_window_start="2026-07-01",
                        discharge_window_end="2026-07-31",
                        fielding_start_date="2026-09-01",
                        fielding_end_date="2026-09-30")
        initiative = get_success_data(api.create_initiative(
            create_initiative_payload(
                ctx["unit"]["id"], "OVERALL_RATING", c1["id"], c2["id"],
                target_score=90.0),
            ADMIN))
        # SCORING baseline: rejected, and nothing is pinned.
        validate_error(api.activate_initiative(initiative["id"], ADMIN),
                       ApiErrorId.ERR_BASELINE_CYCLE_NOT_PUBLISHED)
        after = get_initiative(initiative["id"])
        assert after["status"] == "DRAFT"
        assert after["baseline_score"] is None

        # Once the baseline publishes, activation succeeds and pins 100.0.
        get_success_data(api.publish_cycle(c1["id"], ADMIN))
        activated = validate_success(
            api.activate_initiative(initiative["id"], ADMIN), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["baseline_score"] == pytest.approx(100.0, abs=0.001)


class TestHalfOpenWindowAdjacency:
    def _three_cycles_two_published(self, api, name):
        prog_ctx = setup_program(name=name)
        c1 = setup_published_cycle(prog_ctx, 1, "Q1", 25, 0)["cycle"]
        c2 = setup_published_cycle(prog_ctx, 2, "Q2", 25, 0)["cycle"]
        c3 = make_cycle(prog_ctx["program"]["id"], label="Q3", cycle_index=3,
                        discharge_window_start="2026-08-01",
                        discharge_window_end="2026-08-31",
                        fielding_start_date="2026-10-01",
                        fielding_end_date="2026-10-31")
        return prog_ctx, c1, c2, c3

    def test_initiative_half_open_window_adjacency_allowed(self, api):
        """PRD §3.8: "And the half-open window from the baseline index
        (exclusive) through the evaluation index (inclusive) must not intersect
        the corresponding window of any other initiative on the same unit and
        domain whose status is `ACTIVE`, `UNDER_EVALUATION`, or
        `TARGET_MISSED` (`ERR_INITIATIVE_WINDOW_OVERLAP`); mere adjacency,
        where one initiative's evaluation index equals another's baseline
        index, is permitted."

        Design: Difficulty/resource_temporal_overlap/initiative_half_open_window_adjacency_allowed
        """
        prog_ctx, c1, c2, c3 = self._three_cycles_two_published(api, "P-TO2")
        unit_id = prog_ctx["unit"]["id"]
        inx = make_active_initiative(unit_id, "NURSE_COMM", c1["id"],
                                     c2["id"], 90.0)
        iny = get_success_data(api.create_initiative(
            create_initiative_payload(unit_id, "NURSE_COMM", c2["id"],
                                      c3["id"], target_score=90.0),
            ADMIN))
        inz = get_success_data(api.create_initiative(
            create_initiative_payload(unit_id, "NURSE_COMM", c1["id"],
                                      c3["id"], target_score=90.0),
            ADMIN))

        # Y's window (2,3] is adjacent to X's (1,2] at index 2: permitted.
        y_activated = validate_success(
            api.activate_initiative(iny["id"], ADMIN), 200)
        assert y_activated["status"] == "ACTIVE"
        # Z's window (1,3] intersects both X and Y: rejected.
        validate_error(api.activate_initiative(inz["id"], ADMIN),
                       ApiErrorId.ERR_INITIATIVE_WINDOW_OVERLAP)
        assert get_initiative(inz["id"])["status"] == "DRAFT"

    def test_overlapping_window_rejected_while_adjacent_passes(self, api):
        """PRD §3.8: "the half-open window from the baseline index (exclusive)
        through the evaluation index (inclusive) must not intersect the
        corresponding window of any other initiative on the same unit and
        domain whose status is `ACTIVE`, `UNDER_EVALUATION`, or `TARGET_MISSED`
        (`ERR_INITIATIVE_WINDOW_OVERLAP`); mere adjacency, where one
        initiative's evaluation index equals another's baseline index, is
        permitted."

        Design: Difficulty/resource_temporal_overlap/initiative_half_open_window_adjacency_allowed
        """
        prog_ctx, c1, c2, c3 = self._three_cycles_two_published(api, "P-TO2B")
        unit_id = prog_ctx["unit"]["id"]
        make_active_initiative(unit_id, "NURSE_COMM", c1["id"], c2["id"], 90.0)
        # Identical window (1,2] again: true intersection, rejected.
        dup = get_success_data(api.create_initiative(
            create_initiative_payload(unit_id, "NURSE_COMM", c1["id"],
                                      c2["id"], target_score=88.0),
            ADMIN))
        validate_error(api.activate_initiative(dup["id"], ADMIN),
                       ApiErrorId.ERR_INITIATIVE_WINDOW_OVERLAP)
        assert get_initiative(dup["id"])["status"] == "DRAFT"
        # Adjacent (2,3]: permitted.
        adj = get_success_data(api.create_initiative(
            create_initiative_payload(unit_id, "NURSE_COMM", c2["id"],
                                      c3["id"], target_score=88.0),
            ADMIN))
        activated = validate_success(
            api.activate_initiative(adj["id"], ADMIN), 200)
        assert activated["status"] == "ACTIVE"


class TestEvaluationCycleGuards:
    def _published_baseline_ctx(self, api, name):
        prog_ctx = setup_program(name=name)
        c1 = setup_published_cycle(prog_ctx, 1, "Q1", 25, 0)["cycle"]
        return prog_ctx, c1

    def test_invalid_evaluation_cycle_index(self, api):
        """PRD §3.8: "The evaluation cycle must not be `VOIDED` and its
        `cycle_index` must be strictly greater than the baseline cycle's
        (`ERR_INVALID_EVALUATION_CYCLE`)."
        PRD §3.8: "the evaluation-window rules described at activation — index
        ordering and the half-open overlap check — are enforced whenever an
        initiative is created, activated, or replanned."

        Design: Corner/validations/invalid_evaluation_cycle_index
        """
        prog_ctx, c1 = self._published_baseline_ctx(api, "P-V20")
        initiative = get_success_data(api.create_initiative(
            create_initiative_payload(
                prog_ctx["unit"]["id"], "OVERALL_RATING", c1["id"], c1["id"],
                target_score=90.0),
            ADMIN))
        res = api.activate_initiative(initiative["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_EVALUATION_CYCLE)
        assert res.status_code == 422
        assert get_initiative(initiative["id"])["status"] == "DRAFT"

    def test_evaluation_index_must_strictly_exceed_baseline(self, api):
        """PRD §3.8: "The evaluation cycle must not be `VOIDED` and its
        `cycle_index` must be strictly greater than the baseline cycle's
        (`ERR_INVALID_EVALUATION_CYCLE`)."

        Design: Corner/validations/invalid_evaluation_cycle_index
        """
        prog_ctx, c1 = self._published_baseline_ctx(api, "P-V20B")
        # Same index (1 !> 1): rejected.
        same = get_success_data(api.create_initiative(
            create_initiative_payload(
                prog_ctx["unit"]["id"], "OVERALL_RATING", c1["id"], c1["id"],
                target_score=90.0),
            ADMIN))
        validate_error(api.activate_initiative(same["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_EVALUATION_CYCLE)
        # A strictly greater index passes the ordering guard.
        c2 = make_cycle(prog_ctx["program"]["id"], label="Q2", cycle_index=2,
                        discharge_window_start="2026-07-01",
                        discharge_window_end="2026-07-31",
                        fielding_start_date="2026-09-01",
                        fielding_end_date="2026-09-30")
        ok = get_success_data(api.create_initiative(
            create_initiative_payload(
                prog_ctx["unit"]["id"], "OVERALL_RATING", c1["id"], c2["id"],
                target_score=90.0),
            ADMIN))
        activated = validate_success(api.activate_initiative(ok["id"], ADMIN),
                                     200)
        assert activated["status"] == "ACTIVE"


class TestPinnedVsRollingProgress:
    def _three_published_scenario(self, api, name):
        """Cycles idx1/2/3 PUBLISHED with unit CLEANLINESS adjusted
        80.00 / 84.00 / 88.00; initiative (U1, CLEANLINESS, baseline idx1,
        evaluation idx3, target 85.00) ACTIVE before idx3 publishes."""
        prog_ctx = setup_program(name=name)
        c1 = setup_published_cycle(prog_ctx, 1, "Q1", 20, 5)["cycle"]
        c2 = setup_published_cycle(prog_ctx, 2, "Q2", 21, 4)["cycle"]
        c3 = make_cycle(prog_ctx["program"]["id"], label="Q3", cycle_index=3,
                        discharge_window_start="2026-08-01",
                        discharge_window_end="2026-08-31",
                        fielding_start_date="2026-10-01",
                        fielding_end_date="2026-10-31")
        initiative = make_active_initiative(
            prog_ctx["unit"]["id"], "CLEANLINESS", c1["id"], c3["id"], 85.0)
        return prog_ctx, initiative, c3

    def test_initiative_progress_pinned_vs_rolling(self, api):
        """PRD §3.8: "The **pinned** variant, `progress_pinned`, is the current
        value minus the frozen `baseline_score`, rounded half-up to two decimal
        places; it is null until the evaluation cycle publishes. The **rolling**
        variant, `progress_rolling`, measures against the trailing average:
        take the up-to-two most recent `PUBLISHED` cycles of the same program
        whose `cycle_index` is strictly below the evaluation cycle's, ordered
        by `cycle_index` descending with `created_at` descending as tie-break;
        the rolling baseline is the average of the unit's adjusted percentage
        for the domain across those cycles, rounded half-up to two decimal
        places, and is null when no such cycle exists."
        PRD §3.8: "Activation pins the `baseline_score`"

        Design: Difficulty/dual_variant_calc/initiative_progress_pinned_vs_rolling
        """
        prog_ctx, initiative, c3 = self._three_published_scenario(api, "P-DV2")
        assert get_initiative(initiative["id"])["baseline_score"] == (
            pytest.approx(80.0, abs=0.001))

        field_and_publish_cycle(prog_ctx, c3, 22, 3)
        after = get_initiative(initiative["id"])
        assert after["status"] == "TARGET_MET"  # 88.00 >= 85.00
        assert after["progress_pinned"] == pytest.approx(8.0, abs=0.001)
        assert after["progress_rolling"] == pytest.approx(6.0, abs=0.001)

    def test_pinned_and_rolling_diverge_on_same_evaluation(self, api):
        """PRD §3.8: "`progress_rolling` is the current value minus the rolling
        baseline, rounded half-up to two decimal places — the baseline is
        rounded before the subtraction — and is null whenever the rolling
        baseline is null or the evaluation cycle has not published."
        PRD §3.8: "Progress is computed live on read and populates once the
        evaluation cycle is `PUBLISHED`."

        Design: Difficulty/dual_variant_calc/initiative_progress_pinned_vs_rolling
        """
        prog_ctx, initiative, c3 = self._three_published_scenario(api, "P-DV2B")
        # Before the evaluation cycle publishes, both progress fields are null.
        before = get_initiative(initiative["id"])
        assert before["progress_pinned"] is None
        assert before["progress_rolling"] is None

        published = field_and_publish_cycle(prog_ctx, c3, 22, 3)
        assert published["status"] == "PUBLISHED"
        after = get_initiative(initiative["id"])
        assert after["baseline_score"] == pytest.approx(80.0, abs=0.001)
        assert after["progress_pinned"] == pytest.approx(8.0, abs=0.001)
        assert after["progress_rolling"] == pytest.approx(6.0, abs=0.001)
        assert after["status"] == "TARGET_MET"


class TestUnitAbsentScoresZero:
    def _unit_absent_scenario(self, api, name):
        """Baseline idx1 on U1 at 80.00; evaluation idx2's 25 responses are all
        on U2, so U1 is absent from idx2's unit breakdown."""
        prog_ctx = setup_program(name=name)
        unit1 = prog_ctx["unit"]
        unit2 = make_unit(prog_ctx["program"]["id"], name="Unit 2",
                          unit_code="U2")
        c1 = setup_published_cycle(prog_ctx, 1, "Q1", 20, 5)["cycle"]
        c2 = make_cycle(prog_ctx["program"]["id"], label="Q2", cycle_index=2,
                        discharge_window_start="2026-07-01",
                        discharge_window_end="2026-07-31",
                        fielding_start_date="2026-09-01",
                        fielding_end_date="2026-09-30")
        initiative = make_active_initiative(unit1["id"], "CLEANLINESS",
                                            c1["id"], c2["id"], 50.0)
        # Cycle idx2: all 25 discharges attributed to U2.
        get_success_data(api.open_sampling(c2["id"], ADMIN))
        d_ids = import_discharges(
            prog_ctx["program"]["id"], unit2["id"],
            prog_ctx["provider"]["id"], 25, mrn_prefix="C",
            admit_date="2026-07-01", discharge_date="2026-07-03")
        k_ids = import_cases(c2["id"], d_ids, mode_assigned="MAIL")
        get_success_data(api.start_fielding(c2["id"], ADMIN))
        import_responses(k_ids, prog_ctx["vendor"]["id"], mode_used="MAIL",
                         score=4)
        set_clock("2026-09-30T00:00:00Z")
        get_success_data(api.close_fielding(c2["id"], ADMIN))
        get_success_data(api.begin_scoring(c2["id"], ADMIN))
        return initiative, c2

    def test_initiative_evaluation_unit_absent_scores_zero(self, api):
        """PRD §3.8: "When the unit is absent from the cycle's
        `scored_unit_breakdown`, or its breakdown entry shows zero completed
        responses, the current value is treated as 0.0. Meeting or exceeding
        `target_score` lands `TARGET_MET`; falling short lands `TARGET_MISSED`
        and escalates the unit's open tickets in that domain."
        PRD §3.8: "The **pinned** variant, `progress_pinned`, is the current
        value minus the frozen `baseline_score`, rounded half-up to two decimal
        places"

        Design: Corner/calculations/initiative_evaluation_unit_absent_scores_zero
        """
        initiative, c2 = self._unit_absent_scenario(api, "P-CA5")
        get_success_data(api.publish_cycle(c2["id"], ADMIN))

        after = get_initiative(initiative["id"])
        assert after["status"] == "TARGET_MISSED"  # 0.0 < 50.0
        assert after["progress_pinned"] == pytest.approx(-80.0, abs=0.001)

    def test_absent_unit_evaluation_uses_zero_current(self, api):
        """PRD §3.8: "When the unit is absent from the cycle's
        `scored_unit_breakdown`, or its breakdown entry shows zero completed
        responses, the current value is treated as 0.0."
        PRD §3.8: "Activation pins the `baseline_score`: the unit's published
        adjusted top-box percentage for the domain, read from the baseline
        cycle's `scored_unit_breakdown` and frozen for the life of the
        initiative."

        Design: Corner/calculations/initiative_evaluation_unit_absent_scores_zero
        """
        initiative, c2 = self._unit_absent_scenario(api, "P-CA5B")
        assert get_initiative(initiative["id"])["baseline_score"] == (
            pytest.approx(80.0, abs=0.001))
        get_success_data(api.publish_cycle(c2["id"], ADMIN))

        after = get_initiative(initiative["id"])
        assert_initiative(after)
        assert after["status"] == "TARGET_MISSED"
        assert after["progress_pinned"] == pytest.approx(-80.0, abs=0.001)
        assert after["achieved_at"] is None


class TestMissedBranchAndReplanLoop:
    def _missed_scenario(self, api, name):
        """Baseline idx1 PUBLISHED at 80.00; evaluation idx2 publishes at
        84.00 < target 85.00, so the initiative lands TARGET_MISSED; idx3 DRAFT
        stands by as the replan target."""
        prog_ctx = setup_program(name=name)
        c1 = setup_published_cycle(prog_ctx, 1, "Q1", 20, 5)["cycle"]
        c2 = make_cycle(prog_ctx["program"]["id"], label="Q2", cycle_index=2,
                        discharge_window_start="2026-07-01",
                        discharge_window_end="2026-07-31",
                        fielding_start_date="2026-09-01",
                        fielding_end_date="2026-09-30")
        initiative = make_active_initiative(
            prog_ctx["unit"]["id"], "CLEANLINESS", c1["id"], c2["id"], 85.0)
        # Publish the SAME cycle the initiative evaluates: 84.00 < 85.00.
        field_and_publish_cycle(prog_ctx, c2, 21, 4)
        c3 = make_cycle(prog_ctx["program"]["id"], label="Q3", cycle_index=3,
                        discharge_window_start="2026-08-01",
                        discharge_window_end="2026-08-31",
                        fielding_start_date="2026-10-01",
                        fielding_end_date="2026-10-31")
        return initiative, c3

    def test_initiative_missed_branch_and_replan_loop(self, api):
        """PRD §3.6: "when the unit's published adjusted percentage for the
        initiative's domain in this cycle is at least the `target_score` — the
        comparison inclusive, so exactly meeting the target succeeds — the
        initiative lands in `TARGET_MET` and stamps `achieved_at` from the
        clock; otherwise it lands in `TARGET_MISSED`."
        PRD §3.8: "A `ProgramAdmin` replans an initiative in `TARGET_MISSED`
        back to `ACTIVE` (from any other status, `ERR_INVALID_STATE`),
        supplying a replacement `evaluation_cycle_id` and `target_score`; ...
        Replanning resets `progress_pinned` and `progress_rolling` to null and
        leaves the pinned `baseline_score` unchanged."

        Design: Difficulty/non_linear_state_machine/initiative_missed_branch_and_replan_loop
        """
        initiative, c3 = self._missed_scenario(api, "P-NL2")
        missed = get_initiative(initiative["id"])
        assert missed["status"] == "TARGET_MISSED"  # 84.00 < 85.00
        assert missed["baseline_score"] == pytest.approx(80.0, abs=0.001)

        replanned = validate_success(
            api.replan_initiative(
                initiative["id"],
                replan_initiative_payload(c3["id"], 82.0),
                ADMIN),
            200)
        assert replanned["status"] == "ACTIVE"
        assert replanned["evaluation_cycle_id"] == c3["id"]
        assert replanned["target_score"] == pytest.approx(82.0, abs=0.001)
        assert replanned["baseline_score"] == pytest.approx(80.0, abs=0.001)
        assert replanned["progress_pinned"] is None
        assert replanned["progress_rolling"] is None

    def test_replan_resets_progress_but_keeps_baseline(self, api):
        """PRD §3.8: "Replanning resets `progress_pinned` and
        `progress_rolling` to null and leaves the pinned `baseline_score`
        unchanged."
        PRD §3.8: "A missed target is not the end. A `ProgramAdmin` replans an
        initiative in `TARGET_MISSED` back to `ACTIVE`"

        Design: Difficulty/non_linear_state_machine/initiative_missed_branch_and_replan_loop
        """
        initiative, c3 = self._missed_scenario(api, "P-NL2B")
        missed = get_initiative(initiative["id"])
        assert missed["status"] == "TARGET_MISSED"
        # The progress fields populated when idx2 published ...
        assert missed["progress_pinned"] == pytest.approx(4.0, abs=0.001)

        replanned = validate_success(
            api.replan_initiative(
                initiative["id"],
                replan_initiative_payload(c3["id"], 82.0),
                ADMIN),
            200)
        # ... and the replan loop returns to ACTIVE with progress reset.
        assert replanned["status"] == "ACTIVE"
        assert replanned["progress_pinned"] is None
        assert replanned["progress_rolling"] is None
        assert replanned["baseline_score"] == pytest.approx(80.0, abs=0.001)
        assert replanned["evaluation_cycle_id"] == c3["id"]
        assert replanned["target_score"] == pytest.approx(82.0, abs=0.001)
