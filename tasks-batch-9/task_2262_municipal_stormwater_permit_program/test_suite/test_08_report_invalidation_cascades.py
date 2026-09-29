"""Five-level cascades that end at the annual report's return to DRAFT."""

import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_cents,
    assert_deficiency_score,
    assert_penalty_derivation,
    assert_report_invalidated,
)
from test_helpers.test_users import MANAGER_HEADERS


def _auto_action(inspection_id):
    """The single enforcement action the finalize cascade generated."""
    actions, _ = validate_paginated(
        api_client.list_enforcement_actions(
            MANAGER_HEADERS, {"source_inspection_id": inspection_id}
        )
    )
    assert len(actions) == 1, (
        "the finalize cascade must generate exactly one enforcement action, "
        f"got {len(actions)}"
    )
    return actions[0]


class TestInspectionFinalizeReachesTheReport:
    """Score, stop-work, auto notice, ledger, report — one call moves all five."""

    @pytest.fixture
    def compiled_program(self):
        """A COMPILED 2026 report over a site whose inspection is ready to freeze."""
        program = fx.setup_active_program()
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-A-1",
            site_name="SITE-A",
            operator_name="Northline Builders",
            disturbed_acres=1.00,
        )
        inspection = fx.create_esc_inspection(
            site["id"], "2026-07-01", "2026-07-15", rainfall_trigger=True
        )
        fx.add_findings(inspection["id"], ("MINOR", "MINOR", "MINOR", "CRITICAL"))
        report = fx.setup_compiled_report(program["term_id"], "2026-01-01", "2026-12-31")
        return {
            "program": program,
            "term_id": program["term_id"],
            "site": site,
            "inspection_id": inspection["id"],
            "report": report,
        }

    def test_01_the_first_two_levels_are_the_frozen_score_and_the_stopped_site(
        self, compiled_program
    ):
        """Level one freezes 70 points; level two stops the work.

        PRD: "The stop-work order also arrives automatically. When an
        erosion-control inspection is finalized with a `deficiency_score` of 70 or
        more, the site is driven from `ACTIVE_DISTURBANCE` into `STOP_WORK` without
        any operator asking for it: `stop_work_reason` is set to
        `AUTOMATIC_ESC_DEFICIENCY`, `open_deficiency_score` is set to that
        inspection's `deficiency_score`, `stop_work_count` increments by one, and a
        notice of violation is generated as described in §3.6."

        Design: Difficulty/transitive_cascade/inspection_finalize_cascades_five_levels_to_annual_report_invalidation
        """
        finalized = fx.finalize_inspection(compiled_program["inspection_id"])

        assert finalized["status"] == "FINALIZED", "finalization freezes the inspection"
        assert_deficiency_score(finalized, 70, True)

        site = fx.read_site(compiled_program["site"]["id"])
        assert site["field_status"] == "STOP_WORK", "the escalating score stops the work"
        assert site["stop_work_reason"] == "AUTOMATIC_ESC_DEFICIENCY", (
            "the automatic order records its own reason"
        )
        assert site["open_deficiency_score"] == 70, (
            "the site carries the frozen score of the inspection that stopped it"
        )
        assert site["stop_work_count"] == 1, "the automatic order is counted once"

    def test_02_the_third_level_is_an_automatic_notice_at_the_bare_ladder_base(
        self, compiled_program
    ):
        """Level three is a system-issued notice of violation worth 25000 cents.

        PRD: "The automatic action that the finalize cascade generates is the same
        record on a different origin: `action_type` `NOTICE_OF_VIOLATION`,
        `auto_generated` true, `source_inspection_id` set to the inspection that
        triggered it, `issued_by_user_id` recorded as the system rather than an
        operator, and `violation_days` left at its default of 0."

        Design: Difficulty/transitive_cascade/inspection_finalize_cascades_five_levels_to_annual_report_invalidation
        """
        fx.finalize_inspection(compiled_program["inspection_id"])

        action = _auto_action(compiled_program["inspection_id"])

        assert action["auto_generated"] is True, "the cascade's action is auto generated"
        assert action["source_inspection_id"] == compiled_program["inspection_id"], (
            "the action points back at the inspection that triggered it"
        )
        assert action["status"] == "ISSUED", "a generated action starts ISSUED"
        assert_penalty_derivation(
            action,
            action_type="NOTICE_OF_VIOLATION",
            billable_violation_days=0,
            prior_assessed_total_cents=0,
            escalation_multiplier=1.00,
            penalty_cents=25000,
        )

    def test_03_the_fourth_level_is_the_term_penalty_ledger(self, compiled_program):
        """Level four adds the generated 25000 cents to the term's ledger.

        PRD: "Issuance feeds the ledger and the derived counters. The new
        `penalty_cents` is added to the term's `total_assessed_penalty_cents`,
        which may push a `COMPILED` or `CERTIFIED` annual report back to `DRAFT`."

        Design: Difficulty/transitive_cascade/inspection_finalize_cascades_five_levels_to_annual_report_invalidation
        """
        before = fx.read_term(compiled_program["term_id"])
        assert_cents(
            before["total_assessed_penalty_cents"], 0, "total_assessed_penalty_cents"
        )

        fx.finalize_inspection(compiled_program["inspection_id"])

        term = fx.read_term(compiled_program["term_id"])
        assert_cents(
            term["total_assessed_penalty_cents"], 25000, "total_assessed_penalty_cents"
        )

    def test_04_the_fifth_level_drives_the_compiled_report_back_to_draft(
        self, compiled_program
    ):
        """Level five reopens the frozen report and says why.

        PRD: "The invalidation resets `status` to `DRAFT`, clears `compiled_at`,
        `compiled_by_user_id`, `certified_at`, `certified_by_user_id` and
        `certification_statement`, increments `invalidation_count` by one, and
        writes `invalidated_reason` — `POSTURE_CHANGED` when the posture moved,
        `PENALTY_LEDGER_CHANGED` when the penalty total moved."

        Design: Difficulty/transitive_cascade/inspection_finalize_cascades_five_levels_to_annual_report_invalidation
        """
        report_id = compiled_program["report"]["id"]
        assert compiled_program["report"]["status"] == "COMPILED", (
            "the report was frozen before the inspection was finalized"
        )

        fx.finalize_inspection(compiled_program["inspection_id"])

        report = fx.read_report(report_id)
        assert_report_invalidated(report, "PENALTY_LEDGER_CHANGED", 1)

    def test_05_the_cascade_touches_only_the_measure_the_action_belongs_to(
        self, compiled_program
    ):
        """The runoff measure counts the notice; the plan dimension never moves.

        PRD: "For the `CONSTRUCTION_RUNOFF` measure, if `enforcement_count` is two
        or more, the result is `BEHIND`." And: "If `last_progress_reported_at` is
        null and `measurable_goal_actual` is 0, the result is `PENDING`."

        Design: Difficulty/transitive_cascade/inspection_finalize_cascades_five_levels_to_annual_report_invalidation
        """
        fx.finalize_inspection(compiled_program["inspection_id"])

        measure = fx.read_measure(
            compiled_program["program"]["measures"]["CONSTRUCTION_RUNOFF"]["id"]
        )
        assert measure["enforcement_count"] == 1, (
            "the generated notice reaches the construction runoff measure"
        )
        assert measure["goal_status"] == "PENDING", (
            "one action does not trip the gate, and no progress was ever reported"
        )

        term = fx.read_term(compiled_program["term_id"])
        assert term["behind_measure_count"] == 0, "no measure is behind"

        site = fx.read_site(compiled_program["site"]["id"])
        assert site["plan_status"] == "APPROVED", (
            "the automatic stop-work leaves the plan dimension untouched"
        )


