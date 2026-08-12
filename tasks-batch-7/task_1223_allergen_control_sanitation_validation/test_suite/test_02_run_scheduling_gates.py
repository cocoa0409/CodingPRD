"""Production run scheduling: introduced-allergen baselines, schedule gates,
and schedule/unschedule cycles."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_allergen, create_line, create_matrix_entry, create_product,
    create_run, schedule_run, create_changeover, create_and_approve_procedure,
    create_production_run_payload, set_clock, get_line_version,
    MANAGER, SUPERVISOR, OPERATOR,
)


def _schedule_raw(run_id, line_id):
    """Schedule attempt with a fresh OCC token; returns the raw response."""
    return api_client.schedule_run(
        run_id, {"expected_line_version": get_line_version(line_id)}, SUPERVISOR)


class TestIntroducedAllergensDualBaseline:
    """Optimistic preview at creation vs strict baseline at schedule."""

    def _setup(self):
        allergen = create_allergen("PEANUT")
        create_allergen("MILK")
        line = create_line("LINE-1", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=45)
        prod_nut = create_product("P-NUT", ["PEANUT"], rework_class="SAME_INTO_SAME")
        procedure = create_and_approve_procedure(allergen["id"], "COP-PEANUT-V1",
                                                 min_swab_zones=1)
        run1 = create_run(line["id"], prod_nut["id"],
                          "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z")
        create_changeover(line["id"], run1["id"], procedure["id"], 45)
        run1 = schedule_run(run1)
        run2 = create_run(line["id"], prod_nut["id"],
                          "2026-06-01T13:00:00Z", "2026-06-01T17:00:00Z")
        return line, run1, run2

    def test_optimistic_preview_empty_then_strict_introduces_peanut(self, api):
        """PRD §3.4: "At creation time the preview is *optimistic*: runs still
        sitting in `SCHEDULED` are counted in the baseline set as though they
        will complete, so an immediately preceding scheduled run already
        contributes its allergens to the preview."
        PRD §3.4: "On success, `introduced_allergens` are recomputed under the
        *strict* variant — the baseline now counts only runs that are actually
        `COMPLETED` or `IN_PROGRESS`, so a predecessor still sitting in
        `SCHEDULED` does not contribute its allergens".

        Design: Difficulty/dual_variant_calc/run_introduced_allergens_optimistic_vs_strict_baseline
        """
        line, run1, run2 = self._setup()
        assert run1["status"] == "SCHEDULED"
        # Creation preview: the still-SCHEDULED predecessor contributes PEANUT.
        assert run2["introduced_allergens"] == [], (
            f"Optimistic preview must treat the SCHEDULED predecessor as baseline; "
            f"got {run2['introduced_allergens']}")

        scheduled = validate_success(_schedule_raw(run2["id"], line["id"]), 200)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["introduced_allergens"] == ["PEANUT"], (
            f"Strict recompute must exclude the still-SCHEDULED predecessor; "
            f"got {scheduled['introduced_allergens']}")

    def test_strict_recompute_sets_changeover_required_and_minutes(self, api):
        """PRD §3.4: "Otherwise, if any introduced allergen is mapped
        `REQUIRES_CHANGEOVER`, the changeover is required."
        PRD §3.4: "The `scheduled_changeover_minutes` are the largest
        `changeover_minutes` among the matrix entries covering the introduced
        allergens on that line, or zero when nothing was introduced."

        Design: Difficulty/dual_variant_calc/run_introduced_allergens_optimistic_vs_strict_baseline
        """
        line, run1, run2 = self._setup()
        assert run2["changeover_required"] is False
        scheduled = validate_success(_schedule_raw(run2["id"], line["id"]), 200)
        assert scheduled["changeover_required"] is True
        assert scheduled["scheduled_changeover_minutes"] == 45


class TestScheduleUnscheduleCycle:
    def _setup(self):
        allergen = create_allergen("WHEAT")
        line = create_line("LINE-5", "DRY_CLEAN")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=40)
        product = create_product("P-WHEAT", ["WHEAT"])
        procedure = create_and_approve_procedure(allergen["id"], "COP-WHEAT-V1",
                                                 method="DRY_SCRAPE", min_swab_zones=1)
        run = create_run(line["id"], product["id"],
                         "2026-06-04T08:00:00Z", "2026-06-04T12:00:00Z")
        create_changeover(line["id"], run["id"], procedure["id"], 40)
        return line, run

    def test_first_schedule_pins_introduced_allergens(self, api):
        """PRD §3.4: "Scheduling moves the run `DRAFT` → `SCHEDULED` under a
        `QaSupervisor`" and "On success, `introduced_allergens` are recomputed
        under the *strict* variant — the baseline now counts only runs that are
        actually `COMPLETED` or `IN_PROGRESS`".

        Design: Difficulty/non_linear_state_machine/production_run_schedule_unschedule_cycle_recomputes_introduced
        """
        line, run = self._setup()
        scheduled = validate_success(_schedule_raw(run["id"], line["id"]), 200)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["introduced_allergens"] == ["WHEAT"]
        assert scheduled["changeover_required"] is True

    def test_unschedule_clears_and_second_schedule_recomputes(self, api):
        """PRD §3.4: "Unscheduling moves `SCHEDULED` → `DRAFT` (the run must be
        `SCHEDULED`, failing with `ERR_RUN_NOT_SCHEDULED`) and clears
        `introduced_allergens` and `changeover_required` until the next
        scheduling attempt."

        Design: Difficulty/non_linear_state_machine/production_run_schedule_unschedule_cycle_recomputes_introduced
        """
        line, run = self._setup()
        validate_success(_schedule_raw(run["id"], line["id"]), 200)

        unscheduled = validate_success(api.unschedule_run(run["id"], SUPERVISOR), 200)
        assert unscheduled["status"] == "DRAFT"
        assert unscheduled["introduced_allergens"] == [], (
            "Unschedule must clear introduced_allergens")

        rescheduled = validate_success(_schedule_raw(run["id"], line["id"]), 200)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["introduced_allergens"] == ["WHEAT"]


class TestBaselineExcludesCancelledRuns:
    def test_cancelled_predecessor_does_not_mask_introduced_allergens(self, api):
        """PRD §3.4: "Runs in `DRAFT`, `REJECTED`, or `CANCELLED` never
        contribute to any baseline."

        Design: Corner/calculations/introduced_allergens_excludes_draft_and_cancelled_runs
        """
        allergen = create_allergen("PEANUT")
        line = create_line("LINE-C4", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=30)
        product = create_product("P-C4", ["PEANUT"])
        run1 = create_run(line["id"], product["id"],
                          "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        cancelled = validate_success(api.cancel_run(run1["id"], SUPERVISOR), 200)
        assert cancelled["status"] == "CANCELLED"

        run2 = validate_success(
            api.create_production_run(
                create_production_run_payload(line["id"], product["id"],
                                              planned_start_utc="2026-06-01T12:00:00Z",
                                              planned_end_utc="2026-06-01T14:00:00Z"),
                SUPERVISOR), 201)
        assert run2["introduced_allergens"] == ["PEANUT"], (
            "A CANCELLED predecessor must not contribute its allergens to the baseline")
        assert run2["changeover_required"] is True


class TestScheduleGates:
    def test_changeover_required_run_without_covering_changeover_rejected(self, api):
        """PRD §3.4: "if `changeover_required` is true, a covering changeover
        targeting this run must already exist in `PLANNED` or a later state
        (`ERR_CHANGEOVER_MISSING`)".

        Design: Corner/errors/error_changeover_missing_at_schedule
        """
        allergen = create_allergen("PEANUT")
        line = create_line("LINE-ER1", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=30)
        product = create_product("P-ER1", ["PEANUT"])
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        res = _schedule_raw(run["id"], line["id"])
        validate_error(res, "ERR_CHANGEOVER_MISSING")

    def test_inactive_product_rejected_at_schedule(self, api):
        """PRD §3.4: "the product's `is_active` must be true
        (`ERR_PRODUCT_INACTIVE`, HTTP 422)".

        Design: Corner/errors/error_product_inactive_at_schedule
        """
        line = create_line("LINE-ER2", "ALLERGEN_DEDICATED")
        product = create_product("P-ER2", [], is_active=False)
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        res = _schedule_raw(run["id"], line["id"])
        validate_error(res, "ERR_PRODUCT_INACTIVE")

    def test_prohibited_allergen_rejected_at_schedule(self, api):
        """PRD §3.4: "When any introduced allergen is mapped `PROHIBITED` on
        that line, the run cannot proceed at all — the write is rejected with
        `ERR_ALLERGEN_PROHIBITED_ON_LINE` (HTTP 422), and this is enforced both
        at run creation and again at scheduling."

        Design: Corner/validations/prohibited_allergen_rejected_at_schedule
        """
        allergen = create_allergen("PEANUT")
        line = create_line("LINE-V3", "ALLERGEN_DEDICATED")
        product = create_product("P-V3", ["PEANUT"])
        # Draft the run before any PROHIBITED mapping exists so creation passes.
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        create_matrix_entry(line["id"], allergen["id"], handling="PROHIBITED",
                            changeover_minutes=0)
        res = _schedule_raw(run["id"], line["id"])
        validate_error(res, "ERR_ALLERGEN_PROHIBITED_ON_LINE")

    def test_prohibited_allergen_rejected_at_creation(self, api):
        """PRD §3.4: "When any introduced allergen is mapped `PROHIBITED` on
        that line, the run cannot proceed at all — the write is rejected with
        `ERR_ALLERGEN_PROHIBITED_ON_LINE` (HTTP 422), and this is enforced both
        at run creation and again at scheduling."

        Design: Corner/validations/prohibited_allergen_rejected_at_schedule
        """
        allergen = create_allergen("PEANUT")
        line = create_line("LINE-V3B", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"], handling="PROHIBITED",
                            changeover_minutes=0)
        product = create_product("P-V3B", ["PEANUT"])
        res = api.create_production_run(
            create_production_run_payload(line["id"], product["id"],
                                          planned_start_utc="2026-06-01T08:00:00Z",
                                          planned_end_utc="2026-06-01T10:00:00Z"),
            SUPERVISOR)
        validate_error(res, "ERR_ALLERGEN_PROHIBITED_ON_LINE")

    def test_reschedule_of_scheduled_run_rejected_not_draft(self, api):
        """PRD §3.4: "the run must still be `DRAFT` (`ERR_RUN_NOT_DRAFT`)".
        PRD §2.8: "Requests are evaluated against an ordered validation cascade,
        and the first failing check determines the error returned." — with a
        fresh OCC token supplied, the source-state check is the first failure.

        Design: Corner/validations/state_priority_beats_business_safety_on_run_schedule
        """
        line = create_line("LINE-V2", "ALLERGEN_DEDICATED")
        product = create_product("P-V2A", [])
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        validate_success(_schedule_raw(run["id"], line["id"]), 200)
        res = _schedule_raw(run["id"], line["id"])
        validate_error(res, "ERR_RUN_NOT_DRAFT")


class TestRunStartGates:
    def test_start_draft_run_reports_state_error_not_changeover_gate(self, api):
        """PRD §2.8: "Requests are evaluated against an ordered validation
        cascade, and the first failing check determines the error returned." —
        source-state legality (step 5) precedes the business-safety changeover
        validation gate (step 7).
        PRD §3.4: "The run must be `SCHEDULED` (`ERR_RUN_NOT_SCHEDULED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_run_start_gates
        """
        allergen = create_allergen("FISH")
        line = create_line("LINE-8", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=30)
        product = create_product("P-FISH", ["FISH"])
        run = create_run(line["id"], product["id"],
                         "2026-06-07T08:00:00Z", "2026-06-07T12:00:00Z")
        assert run["changeover_required"] is True  # no covering changeover exists
        set_clock("2026-06-07T09:00:00Z")
        res = api.start_run(run["id"], OPERATOR)
        validate_error(res, "ERR_RUN_NOT_SCHEDULED")

    def test_start_scheduled_run_without_validated_changeover_rejected(self, api):
        """PRD §3.4: "a run flagged `changeover_required` may only start once
        its covering changeover stands at `VALIDATED`
        (`ERR_CHANGEOVER_NOT_VALIDATED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_run_start_gates
        """
        allergen = create_allergen("FISH")
        line = create_line("LINE-8B", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=30)
        product = create_product("P-FISH-B", ["FISH"])
        procedure = create_and_approve_procedure(allergen["id"], "COP-FISH-V1",
                                                 min_swab_zones=1)
        run = create_run(line["id"], product["id"],
                         "2026-06-07T08:00:00Z", "2026-06-07T12:00:00Z")
        create_changeover(line["id"], run["id"], procedure["id"], 30)  # stays PLANNED
        run = schedule_run(run)
        assert run["status"] == "SCHEDULED"
        set_clock("2026-06-07T09:00:00Z")
        res = api.start_run(run["id"], OPERATOR)
        validate_error(res, "ERR_CHANGEOVER_NOT_VALIDATED")
