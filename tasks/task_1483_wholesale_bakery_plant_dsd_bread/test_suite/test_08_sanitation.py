"""Sanitation changeover machinery: matrix, dwell time, fail/retry loop, and
release/scheduling gates (PRD §3.5, §3.3, §3.4)."""
from test_helpers import (
    TEST_USERS,
    assert_line,
    assert_sanitation_cycle,
    create_batch,
    create_cycle,
    create_line,
    create_plan,
    create_plant,
    create_product,
    get_plan,
    lock_plan,
    make_operator_headers,
    make_qa_headers,
    release_plan,
    set_clock,
    setup_line_dirty_with_sesame,
    validate_error,
    validate_success,
)


class TestSanitationFailRetryLoop:
    def test_fail_then_restart_returns_to_in_progress(self, api):
        """PRD §3.5: "A failed cycle is not terminal: starting it again loops
        it from `FAILED` back to `IN_PROGRESS`, resetting `started_at` and
        `started_by_user_id` and putting the line into `SANITIZING` once
        more."

        Design: Difficulty/non_linear_state_machine/sanitation_fail_retry_loop
        """
        ctx = setup_line_dirty_with_sesame(plant_name="Plant Theta")
        line = ctx["line"]

        cycle = create_cycle(line["id"], to_allergen_class="NONE", operator_id="op-1")
        # SESAME -> NONE matrix row requires 120 minutes.
        assert cycle["required_minutes"] == 120, (
            f"ALLERGEN->NONE must require 120 min, got {cycle['required_minutes']}"
        )

        op = make_operator_headers("op-1")
        qa = make_qa_headers("qa-1")
        validate_success(api.start_sanitation_cycle(cycle["id"], op))
        failed = validate_success(api.fail_sanitation_cycle(cycle["id"], qa))
        assert failed["status"] == "FAILED"

        restarted = validate_success(api.start_sanitation_cycle(cycle["id"], op))
        assert restarted["status"] == "IN_PROGRESS", (
            f"FAILED -> IN_PROGRESS retry leg must succeed, got {restarted['status']}"
        )

    def test_verify_after_retry_completes_and_cleans_line(self, api):
        """PRD §3.5: "A passing verification moves the cycle to the terminal
        `VERIFIED` state, stamps `verified_at`, returns the line to `CLEAN`,
        and sets the line's `allergen_class_current` to the cycle's
        `to_allergen_class`."

        Design: Difficulty/non_linear_state_machine/sanitation_fail_retry_loop
        """
        ctx = setup_line_dirty_with_sesame(plant_name="Plant Theta 2")
        line = ctx["line"]

        cycle = create_cycle(line["id"], to_allergen_class="NONE", operator_id="op-1")
        op = make_operator_headers("op-1")
        qa = make_qa_headers("qa-1")
        validate_success(api.start_sanitation_cycle(cycle["id"], op))
        validate_success(api.fail_sanitation_cycle(cycle["id"], qa))
        # Restart at 08:10 (the current clock); +120min is 10:10.
        validate_success(api.start_sanitation_cycle(cycle["id"], op))
        set_clock("2026-08-09T10:10:00Z")
        verified = validate_success(api.verify_sanitation_cycle(cycle["id"], qa))
        assert verified["status"] == "VERIFIED"

        line_after = validate_success(
            api.get_line(line["id"], TEST_USERS["planner_headers"])
        )
        assert_line(line_after)
        assert line_after["cleanliness"] == "CLEAN"
        assert line_after["allergen_class_current"] == "NONE"


