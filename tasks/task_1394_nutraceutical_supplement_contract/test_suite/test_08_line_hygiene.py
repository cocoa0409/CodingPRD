"""Line hygiene cycle, allergen changeover gating, cleaning validation workflow."""
from test_helpers import (
    TEST_USERS,
    WINDOW_DAY1,
    WINDOW_DAY2,
    ApiErrorId,
    approve_cleaning,
    complete_batch,
    create_and_approve_formula,
    create_customer,
    create_production_line,
    create_raw_material,
    create_released_lot,
    get_batch,
    get_production_line,
    make_catalog,
    place_order,
    record_cleaning,
    record_consumption,
    run_batch,
    schedule_order,
    setup_batch_at_stage,
    start_batch,
    swab_cleaning,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]
CHEMIST = TEST_USERS["qa_chemist_headers"]
QA = TEST_USERS["qa_manager_headers"]


def _dirty_line_with_scheduled_batch():
    """B1 completed on the line (line DIRTY, allergen NONE); B2 scheduled day 2."""
    ctx = make_catalog(clock="2026-08-01T00:00:00Z", lot_qty=20000000)
    run1 = run_batch(ctx, window=WINDOW_DAY1, stage="COMPLETED")
    run2 = run_batch(ctx, window=WINDOW_DAY2, stage="SCHEDULED")
    return ctx, run1, run2


class TestAllergenChangeover:
    def _gluten_then_none_setup(self):
        customer = create_customer("Acme")
        rm_g = create_raw_material("WheatStarch", "GLUTEN")
        rm_n = create_raw_material("VitC", "NONE")
        f_g = create_and_approve_formula(
            customer["id"], rm_g["id"], name="W500", allergen_class="GLUTEN"
        )
        f_n = create_and_approve_formula(
            customer["id"], rm_n["id"], name="C500", allergen_class="NONE"
        )
        line = create_production_line("L1")
        lot_g = create_released_lot(rm_g["id"], qty_received=20000000)
        mo1 = place_order(customer["id"], f_g["id"], 10000)
        b1 = schedule_order(mo1["id"], line["id"], WINDOW_DAY1[0], WINDOW_DAY1[1])
        start_batch(b1["id"])
        record_consumption(b1["id"], lot_g["id"], 5500000)
        complete_batch(b1["id"], 9800, 5390)
        return customer, f_g, f_n, line

    def test_allergen_changeover_required_on_dirty_line(self, api):
        """PRD §3.4: "a `DIRTY` line whose `current_allergen_class` differs from the
        formula's allergen class rejects it with `ERR_ALLERGEN_CHANGEOVER_REQUIRED`,
        forcing the changeover workflow of §3.6 first."

        Design: Corner/state_machines/allergen_changeover_required_on_dirty_line
        """
        customer, _f_g, f_n, line = self._gluten_then_none_setup()
        line_now = get_production_line(line["id"])
        assert line_now["cleaning_status"] == "DIRTY"
        assert line_now["current_allergen_class"] == "GLUTEN"

        mo2 = place_order(customer["id"], f_n["id"], 10000)
        b2 = schedule_order(mo2["id"], line["id"], WINDOW_DAY2[0], WINDOW_DAY2[1])
        resp = api.start_batch(b2["id"], {}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_REQUIRED)
        assert resp.status_code == 409

    def test_like_for_like_start_on_dirty_line_allowed(self, api):
        """PRD §3.4: "a `DIRTY` line also accepts it when its
        `current_allergen_class` matches the allergen class of the formula being
        run — the like-for-like campaign continuation."

        Design: Corner/state_machines/like_for_like_start_on_dirty_line_allowed
        """
        customer, f_g, _f_n, line = self._gluten_then_none_setup()
        assert get_production_line(line["id"])["current_allergen_class"] == "GLUTEN"

        mo2 = place_order(customer["id"], f_g["id"], 10000)
        b2 = schedule_order(mo2["id"], line["id"], WINDOW_DAY2[0], WINDOW_DAY2[1])
        resp = api.start_batch(b2["id"], {}, OPERATOR)
        started = validate_success(resp, 200)
        assert started["production_status"] == "IN_PROCESS", (
            "GLUTEN formula on a DIRTY GLUTEN line is a lawful like-for-like start"
        )


