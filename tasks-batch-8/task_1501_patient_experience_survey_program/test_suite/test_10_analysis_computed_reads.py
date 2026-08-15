"""Computed reads over the scored snapshot: attribution report, star rating
gating, the VBP what-if projection (pinned rounding order, no persistence),
and mode-transition analysis (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_scored_snapshot,
    get_cycle,
    get_success_data,
    import_cases,
    import_discharges,
    import_responses,
    make_cycle,
    make_provider,
    make_unit,
    make_vendor_headers,
    record_response,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    setup_published_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAttributionReport:
    def _two_unit_scored_cycle(self, api, name):
        """Cycle SCORING: 15 all-4 MAIL cases on U1/P1, and 8 all-4 + 2 all-3
        MAIL cases on U2/P2 (adjusted overall: U1 100.00, P2 80.00)."""
        prog_ctx = setup_program(name=name)
        unit1 = prog_ctx["unit"]
        provider1 = prog_ctx["provider"]
        unit2 = make_unit(prog_ctx["program"]["id"], name="Unit 2",
                          unit_code="U2")
        provider2 = make_provider(prog_ctx["program"]["id"], full_name="Dr B",
                                  npi="NPI2", specialty="CARD")
        cycle = make_cycle(prog_ctx["program"]["id"], label="Q1",
                           cycle_index=1)
        get_success_data(api.open_sampling(cycle["id"], ADMIN))
        d_a = import_discharges(
            prog_ctx["program"]["id"], unit1["id"], provider1["id"], 15,
            mrn_prefix="A")
        d_b = import_discharges(
            prog_ctx["program"]["id"], unit2["id"], provider2["id"], 8,
            mrn_prefix="B")
        d_c = import_discharges(
            prog_ctx["program"]["id"], unit2["id"], provider2["id"], 2,
            mrn_prefix="C")
        k_a = import_cases(cycle["id"], d_a)
        k_b = import_cases(cycle["id"], d_b)
        k_c = import_cases(cycle["id"], d_c)
        get_success_data(api.start_fielding(cycle["id"], ADMIN))
        import_responses(k_a, prog_ctx["vendor"]["id"], mode_used="MAIL",
                         score=4)
        import_responses(k_b, prog_ctx["vendor"]["id"], mode_used="MAIL",
                         score=4)
        import_responses(k_c, prog_ctx["vendor"]["id"], mode_used="MAIL",
                         score=3)
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(cycle["id"], ADMIN))
        get_success_data(api.begin_scoring(cycle["id"], ADMIN))
        return cycle, unit1, provider2

    def test_attribution_report_unit_and_provider(self, api):
        """PRD §3.6: "The identical formula produces the program-level
        composites, the per-unit entries (grouping by the case's `unit_id`),
        and the per-provider entries (grouping by `provider_id`)."
        PRD §3.6: "The caller supplies exactly one of `unit_id` or
        `provider_id` to choose the reporting scope, and the report returns the
        `cycle_id`, the `scope`, the `subject_id`, and that subject's
        `completed_responses`, `raw_pcts`, and `adjusted_pcts` — the per-unit
        or per-provider entry frozen at begin-scoring."

        Design: Corner/endpoints/attribution_report_unit_and_provider
        """
        cycle, unit1, provider2 = self._two_unit_scored_cycle(api, "P-EP3")

        unit_report = validate_success(
            api.get_attribution_report(cycle["id"], ADMIN,
                                       params={"unit_id": unit1["id"]}),
            200)
        assert unit_report["cycle_id"] == cycle["id"]
        assert unit_report["scope"] == "UNIT"
        assert unit_report["subject_id"] == unit1["id"]
        assert unit_report["completed_responses"] == 15
        assert unit_report["adjusted_pcts"]["overall_rating"] == (
            pytest.approx(100.0, abs=0.001))

        provider_report = validate_success(
            api.get_attribution_report(cycle["id"], ADMIN,
                                       params={"provider_id": provider2["id"]}),
            200)
        assert provider_report["scope"] == "PROVIDER"
        assert provider_report["subject_id"] == provider2["id"]
        assert provider_report["completed_responses"] == 10
        assert provider_report["adjusted_pcts"]["overall_rating"] == (
            pytest.approx(80.0, abs=0.001))

        res = api.get_attribution_report(cycle["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_attribution_report_requires_exactly_one_scope(self, api):
        """PRD §3.6: "The caller supplies exactly one of `unit_id` or
        `provider_id` to choose the reporting scope, and the report returns the
        `cycle_id`, the `scope`, the `subject_id`, and that subject's
        `completed_responses`, `raw_pcts`, and `adjusted_pcts` — the per-unit
        or per-provider entry frozen at begin-scoring."
        PRD §2.6: "5. **Request shape.** Required fields present, unknown
        fields rejected, types correct, enum members valid, dates ISO-formatted,
        composite scores within 1 to 4 (`ERR_INVALID_REQUEST`)."

        Design: Corner/endpoints/attribution_report_unit_and_provider
        """
        cycle, unit1, provider2 = self._two_unit_scored_cycle(api, "P-EP3B")
        # No scope id: rejected at request-shape validation.
        validate_error(api.get_attribution_report(cycle["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_REQUEST)
        # Both scope ids: also not "exactly one".
        validate_error(
            api.get_attribution_report(
                cycle["id"], ADMIN,
                params={"unit_id": unit1["id"],
                        "provider_id": provider2["id"]}),
            ApiErrorId.ERR_INVALID_REQUEST)
        # The well-formed single-scope calls succeed.
        unit_report = validate_success(
            api.get_attribution_report(cycle["id"], ADMIN,
                                       params={"unit_id": unit1["id"]}),
            200)
        assert unit_report["scope"] == "UNIT"
        assert unit_report["adjusted_pcts"]["overall_rating"] == (
            pytest.approx(100.0, abs=0.001))

    def test_attribution_requires_scoring_posture(self, api):
        """PRD §3.6: "The same snapshot powers the attribution report, likewise
        available only while the cycle is `SCORING` or `PUBLISHED` (otherwise
        `ERR_CYCLE_NOT_SCORED`)."

        Design: Corner/endpoints/attribution_requires_scoring_posture
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-EP4"), "FIELDING", discharge_count=1)
        res = api.get_attribution_report(
            ctx["cycle"]["id"], ADMIN, params={"unit_id": ctx["unit"]["id"]})
        validate_error(res, ApiErrorId.ERR_CYCLE_NOT_SCORED)

    def test_attribution_report_gated_before_scoring(self, api):
        """PRD §2.7: "Star ratings, attribution reports, and value-based
        purchasing projections are available only once a cycle has reached
        `SCORING` or `PUBLISHED`"
        PRD §3.6: "The same snapshot powers the attribution report, likewise
        available only while the cycle is `SCORING` or `PUBLISHED` (otherwise
        `ERR_CYCLE_NOT_SCORED`)."

        Design: Corner/endpoints/attribution_requires_scoring_posture
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-EP4B"), "FIELDING", discharge_count=1)
        validate_error(
            api.get_attribution_report(
                ctx["cycle"]["id"], ADMIN,
                params={"unit_id": ctx["unit"]["id"]}),
            ApiErrorId.ERR_CYCLE_NOT_SCORED)
        assert get_cycle(ctx["cycle"]["id"])["status"] == "FIELDING"


class TestVbpProjection:
    def _scored_all4_cycle(self, api, name):
        ctx = setup_cycle_in_state(
            setup_program(name=name), "FIELDING", discharge_count=25)
        import_responses(ctx["case_ids"], ctx["vendor"]["id"],
                         mode_used="MAIL", score=4)
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))
        return get_cycle(ctx["cycle"]["id"])

    def test_vbp_per_composite_rounding_order(self, api):
        """PRD §3.7: "Each composite converts its percentage to points by
        subtracting the floor of 50.0, dividing by the span from the floor to
        the 95.0 benchmark, and multiplying by the 10 points available per
        composite; the result is rounded half-up to a whole number and clamped
        to the range 0 through 10. The rounding order is pinned: each
        composite's points are rounded before summing, and summing unrounded
        values is forbidden because the two orders disagree."
        PRD §3.7: "the `vbp_adjustment_pct` is that total divided by 40 and
        multiplied by the maximum adjustment of 2.0 percent, rounded half-up to
        two decimal places."

        Design: Difficulty/combinatorial_formula/vbp_per_composite_rounding_order
        """
        cycle = self._scored_all4_cycle(api, "P-CF2")
        projection = validate_success(
            api.create_vbp_projection(
                cycle["id"],
                {"nurse_comm_pct": 74.75, "doctor_comm_pct": 70.25,
                 "cleanliness_pct": 65.15, "overall_rating_pct": 80.0},
                ADMIN),
            200)
        # Per-composite round-half-up to integer: 5.5->6, 4.5->5, 3.3667->3,
        # 6.6667->7. Sum-then-round of the raw points (20.03) would give 20.
        assert projection["composite_points"] == {
            "nurse_comm": 6, "doctor_comm": 5, "cleanliness": 3,
            "overall_rating": 7,
        }
        assert projection["total_points"] == 21
        assert projection["vbp_adjustment_pct"] == pytest.approx(1.05,
                                                                 abs=0.001)

    def test_vbp_pinned_rounding_order_diverges_from_sum_then_round(self, api):
        """PRD §3.7: "The rounding order is pinned: each composite's points are
        rounded before summing, and summing unrounded values is forbidden
        because the two orders disagree."
        PRD §2.9: "Where a calculation produces per-line values that are later
        summed (the VBP projection), each line is rounded to a whole number
        before the sum; the rounding order is part of the contract."

        Design: Difficulty/combinatorial_formula/vbp_per_composite_rounding_order
        """
        cycle = self._scored_all4_cycle(api, "P-CF2B")
        projection = validate_success(
            api.create_vbp_projection(
                cycle["id"],
                {"nurse_comm_pct": 74.75, "doctor_comm_pct": 70.25,
                 "cleanliness_pct": 65.15, "overall_rating_pct": 80.0},
                ADMIN),
            200)
        assert projection["composite_points"]["nurse_comm"] == 6
        assert projection["composite_points"]["doctor_comm"] == 5
        assert projection["composite_points"]["cleanliness"] == 3
        assert projection["composite_points"]["overall_rating"] == 7
        assert projection["total_points"] == 21
        # round-then-sum gives 21 -> 1.05; the forbidden sum-then-round order
        # would give 20 -> 1.00 on identical inputs.
        assert projection["vbp_adjustment_pct"] == pytest.approx(1.05,
                                                                 abs=0.001)

    def test_vbp_projection_has_no_persistence(self, api):
        """PRD §3.7: "The VBP projection is a what-if model over the scored
        snapshot, run by a `ProgramAdmin` while the cycle is `SCORING` or
        `PUBLISHED` (otherwise `ERR_CYCLE_NOT_SCORED`); it persists nothing."
        PRD §3.7: "The request may carry per-composite percentage overrides —
        `nurse_comm_pct`, `doctor_comm_pct`, `cleanliness_pct`,
        `overall_rating_pct` — and each composite's percentage is the override
        when supplied, else the snapshot's adjusted value."

        Design: Corner/endpoints/vbp_projection_has_no_persistence
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-EP7"), "FIELDING", discharge_count=1)
        cycle_id = ctx["cycle"]["id"]
        record_response(ctx["case_ids"][0], ctx["vendor"]["id"])
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(cycle_id, ADMIN))
        scored = get_success_data(api.begin_scoring(cycle_id, ADMIN))
        version_after_scoring = scored["version"]

        projection = validate_success(
            api.create_vbp_projection(cycle_id, {"nurse_comm_pct": 55.0},
                                      ADMIN),
            200)
        # nurse override 55.0 -> round_half_up((55-50)/45*10) = 1; the other
        # three composites keep their snapshot value 100.0 -> 10 points each.
        assert projection["composite_points"]["nurse_comm"] == 1
        assert projection["total_points"] == 31
        assert projection["vbp_adjustment_pct"] == pytest.approx(1.55,
                                                                 abs=0.001)

        after = get_cycle(cycle_id)
        for key in ("nurse_comm", "doctor_comm", "cleanliness",
                    "overall_rating"):
            assert after["scored_adjusted_composite_pcts"][key] == (
                pytest.approx(100.0, abs=0.001)), key
        assert after["version"] == version_after_scoring

    def test_vbp_projection_leaves_snapshot_untouched(self, api):
        """PRD §3.7: "The VBP projection is a what-if model over the scored
        snapshot, run by a `ProgramAdmin` while the cycle is `SCORING` or
        `PUBLISHED` (otherwise `ERR_CYCLE_NOT_SCORED`); it persists nothing."
        PRD §3.7: "The projection returns `cycle_id`, the per-composite
        `composite_points`, `total_points`, and `vbp_adjustment_pct`."

        Design: Corner/endpoints/vbp_projection_has_no_persistence
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-EP7B"), "FIELDING", discharge_count=1)
        cycle_id = ctx["cycle"]["id"]
        record_response(ctx["case_ids"][0], ctx["vendor"]["id"])
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(cycle_id, ADMIN))
        get_success_data(api.begin_scoring(cycle_id, ADMIN))
        before = get_cycle(cycle_id)

        projection = validate_success(
            api.create_vbp_projection(cycle_id, {"nurse_comm_pct": 55.0},
                                      ADMIN),
            200)
        assert projection["cycle_id"] == cycle_id
        assert projection["composite_points"]["nurse_comm"] == 1
        assert projection["total_points"] == 31
        assert projection["vbp_adjustment_pct"] == pytest.approx(1.55,
                                                                 abs=0.001)

        after = get_cycle(cycle_id)
        assert after["scored_adjusted_composite_pcts"] == (
            before["scored_adjusted_composite_pcts"])
        assert after["version"] == before["version"]
        assert after["status"] == "SCORING"


class TestModeTransitionAnalysis:
    def test_mode_transition_requires_published_cycles(self, api):
        """PRD §3.7: "Mode-transition analysis compares the cycle in the path
        against another cycle supplied via `compare_to_cycle_id`; both must be
        `PUBLISHED` (`ERR_CYCLE_NOT_PUBLISHED`) and belong to the same program
        (`ERR_CROSS_PROGRAM_REFERENCE`)."

        Design: Corner/endpoints/mode_transition_requires_published_cycles
        """
        program = get_success_data(api.create_program(
            {"name": "P-EP5", "sampling_protocol": "CENSUS",
             "admin_mode": "MAIL_ONLY"},
            ADMIN))
        c1 = make_cycle(program["id"], label="Q1", cycle_index=1)
        c2 = make_cycle(program["id"], label="Q2", cycle_index=2,
                        discharge_window_start="2026-07-01",
                        discharge_window_end="2026-07-31",
                        fielding_start_date="2026-09-01",
                        fielding_end_date="2026-09-30")
        res = api.get_mode_transition_analysis(
            c2["id"], ADMIN, params={"compare_to_cycle_id": c1["id"]})
        validate_error(res, ApiErrorId.ERR_CYCLE_NOT_PUBLISHED)

    def test_mode_transition_gated_on_both_cycles_published(self, api):
        """PRD §2.7: "mode-transition analysis compares two `PUBLISHED`
        cycles."
        PRD §3.7: "both must be `PUBLISHED` (`ERR_CYCLE_NOT_PUBLISHED`) and
        belong to the same program (`ERR_CROSS_PROGRAM_REFERENCE`)."

        Design: Corner/endpoints/mode_transition_requires_published_cycles
        """
        prog_ctx = setup_program(name="P-EP5B")
        published = setup_published_cycle(prog_ctx, 1, "Q1", 25, 0)["cycle"]
        draft = make_cycle(prog_ctx["program"]["id"], label="Q2",
                           cycle_index=2,
                           discharge_window_start="2026-07-01",
                           discharge_window_end="2026-07-31",
                           fielding_start_date="2026-09-01",
                           fielding_end_date="2026-09-30")
        # Path cycle PUBLISHED, comparison still DRAFT: rejected.
        validate_error(
            api.get_mode_transition_analysis(
                published["id"], ADMIN,
                params={"compare_to_cycle_id": draft["id"]}),
            ApiErrorId.ERR_CYCLE_NOT_PUBLISHED)
        # Path cycle DRAFT: rejected too.
        validate_error(
            api.get_mode_transition_analysis(
                draft["id"], ADMIN,
                params={"compare_to_cycle_id": published["id"]}),
            ApiErrorId.ERR_CYCLE_NOT_PUBLISHED)

    def _two_published_mode_cycles(self, api, name):
        """Cycle A (idx1): 25 PHONE all-4 -> raw 100.0 / adjusted 0.0.
        Cycle B (idx2): 20 all-4 + 5 all-3 MAIL -> raw 80.0 / adjusted 80.0."""
        prog_ctx = setup_program(name=name, admin_mode="MIXED_MODE")
        cycle_a = setup_published_cycle(
            prog_ctx, 1, "Q1", 25, 0, mode_used="PHONE",
            mode_assigned="PHONE")["cycle"]
        cycle_b = setup_published_cycle(
            prog_ctx, 2, "Q2", 20, 5, mode_used="MAIL",
            mode_assigned="MAIL")["cycle"]
        return cycle_a, cycle_b

    def test_mode_transition_analysis_computation(self, api):
        """PRD §3.7: "A cycle's mode share is the fraction of its counted
        responses — those in `ACCEPTED` or `INCLUDED` — that were collected in
        a given mode. The analysis returns `mail_share_delta` and
        `phone_share_delta`, each the path cycle's share minus the comparison
        cycle's share, rounded half-up to four decimal places;
        `raw_overall_delta` and `adjusted_overall_delta`, the differences
        between the two cycles' raw and adjusted overall-rating percentages,
        rounded half-up to two decimal places; and `mode_effect_delta`, built
        from each cycle's mode effect — its raw overall-rating percentage
        minus its adjusted one, the percentage points of top-box inflation
        attributable to mode mix — taking the path cycle's mode effect minus
        the comparison cycle's, rounded half-up to two decimal places."

        Design: Corner/endpoints/mode_transition_analysis_computation
        """
        cycle_a, cycle_b = self._two_published_mode_cycles(api, "P-EP6")
        analysis = validate_success(
            api.get_mode_transition_analysis(
                cycle_b["id"], ADMIN,
                params={"compare_to_cycle_id": cycle_a["id"]}),
            200)
        assert analysis["cycle_id"] == cycle_b["id"]
        assert analysis["compare_to_cycle_id"] == cycle_a["id"]
        assert analysis["mail_share_delta"] == pytest.approx(1.0, abs=1e-4)
        assert analysis["phone_share_delta"] == pytest.approx(-1.0, abs=1e-4)
        assert analysis["raw_overall_delta"] == pytest.approx(-20.0, abs=0.001)
        assert analysis["adjusted_overall_delta"] == pytest.approx(
            80.0, abs=0.001)
        assert analysis["mode_effect_delta"] == pytest.approx(-100.0,
                                                              abs=0.001)

    def test_mode_transition_analysis_deltas(self, api):
        """PRD §3.7: "The analysis returns `mail_share_delta` and
        `phone_share_delta`, each the path cycle's share minus the comparison
        cycle's share, rounded half-up to four decimal places"
        PRD §3.7: "The response carries `cycle_id`, `compare_to_cycle_id`, and
        the five deltas."

        Design: Corner/endpoints/mode_transition_analysis_computation
        """
        cycle_a, cycle_b = self._two_published_mode_cycles(api, "P-EP6B")
        analysis = validate_success(
            api.get_mode_transition_analysis(
                cycle_b["id"], ADMIN,
                params={"compare_to_cycle_id": cycle_a["id"]}),
            200)
        # B all-MAIL vs A all-PHONE: shares swing fully.
        assert analysis["mail_share_delta"] == pytest.approx(1.0, abs=1e-4)
        assert analysis["phone_share_delta"] == pytest.approx(-1.0, abs=1e-4)
        # Raw: 80.00 - 100.00; adjusted: 80.00 - 0.00 (PHONE raw-4 adjusts to
        # 3.5 and does not count in A's adjusted view).
        assert analysis["raw_overall_delta"] == pytest.approx(-20.0, abs=0.001)
        assert analysis["adjusted_overall_delta"] == pytest.approx(
            80.0, abs=0.001)
        # Mode effect: A inflates 100pp (100 raw - 0 adjusted), B inflates 0pp.
        assert analysis["mode_effect_delta"] == pytest.approx(-100.0,
                                                              abs=0.001)