class TestSanitationVerifyDwell:
    def test_sanitation_verify_before_required_minutes_rejected(self, api):
        """PRD §3.5: "at least `required_minutes` must have elapsed since
        `started_at` (else `ERR_SANITATION_NOT_COMPLETE`)."

        Design: Corner/validations/sanitation_verify_before_required_minutes_rejected
        """
        ctx = setup_line_dirty_with_sesame(plant_name="Plant P Dwell")
        line = ctx["line"]
        cycle = create_cycle(line["id"], to_allergen_class="NONE", operator_id="op-1")
        op = make_operator_headers("op-1")
        qa = make_qa_headers("qa-1")
        validate_success(api.start_sanitation_cycle(cycle["id"], op))

        # 30 minutes elapsed, 120 required.
        set_clock("2026-08-09T08:40:00Z")
        resp = api.verify_sanitation_cycle(cycle["id"], qa)
        validate_error(resp, "ERR_SANITATION_NOT_COMPLETE", expected_status=409)
        after = validate_success(
            api.get_sanitation_cycle(cycle["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "IN_PROGRESS"


class TestBatchScheduleOnSanitizingLine:
    def test_batch_schedule_on_sanitizing_line_rejected(self, api):
        """PRD §3.4: "A line currently `SANITIZING` rejects scheduling with
        `ERR_LINE_NOT_AVAILABLE`."

        Design: Corner/validations/batch_schedule_on_sanitizing_line_rejected
        """
        ctx = setup_line_dirty_with_sesame(plant_name="Plant P Sanitizing")
        line = ctx["line"]
        plan = ctx["plan"]
        product_b = ctx["product_b"]

        cycle = create_cycle(line["id"], to_allergen_class="NONE", operator_id="op-1")
        op = make_operator_headers("op-1")
        validate_success(api.start_sanitation_cycle(cycle["id"], op))

        plan_now = get_plan(plan["id"])
        resp = api.create_batch(
            {
                "production_plan_id": plan["id"],
                "line_id": line["id"],
                "product_id": product_b["id"],
                "qty_units": 50,
                "scheduled_start_at": "2026-08-09T11:00:00Z",
                "scheduled_end_at": "2026-08-09T12:00:00Z",
                "expected_production_plan_version": plan_now["version"],
            },
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_LINE_NOT_AVAILABLE", expected_status=409)


class TestPlanReleaseGates:
    def test_plan_release_without_batches_rejected(self, api):
        """PRD §3.3: "Releasing a plan to the floor requires at least one
        batch in `SCHEDULED` (else `ERR_PLAN_NOT_RELEASABLE`)."

        Design: Corner/validations/plan_release_without_batches_rejected
        """
        plant = create_plant()
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        validate_success(api.lock_production_plan(plan["id"], TEST_USERS["planner_headers"]))

        resp = api.release_production_plan(plan["id"], TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_PLAN_NOT_RELEASABLE", expected_status=409)
        plan_after = validate_success(
            api.get_production_plan(plan["id"], TEST_USERS["planner_headers"])
        )
        assert plan_after["status"] == "LOCKED"

    def test_plan_release_blocked_by_pending_sanitation(self, api):
        """PRD §3.3: "requires that no sanitation cycle on any line used by
        the plan is still `REQUESTED` or `IN_PROGRESS` (else
        `ERR_SANITATION_REQUIRED`)."

        Design: Corner/validations/plan_release_blocked_by_pending_sanitation
        """
        # plan1's SESAME batch runs on the line and completes, leaving it DIRTY.
        ctx = setup_line_dirty_with_sesame(plant_name="Plant P SanRel")
        plant = ctx["plant"]
        line = ctx["line"]
        product_b = ctx["product_b"]

        # A REQUESTED (not yet started) cycle exists on this line.
        cycle = create_cycle(line["id"], to_allergen_class="NONE", operator_id="op-1")
        assert cycle["status"] == "REQUESTED"

        # plan2 (different bake_date) schedules a SESAME batch on the same line.
        plant_now = validate_success(
            api.get_plant(plant["id"], TEST_USERS["planner_headers"])
        )
        plan2 = create_plan(
            plant["id"],
            expected_plant_version=plant_now["version"],
            bake_date="2026-08-10",
        )
        plan2_locked = lock_plan(plan2["id"])
        create_batch(
            plan2["id"],
            line["id"],
            product_b["id"],
            plan_version=plan2_locked["version"],
            qty_units=100,
            scheduled_start_at="2026-08-10T07:00:00Z",
            scheduled_end_at="2026-08-10T09:00:00Z",
        )

        resp = api.release_production_plan(plan2["id"], TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_SANITATION_REQUIRED", expected_status=409)
        plan2_after = validate_success(
            api.get_production_plan(plan2["id"], TEST_USERS["planner_headers"])
        )
        assert plan2_after["status"] == "LOCKED"