class TestCleaningValidationWorkflow:
    def test_cleaning_record_on_validated_line_rejected(self, api):
        """PRD §3.6: "Cleaning is recorded by a `ProductionOperator` on a line whose
        `cleaning_status` is `DIRTY` — recording on any other posture is rejected
        with `ERR_CLEANING_STATE`."

        Design: Corner/state_machines/cleaning_record_on_validated_line_rejected
        """
        line = create_production_line("L1")
        assert line["cleaning_status"] == "CLEAN_VALIDATED"
        resp = api.record_cleaning_validation(line["id"], {}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CLEANING_STATE)
        assert resp.status_code == 409

    def test_swab_fail_returns_line_to_dirty(self, api):
        """PRD §3.6: "A failing swab moves the validation to the terminal `FAILED`
        status and pushes the line back to `DIRTY`, forcing a fresh cleaning
        cycle."

        Design: Corner/state_machines/cleaning_swab_fail_returns_line_to_dirty
        """
        ctx = setup_batch_at_stage("COMPLETED")
        line_id = ctx["line"]["id"]
        assert get_production_line(line_id)["cleaning_status"] == "DIRTY"

        validation = record_cleaning(line_id)
        assert validation["status"] == "RECORDED"
        resp = api.swab_cleaning_validation(validation["id"], {"result": "FAIL"}, CHEMIST)
        failed = validate_success(resp, 200)
        assert failed["status"] == "FAILED"
        assert get_production_line(line_id)["cleaning_status"] == "DIRTY", (
            "the line must bounce back to DIRTY so a fresh cleaning can be recorded"
        )

    def test_approve_before_swab_rejected(self, api):
        """PRD §3.6: "Final approval is a `QAManager` action on a validation in
        `SWAB_PASSED` (`ERR_CLEANING_STATE` otherwise)".

        Design: Corner/state_machines/cleaning_approve_before_swab_rejected
        """
        ctx = setup_batch_at_stage("COMPLETED")
        validation = record_cleaning(ctx["line"]["id"])

        resp = api.approve_cleaning_validation(validation["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_CLEANING_STATE)
        assert resp.status_code == 409

        rows, meta = validate_paginated(
            api.list_cleaning_validations(ctx["line"]["id"], QA)
        )
        current = [r for r in rows if r["id"] == validation["id"]][0]
        assert current["status"] == "RECORDED", (
            "the rejected approval must leave the validation RECORDED"
        )


class TestLineCleaningCycle:
    def test_line_hygiene_cycle_repeats_per_campaign(self, api):
        """PRD §3.6: "The line's hygiene posture cycles: `CLEAN_VALIDATED` → `DIRTY`
        when a batch completes (§3.4) → `CLEAN_PENDING_VALIDATION` when cleaning is
        recorded → back to `CLEAN_VALIDATED` when the validation is approved,
        repeating per campaign."
        PRD §3.4: "Completion also stamps `completed_at` from the logical clock
        (§2.6), records the operator in `recorded_by_id`, and flips the line:
        `cleaning_status` becomes `DIRTY` and `current_allergen_class` takes the
        completing batch's formula allergen class."

        Design: Difficulty/non_linear_state_machine/production_line_cleaning_cycle
        """
        ctx, run1, run2 = _dirty_line_with_scheduled_batch()
        line_id = ctx["line"]["id"]
        # CLEAN_VALIDATED -> DIRTY after the first completion.
        line = get_production_line(line_id)
        assert line["cleaning_status"] == "DIRTY"
        assert line["current_allergen_class"] == "NONE"

        # DIRTY -> CLEAN_PENDING_VALIDATION on record.
        validation = record_cleaning(line_id)
        assert validation["status"] == "RECORDED"
        assert get_production_line(line_id)["cleaning_status"] == "CLEAN_PENDING_VALIDATION"

        # CLEAN_PENDING_VALIDATION -> CLEAN_VALIDATED on swab PASS + approve.
        swab_cleaning(validation["id"], "PASS")
        approve_cleaning(validation["id"])
        line = get_production_line(line_id)
        assert line["cleaning_status"] == "CLEAN_VALIDATED"
        assert line["current_allergen_class"] == "NONE"

        # The cycle repeats: starting and completing the second batch re-dirties.
        start_batch(run2["batch"]["id"])
        record_consumption(run2["batch"]["id"], ctx["lot"]["id"], 5500000)
        complete_batch(run2["batch"]["id"], 9900, 5445)
        line = get_production_line(line_id)
        assert line["cleaning_status"] == "DIRTY", (
            "the second campaign must drive the line back to DIRTY"
        )

    def test_cleaning_approval_resets_allergen_and_reopens_gate(self, api):
        """PRD §3.6: "Approval moves the validation to the terminal `VALIDATED`
        status with `approved_by_id` recorded, returns the line to
        `CLEAN_VALIDATED`, and resets the line's `current_allergen_class` to `NONE`
        — the line is then ready for any formula, including allergen changeovers."

        Design: Difficulty/non_linear_state_machine/production_line_cleaning_cycle
        """
        ctx, run1, run2 = _dirty_line_with_scheduled_batch()
        line_id = ctx["line"]["id"]
        validation = record_cleaning(line_id)
        swabbed = swab_cleaning(validation["id"], "PASS")
        assert swabbed["status"] == "SWAB_PASSED"
        assert swabbed["swabbed_by_id"] == "chem-1"

        approved = approve_cleaning(validation["id"])
        assert approved["status"] == "VALIDATED"
        assert approved["approved_by_id"] == "qm-1"

        line = get_production_line(line_id)
        assert line["cleaning_status"] == "CLEAN_VALIDATED"
        assert line["current_allergen_class"] == "NONE"

        resp = api.start_batch(run2["batch"]["id"], {}, OPERATOR)
        started = validate_success(resp, 200)
        assert started["production_status"] == "IN_PROCESS", (
            "a validated cleaning reopens the start gate"
        )


class TestBatchStartCleaningGate:
    def test_start_rejected_while_cleaning_pending_validation(self, api):
        """PRD §3.4: "A line sitting in `CLEAN_PENDING_VALIDATION` rejects the start
        with `ERR_LINE_NOT_CLEAN_VALIDATED`".

        Design: Difficulty/cross_entity_state_dependency/batch_start_gated_on_line_cleaning
        """
        ctx, run1, run2 = _dirty_line_with_scheduled_batch()
        record_cleaning(ctx["line"]["id"])
        line = get_production_line(ctx["line"]["id"])
        assert line["cleaning_status"] == "CLEAN_PENDING_VALIDATION"

        resp = api.start_batch(run2["batch"]["id"], {}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_CLEAN_VALIDATED)
        assert resp.status_code == 409
        assert get_batch(run2["batch"]["id"])["production_status"] == "CREATED"

    def test_start_allowed_after_cleaning_validation_approved(self, api):
        """PRD §3.4: "The line gate then applies: a line whose `cleaning_status` is
        `CLEAN_VALIDATED` accepts the start".
        PRD §3.6: "Approval moves the validation to the terminal `VALIDATED` status
        with `approved_by_id` recorded, returns the line to `CLEAN_VALIDATED`, and
        resets the line's `current_allergen_class` to `NONE`".

        Design: Difficulty/cross_entity_state_dependency/batch_start_gated_on_line_cleaning
        """
        ctx, run1, run2 = _dirty_line_with_scheduled_batch()
        validation = record_cleaning(ctx["line"]["id"])
        swab_cleaning(validation["id"], "PASS")
        approve_cleaning(validation["id"])

        line = get_production_line(ctx["line"]["id"])
        assert line["cleaning_status"] == "CLEAN_VALIDATED"
        assert line["current_allergen_class"] == "NONE"

        resp = api.start_batch(run2["batch"]["id"], {}, OPERATOR)
        started = validate_success(resp, 200)
        assert started["production_status"] == "IN_PROCESS"