class TestSuspectScreeningReachesTheReport:
    """The fourth open case trips the gate, moves the posture and reopens the report."""

    @pytest.fixture
    def three_open_cases(self):
        """Four outfalls, three suspect, a MET measure and a COMPILED report."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01",),
            outfall_overrides={
                "receiving_water": "Mill Creek",
                "drainage_area_acres": 45.00,
                "priority_tier": "HIGH",
                "baseline_concentration_mg_per_l": 0.45,
                "design_runoff_kl": 20000,
                "sweeping_capacity_lane_miles_per_month": 40.00,
            },
        )
        term_id = program["term_id"]
        outfalls = {"OF-01": program["outfalls"]["OF-01"]}
        outfalls["OF-02"] = fx.create_outfall(
            term_id,
            "OF-02",
            receiving_water="Mill Creek",
            drainage_area_acres=22.00,
            priority_tier="MEDIUM",
            baseline_concentration_mg_per_l=0.30,
            design_runoff_kl=12000,
        )
        outfalls["OF-03"] = fx.create_outfall(
            term_id,
            "OF-03",
            receiving_water="Bell Slough",
            drainage_area_acres=18.00,
            priority_tier="MEDIUM",
            baseline_concentration_mg_per_l=0.30,
            design_runoff_kl=9000,
        )
        outfalls["OF-04"] = fx.create_outfall(
            term_id,
            "OF-04",
            receiving_water="Bell Slough",
            drainage_area_acres=30.00,
            priority_tier="LOW",
            baseline_concentration_mg_per_l=0.20,
            design_runoff_kl=15000,
        )
        measure_id = program["measures"]["ILLICIT_DISCHARGE"]["id"]
        fx.report_progress(measure_id, 20)
        fx.record_screening(
            outfalls["OF-01"]["id"],
            "2026-08-01T08:00:00Z",
            suspect=True,
            indicator_bacteria_mpn=5000,
            indicator_surfactant_mg_per_l=0.60,
            indicator_ammonia_mg_per_l=0.20,
        )
        fx.record_screening(
            outfalls["OF-02"]["id"],
            "2026-08-01T09:00:00Z",
            suspect=True,
            indicator_bacteria_mpn=4000,
            indicator_surfactant_mg_per_l=0.10,
            indicator_ammonia_mg_per_l=1.20,
        )
        fx.record_screening(
            outfalls["OF-03"]["id"],
            "2026-08-01T10:00:00Z",
            suspect=True,
            indicator_bacteria_mpn=100,
            indicator_surfactant_mg_per_l=0.80,
            indicator_ammonia_mg_per_l=0.90,
        )
        report = fx.setup_compiled_report(term_id, "2026-01-01", "2026-12-31")
        return {
            "term_id": term_id,
            "outfalls": outfalls,
            "measure_id": measure_id,
            "report": report,
        }

    def test_06_three_open_cases_leave_the_measure_at_its_attainment_band(
        self, three_open_cases
    ):
        """Three is not more than three, so a fully reported measure is still MET.

        PRD: "For the `ILLICIT_DISCHARGE` measure, if `open_case_count` is greater
        than three, the result is `BEHIND`."

        Design: Difficulty/transitive_cascade/suspect_screening_cascades_through_open_case_gate_to_posture_and_report
        """
        measure = fx.read_measure(three_open_cases["measure_id"])
        assert measure["open_case_count"] == 3, "three screenings opened three cases"
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            "20 of 20 reported is full attainment"
        )
        assert measure["goal_status"] == "MET", "the gate is not yet tripped"

        term = fx.read_term(three_open_cases["term_id"])
        assert term["behind_measure_count"] == 0, "no measure is behind"
        assert term["compliance_posture"] == "COMPLIANT", (
            "the report could only be compiled while the posture was clean"
        )
        assert three_open_cases["report"]["status"] == "COMPILED", (
            "the report is frozen before the fourth case is opened"
        )

    def test_07_the_fourth_screening_opens_a_case_on_its_own_outfall(
        self, three_open_cases
    ):
        """The screening writes SUSPECT and the server opens the case itself.

        PRD: "A `SUSPECT` result moves `screening_status` from either
        `NOT_SCREENED` or `CLEAR` to `SUSPECT` and additionally opens a case: the
        server creates an **illicit discharge case** in `OPEN` whose `outfall_id`
        is this outfall and whose `origin_observation_id` is the new observation,
        stamps the case's `opened_at` from the logical clock, raises the outfall's
        `open_case_count` by one, then recomputes the `ILLICIT_DISCHARGE` control
        measure's `open_case_count` and `goal_status`, the term's posture, and —
        where the posture moved and the observation falls inside a closed
        reporting window — the annual report's return to `DRAFT`."

        Design: Difficulty/transitive_cascade/suspect_screening_cascades_through_open_case_gate_to_posture_and_report
        """
        outfall_id = three_open_cases["outfalls"]["OF-04"]["id"]

        observation = fx.record_screening(
            outfall_id,
            "2026-08-02T08:00:00Z",
            suspect=True,
            indicator_bacteria_mpn=9000,
            indicator_surfactant_mg_per_l=0.75,
            indicator_ammonia_mg_per_l=0.20,
        )

        assert observation["screening_result"] == "SUSPECT", (
            "bacteria and surfactant both exceed their limits"
        )
        assert observation["validation_status"] == "NOT_APPLICABLE", (
            "a screening is never adjudicated as a sample"
        )

        outfall = fx.read_outfall(outfall_id)
        assert outfall["screening_status"] == "SUSPECT", "the outfall becomes suspect"
        assert outfall["screening_count"] == 1, "its first screening is counted"
        assert outfall["open_case_count"] == 1, "one case is now open against it"
        assert outfall["last_screened_at"] == "2026-08-02T08:00:00Z", (
            "the visit instant is stamped on the outfall"
        )

        cases, _ = fx._list_cases({"origin_observation_id": observation["id"]})
        assert len(cases) == 1, "exactly one case originates in the new screening"
        assert cases[0]["status"] == "OPEN", "the generated case starts OPEN"

    def test_08_the_fourth_case_trips_the_gate_over_a_fully_attained_measure(
        self, three_open_cases
    ):
        """A measure at 100.00 attainment still reads BEHIND once four cases are open.

        PRD: "The first three tests are compliance **gates**, and a gate wins
        outright: a measure sitting at 125.00 percent attainment is still `BEHIND`
        while its gate is tripped."

        Design: Difficulty/transitive_cascade/suspect_screening_cascades_through_open_case_gate_to_posture_and_report
        """
        fx.record_screening(
            three_open_cases["outfalls"]["OF-04"]["id"],
            "2026-08-02T08:00:00Z",
            suspect=True,
            indicator_bacteria_mpn=9000,
            indicator_surfactant_mg_per_l=0.75,
            indicator_ammonia_mg_per_l=0.20,
        )

        measure = fx.read_measure(three_open_cases["measure_id"])
        assert measure["open_case_count"] == 4, "the census is rebuilt at four"
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            "the reported progress is untouched by the case census"
        )
        assert measure["goal_status"] == "BEHIND", (
            "the open-case gate outranks the attainment band"
        )

    def test_09_the_tripped_gate_moves_the_posture_and_reopens_the_report(
        self, three_open_cases
    ):
        """One behind measure is AT_RISK, and the posture move reopens the report.

        PRD: "Otherwise, if `behind_measure_count` is exactly one, or
        `exceeding_outfall_count` is at least one, it becomes `AT_RISK`. In every
        other case it is `COMPLIANT`."

        Design: Difficulty/transitive_cascade/suspect_screening_cascades_through_open_case_gate_to_posture_and_report
        """
        fx.record_screening(
            three_open_cases["outfalls"]["OF-04"]["id"],
            "2026-08-02T08:00:00Z",
            suspect=True,
            indicator_bacteria_mpn=9000,
            indicator_surfactant_mg_per_l=0.75,
            indicator_ammonia_mg_per_l=0.20,
        )

        term = fx.read_term(three_open_cases["term_id"])
        assert term["behind_measure_count"] == 1, "exactly one measure is behind"
        assert term["exceeding_outfall_count"] == 0, "no load assessment has been run"
        assert term["compliance_posture"] == "AT_RISK", (
            "one behind measure and no exceedance is AT_RISK"
        )

        report = fx.read_report(three_open_cases["report"]["id"])
        assert_report_invalidated(report, "POSTURE_CHANGED", 1)

    def test_10_the_cascade_leaves_the_three_earlier_outfalls_alone(
        self, three_open_cases
    ):
        """Only the screened outfall's own dimension moves.

        PRD: "Every dry-weather screening stamps the outfall's `last_screened_at`
        with the observation's `observed_at` and increments `screening_count` by
        one."

        Design: Difficulty/transitive_cascade/suspect_screening_cascades_through_open_case_gate_to_posture_and_report
        """
        fx.record_screening(
            three_open_cases["outfalls"]["OF-04"]["id"],
            "2026-08-02T08:00:00Z",
            suspect=True,
            indicator_bacteria_mpn=9000,
            indicator_surfactant_mg_per_l=0.75,
            indicator_ammonia_mg_per_l=0.20,
        )

        first = fx.read_outfall(three_open_cases["outfalls"]["OF-01"]["id"])
        assert first["screening_status"] == "SUSPECT", "its own case is still open"
        assert first["screening_count"] == 1, "no second screening was recorded there"
        assert first["last_screened_at"] == "2026-08-01T08:00:00Z", (
            "the earlier outfall keeps its own visit instant"
        )
        assert first["open_case_count"] == 1, "one case per suspect screening"
