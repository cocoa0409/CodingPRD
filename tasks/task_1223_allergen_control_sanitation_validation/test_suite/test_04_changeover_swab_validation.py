"""Changeover execution, swab outcome computation, validation scoring, the
rework/reswab cycle, changeover budgets, and the run-start validation gate."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_allergen, create_line, create_matrix_entry, create_product,
    create_run, schedule_run, create_changeover, create_and_approve_procedure,
    setup_changeover_scenario, setup_swab_pending_changeover,
    drive_changeover_to_swab_pending, record_swab, record_swab_ok,
    get_changeover, get_run, get_line, set_clock,
    assert_changeover,
    MANAGER, SUPERVISOR, OPERATOR,
)


class TestValidationScoreMultiInput:
    """Base 100, on-time bonus, tiered tardy penalty, margin bonus, and the
    invalidated penalty combine into one clamped integer score."""

    def _setup(self):
        return setup_swab_pending_changeover(
            allergen_code="MILK", line_code="LINE-2", sku="P-MILK",
            procedure_code="COP-MILK-V1", changeover_minutes=60,
            min_swab_zones=2, atp_action_level_rlu=150, allergen_action_level_ppm=2.0,
            scheduled_minutes=60, actual_minutes=90, tech_code="TECH-100",
            run_start="2026-06-02T08:00:00Z", run_end="2026-06-02T12:00:00Z")

    def _record_swabs(self, ctx):
        # Margin PASS: 70 <= 0.5 * 150.
        swab1 = record_swab_ok(ctx, zone_code="BELT-A", swab_type="ATP", measured_value=70)
        assert swab1["outcome"] == "PASS"
        # Invalidated outright at recording: not a FAIL.
        swab2 = record_swab_ok(ctx, zone_code="FRAME-3", swab_type="ATP",
                               measured_value=999,
                               invalidated_reason="ZONE_REPLACED_BEFORE_READ")
        assert swab2["outcome"] == "INVALIDATED"
        # Margin PASS: 0.8 <= 0.5 * 2.0. Second distinct PASS zone.
        swab3 = record_swab_ok(ctx, zone_code="HOPPER-1", swab_type="ALLERGEN_ELISA",
                               measured_value=0.8)
        assert swab3["outcome"] == "PASS"

    def test_validation_score_combines_all_terms(self, api):
        """PRD §3.5: "It starts from a base of 100 points. Finishing on time —
        `actual_minutes` at or under `scheduled_minutes` — adds a 5-point bonus.
        Running over subtracts 1 point for each full five-minute block of
        overrun, and that tardy deduction is capped at 20 points no matter how
        long the overrun runs. Each `PASS` swab whose `measured_value` is at
        most half of its `action_level_used` adds a 1-point margin bonus, with
        the total margin bonus capped at 10 points. Each `INVALIDATED` swab
        subtracts 2 points. The final figure is clamped to the inclusive range
        0 through 100 and stored as an integer."

        Design: Difficulty/combinatorial_formula/changeover_validation_score_multi_input_tiered
        """
        ctx = self._setup()
        self._record_swabs(ctx)
        co = get_changeover(ctx["changeover"]["id"])
        # 100 base + 0 on-time (90 > 60) - min(20, floor(30/5)) tardy (-6)
        # + 2 margin (two half-level PASS swabs) - 2 invalidated = 94.
        assert co["validation_score"] == 94, (
            f"Expected 94, got {co['validation_score']}")

    def test_changeover_validates_with_distinct_pass_zones(self, api):
        """PRD §3.5: "Validation requires three conditions together: the count
        of distinct `zone_code` values holding a `PASS` swab reaches the
        procedure's `min_swab_zones`; no swab on the changeover stands at
        `FAIL`; and every ELISA swab required for the procedure's target
        allergen has been recorded with a `PASS`. When all three hold, the
        changeover moves `SWAB_PENDING` → `VALIDATED`".

        Design: Difficulty/combinatorial_formula/changeover_validation_score_multi_input_tiered
        """
        ctx = self._setup()
        self._record_swabs(ctx)
        co = get_changeover(ctx["changeover"]["id"])
        assert co["status"] == "VALIDATED"


class TestChangeoverReworkCycle:
    def _setup(self):
        ctx = setup_swab_pending_changeover(
            allergen_code="SOY", line_code="LINE-4", sku="P-SOY",
            procedure_code="COP-SOY-V1", changeover_minutes=30,
            min_swab_zones=1, atp_action_level_rlu=150, allergen_action_level_ppm=2.0,
            scheduled_minutes=30, actual_minutes=30, tech_code="TECH-200",
            run_start="2026-06-03T08:00:00Z", run_end="2026-06-03T12:00:00Z")
        # 5.5 >= 2.0 action level => FAIL; a single FAIL lands REWORK_REQUIRED.
        ctx["failed_swab"] = record_swab_ok(ctx, zone_code="BELT-A",
                                            swab_type="ALLERGEN_ELISA", measured_value=5.5)
        assert ctx["failed_swab"]["outcome"] == "FAIL"
        return ctx

    def test_single_fail_enters_rework_and_reswab_returns_to_swab_pending(self, api):
        """PRD §3.5: "A single `FAIL` lands the changeover in `REWORK_REQUIRED`
        instead, with the failed zones queued for re-cleaning."
        PRD §3.5: "Recovery from `REWORK_REQUIRED` is the reswab: a
        `LineOperator` moves the changeover back to `SWAB_PENDING` after the
        re-clean (the changeover must be `REWORK_REQUIRED`, failing with
        `ERR_CHANGEOVER_NOT_REWORK`), and every prior `FAIL` swab in the
        re-cleaned zones is marked `INVALIDATED` with `invalidated_reason` set
        to RESWAB, clearing them from the failure count."

        Design: Difficulty/non_linear_state_machine/changeover_rework_cycle_swab_pending_to_rework_and_back
        """
        ctx = self._setup()
        co = get_changeover(ctx["changeover"]["id"])
        assert co["status"] == "REWORK_REQUIRED"

        reswabbed = validate_success(
            api.reswab_changeover(ctx["changeover"]["id"], OPERATOR), 200)
        assert reswabbed["status"] == "SWAB_PENDING"

        old = validate_success(
            api.get_swab_result(ctx["failed_swab"]["id"], SUPERVISOR), 200)
        assert old["outcome"] == "INVALIDATED"
        assert old["invalidated_reason"] == "RESWAB"

    def test_fresh_pass_after_reswab_validates(self, api):
        """PRD §3.5: "When all three hold, the changeover moves `SWAB_PENDING`
        → `VALIDATED`: its `validation_score` is computed, the line's
        `last_validated_changeover_id` is set to this changeover, the line's
        `posture` is recomputed, and the covering gate on the to-run is
        satisfied."

        Design: Difficulty/non_linear_state_machine/changeover_rework_cycle_swab_pending_to_rework_and_back
        """
        ctx = self._setup()
        validate_success(api.reswab_changeover(ctx["changeover"]["id"], OPERATOR), 200)
        swab = record_swab_ok(ctx, zone_code="BELT-A", swab_type="ALLERGEN_ELISA",
                              measured_value=0.5)
        assert swab["outcome"] == "PASS"
        co = get_changeover(ctx["changeover"]["id"])
        assert co["status"] == "VALIDATED"


class TestSwabActionLevelBoundary:
    def test_measured_equal_to_action_level_is_fail(self, api):
        """PRD §2.9: "the comparison is strict in the safety direction: a
        measured value exactly equal to the action level counts as a `FAIL`,
        not a `PASS`."
        PRD §3.5: "The applied threshold, stored as `action_level_used`, is the
        procedure's `atp_action_level_rlu` when the swab is `ATP`, and the
        procedure's `allergen_action_level_ppm` for `ALLERGEN_PROTEIN` and
        `ALLERGEN_ELISA`."

        Design: Difficulty/boundary_precision_check/swab_action_level_exact_equality_is_fail
        """
        ctx = setup_swab_pending_changeover(
            allergen_code="MUSTARD", line_code="LINE-10", sku="P-MUS",
            procedure_code="COP-MUS-V1", changeover_minutes=25,
            min_swab_zones=2, atp_action_level_rlu=150, allergen_action_level_ppm=2.0,
            scheduled_minutes=25, actual_minutes=20, tech_code="TECH-500",
            run_start="2026-06-09T08:00:00Z", run_end="2026-06-09T12:00:00Z")
        # Just-below PASS occupies one zone so the changeover stays SWAB_PENDING.
        below = record_swab_ok(ctx, zone_code="BELT-A", swab_type="ALLERGEN_ELISA",
                               measured_value=1.999)
        assert below["outcome"] == "PASS"
        equal = record_swab_ok(ctx, zone_code="BELT-B", swab_type="ALLERGEN_ELISA",
                               measured_value=2.0)
        assert equal["action_level_used"] == 2.0
        assert equal["outcome"] == "FAIL", (
            "measured_value exactly equal to the action level must FAIL")
        assert get_changeover(ctx["changeover"]["id"])["status"] == "REWORK_REQUIRED"

    def test_measured_just_below_action_level_is_pass(self, api):
        """PRD §3.5: "Otherwise the `outcome` is `PASS` when the
        `measured_value` is strictly below the `action_level_used`, and `FAIL`
        when it equals or exceeds it — an exact hit on the action level is a
        failure."

        Design: Difficulty/boundary_precision_check/swab_action_level_exact_equality_is_fail
        """
        ctx = setup_swab_pending_changeover(
            allergen_code="MUSTARD", line_code="LINE-10B", sku="P-MUS-B",
            procedure_code="COP-MUS-V2", changeover_minutes=25,
            min_swab_zones=1, atp_action_level_rlu=150, allergen_action_level_ppm=2.0,
            scheduled_minutes=25, actual_minutes=20, tech_code="TECH-501",
            run_start="2026-06-09T08:00:00Z", run_end="2026-06-09T12:00:00Z")
        swab = record_swab_ok(ctx, zone_code="BELT-A", swab_type="ALLERGEN_ELISA",
                              measured_value=1.999)
        assert swab["outcome"] == "PASS"
        assert swab["action_level_used"] == 2.0
        assert get_changeover(ctx["changeover"]["id"])["status"] == "VALIDATED"


class TestChangeoverBudget:
    def _setup(self):
        peanut = create_allergen("PEANUT")
        milk = create_allergen("MILK")
        line = create_line("LINE-14", "WET_WASH")
        create_matrix_entry(line["id"], peanut["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=45)
        create_matrix_entry(line["id"], milk["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=60)
        product = create_product("P-BOTH", ["PEANUT", "MILK"])
        procedure = create_and_approve_procedure(peanut["id"], "COP-BOTH-V1",
                                                 min_swab_zones=1)
        run = create_run(line["id"], product["id"],
                         "2026-06-13T08:00:00Z", "2026-06-13T12:00:00Z")
        return line, product, procedure, run

    def test_scheduled_minutes_one_short_rejected(self, api):
        """PRD §3.5: "The budget must be at least the to-run's
        `scheduled_changeover_minutes`; a short budget is rejected with
        `ERR_CHANGEOVER_BUDGET_SHORT` (HTTP 422)."
        PRD §3.4: "The `scheduled_changeover_minutes` are the largest
        `changeover_minutes` among the matrix entries covering the introduced
        allergens on that line, or zero when nothing was introduced."

        Design: Difficulty/resource_temporal_overlap/changeover_budget_aggregate_capacity_minutes
        """
        line, product, procedure, run = self._setup()
        assert run["scheduled_changeover_minutes"] == 60, (
            "max(45, 60) over the introduced allergens must be 60")
        res = api.create_changeover(
            {"line_id": line["id"], "from_run_id": None, "to_run_id": run["id"],
             "procedure_id": procedure["id"], "scheduled_minutes": 59},
            SUPERVISOR)
        validate_error(res, "ERR_CHANGEOVER_BUDGET_SHORT")

    def test_scheduled_minutes_exactly_at_requirement_accepted(self, api):
        """PRD §3.5: "The budget must be at least the to-run's
        `scheduled_changeover_minutes`; a short budget is rejected with
        `ERR_CHANGEOVER_BUDGET_SHORT` (HTTP 422). The changeover is born
        `PLANNED`".

        Design: Difficulty/resource_temporal_overlap/changeover_budget_aggregate_capacity_minutes
        """
        line, product, procedure, run = self._setup()
        res = api.create_changeover(
            {"line_id": line["id"], "from_run_id": None, "to_run_id": run["id"],
             "procedure_id": procedure["id"], "scheduled_minutes": 60},
            SUPERVISOR)
        changeover = validate_success(res, 201)
        assert_changeover(changeover)
        assert changeover["status"] == "PLANNED"


class TestRunStartGatedByValidatedChangeover:
    def _setup(self):
        ctx = setup_swab_pending_changeover(
            allergen_code="PEANUT", line_code="LINE-12", sku="P-NUT2",
            procedure_code="COP-PN2-V1", changeover_minutes=30,
            min_swab_zones=1, atp_action_level_rlu=150, allergen_action_level_ppm=2.0,
            scheduled_minutes=30, actual_minutes=28, tech_code="TECH-600",
            run_start="2026-06-11T08:00:00Z", run_end="2026-06-11T12:00:00Z")
        set_clock("2026-06-11T09:00:00Z")
        return ctx

    def test_start_blocked_until_changeover_validated(self, api):
        """PRD §3.4: "a run flagged `changeover_required` may only start once
        its covering changeover stands at `VALIDATED`
        (`ERR_CHANGEOVER_NOT_VALIDATED`)".

        Design: Difficulty/cross_entity_state_dependency/run_start_gated_by_changeover_validated_state
        """
        ctx = self._setup()
        res = api.start_run(ctx["run"]["id"], OPERATOR)
        validate_error(res, "ERR_CHANGEOVER_NOT_VALIDATED")

        swab = record_swab_ok(ctx, zone_code="BELT-A", swab_type="ALLERGEN_ELISA",
                              measured_value=0.3)
        assert swab["outcome"] == "PASS"
        assert get_changeover(ctx["changeover"]["id"])["status"] == "VALIDATED"

        started = validate_success(api.start_run(ctx["run"]["id"], OPERATOR), 200)
        assert started["status"] == "IN_PROGRESS"

    def test_start_consumes_changeover_and_updates_line_pointer(self, api):
        """PRD §3.4: "A successful start consumes the covering changeover,
        linking it to the run, and refreshes the line's
        `last_validated_changeover_id` with the changeover that was just
        consumed."

        Design: Difficulty/cross_entity_state_dependency/run_start_gated_by_changeover_validated_state
        """
        ctx = self._setup()
        record_swab_ok(ctx, zone_code="BELT-A", swab_type="ALLERGEN_ELISA",
                       measured_value=0.3)
        validate_success(api.start_run(ctx["run"]["id"], OPERATOR), 200)
        line = get_line(ctx["line"]["id"])
        assert line["last_validated_changeover_id"] == ctx["changeover"]["id"]


class TestValidationScoreOnTimeClamp:
    def test_on_time_full_margin_clamps_to_100(self, api):
        """PRD §3.5: "It starts from a base of 100 points. Finishing on time —
        `actual_minutes` at or under `scheduled_minutes` — adds a 5-point
        bonus."
        PRD §3.5: "Each `PASS` swab whose `measured_value` is at most half of
        its `action_level_used` adds a 1-point margin bonus, with the total
        margin bonus capped at 10 points."
        PRD §3.5: "The final figure is clamped to the inclusive range 0 through
        100 and stored as an integer."

        Design: Corner/calculations/changeover_validation_score_on_time_full_margin
        """
        ctx = setup_swab_pending_changeover(
            allergen_code="WHEAT", line_code="LINE-C1", sku="P-C1",
            procedure_code="COP-C1", changeover_minutes=30,
            min_swab_zones=3, atp_action_level_rlu=100, allergen_action_level_ppm=2.0,
            scheduled_minutes=30, actual_minutes=30, tech_code="TECH-C1",
            run_start="2026-06-01T08:00:00Z", run_end="2026-06-01T10:00:00Z")
        record_swab_ok(ctx, zone_code="Z1", swab_type="ATP", measured_value=40)
        record_swab_ok(ctx, zone_code="Z2", swab_type="ATP", measured_value=45)
        record_swab_ok(ctx, zone_code="Z3", swab_type="ALLERGEN_ELISA", measured_value=0.5)
        co = get_changeover(ctx["changeover"]["id"])
        # 100 + 5 on-time + 3 margin = 108, clamped to 100.
        assert co["status"] == "VALIDATED"
        assert co["validation_score"] == 100


class TestChangeoverTerminalLockdown:
    def test_cancel_validated_changeover_rejected(self, api):
        """PRD §3.5: "a `QaSupervisor` may cancel a changeover standing at
        `PLANNED` or `IN_EXECUTION` — anything more advanced is terminal for
        this purpose and rejected with `ERR_CHANGEOVER_TERMINAL`".

        Design: Corner/state_machines/changeover_terminal_cancel_rejected
        """
        ctx = setup_swab_pending_changeover(
            allergen_code="EGG", line_code="LINE-S2", sku="P-S2",
            procedure_code="COP-S2", changeover_minutes=10,
            min_swab_zones=1, atp_action_level_rlu=150, allergen_action_level_ppm=2.0,
            scheduled_minutes=10, actual_minutes=10, tech_code="TECH-S2",
            run_start="2026-06-01T08:00:00Z", run_end="2026-06-01T10:00:00Z")
        record_swab_ok(ctx, zone_code="Z1", swab_type="ATP", measured_value=50)
        res = api.cancel_changeover(ctx["changeover"]["id"], SUPERVISOR)
        validate_error(res, "ERR_CHANGEOVER_TERMINAL")


class TestSwabStateGate:
    def test_swab_on_planned_changeover_rejected(self, api):
        """PRD §3.5: "Swab evidence then accumulates against the `SWAB_PENDING`
        changeover — a swab recorded against a changeover in any other state is
        rejected with `ERR_SWAB_NOT_PENDING` (HTTP 409)."

        Design: Corner/entities/swab_result_computed_fields_ignore_input_outcome
        """
        ctx = setup_changeover_scenario(
            allergen_code="SOY", line_code="LINE-T3", sku="P-T3",
            procedure_code="COP-T3", changeover_minutes=10,
            min_swab_zones=1, tech_code="TECH-T3",
            run_start="2026-06-01T08:00:00Z", run_end="2026-06-01T10:00:00Z",
            schedule_the_run=False)
        assert ctx["changeover"]["status"] == "PLANNED"
        res = record_swab(ctx, zone_code="Z1", swab_type="ATP", measured_value=10)
        validate_error(res, "ERR_SWAB_NOT_PENDING")


class TestTechnicianCertificationGate:
    def test_expired_certification_rejected_at_recording(self, api):
        """PRD §3.5: "must hold a current certification covering the
        procedure's target allergen, meaning the allergen appears in the
        technician's `certified_allergen_ids` and the logical clock has not
        passed `certification_expiry_utc`, failing with `ERR_TECH_NOT_CERTIFIED`
        (HTTP 403) otherwise."
        PRD §2.4: "any swab recorded after the technician's
        `certification_expiry_utc` is rejected at recording time."

        Design: Corner/validations/tech_certification_expired_swab_rejected
        """
        allergen = create_allergen("SOY")
        line = create_line("LINE-V5", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=10)
        product = create_product("P-V5", ["SOY"])
        procedure = create_and_approve_procedure(allergen["id"], "COP-V5",
                                                 min_swab_zones=1)
        from test_helpers import create_technician
        tech = create_technician("TECH-V5", [allergen["id"]],
                                 certification_expiry_utc="2026-06-01T00:00:00Z")
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        changeover = create_changeover(line["id"], run["id"], procedure["id"], 10)
        schedule_run(run)
        validate_success(api.begin_changeover(changeover["id"], OPERATOR), 200)
        validate_success(
            api.finish_changeover_execution(changeover["id"], {"actual_minutes": 10},
                                            OPERATOR), 200)
        # Advance the logical clock beyond the certification expiry.
        set_clock("2026-07-01T00:00:00Z")
        from test_helpers import make_qa_technician_headers
        res = api.record_swab_result(
            changeover["id"],
            {"zone_code": "Z1", "swab_type": "ATP", "measured_value": 50,
             "recorded_by_id": tech["id"]},
            make_qa_technician_headers(tech["id"]))
        validate_error(res, "ERR_TECH_NOT_CERTIFIED")
