"""Recall exercises: recovery threshold, deadline, completion idempotency,
cross-plant target validation."""
from test_helpers import (
    QA_MANAGER_1,
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    assert_pct,
    complete_recall_payload,
    create_recall_exercise_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

ADMIN = TEST_USERS["plant_admin_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestRecoveryThresholdBoundary:
    def test_recovery_at_exactly_99_5_passes(self, api):
        """PRD §3.9: "The pass/fail decision, however, uses the unrounded ratio: the exercise lands in `PASSED` when the logical clock reads at or before `deadline_at` and the ratio of reconciled (capped at basis) to basis is at least 0.995 — a recovery percentage of at least 99.5 — and in `FAILED` when the deadline has passed or the ratio falls short."
        PRD §3.9: "Initiation stamps `initiated_at` from the clock, sets `deadline_at` to twenty-four hours later, snapshots the target lot's `total_weight_lbs` as `basis_weight_lbs` (the one-hundred-percent recovery basis), and lands the exercise in `INITIATED`."

        Design: Difficulty/boundary_precision_check/recall_recovery_threshold_99_5_boundary
        """
        env, lot, label, fl, ex = fixtures.setup_recall_exercise(
            establishment_number="EST-1645-L1",
            units_produced=100, unit_weight_lbs=10.0,
        )
        assert ex["status"] == "INITIATED"
        assert_pct(ex["basis_weight_lbs"], 1000.0)
        assert_instant_equals(ex["initiated_at"], "2026-08-01T07:00:00Z")
        assert_instant_equals(ex["deadline_at"], "2026-08-02T07:00:00Z")

        done = validate_success(
            api.complete_recall_exercise(
                ex["id"], complete_recall_payload(reconciled_weight_lbs=995.0),
                fixtures.make_qa_manager_headers(QA_MANAGER_1),
            ),
            200,
        )
        # 995.0 / 1000.0 == 0.995 exactly: the inclusive threshold passes.
        assert_pct(done["recovery_pct"], 99.5)
        assert done["status"] == "PASSED"

    def test_recovery_just_below_99_5_fails_and_cascades(self, api):
        """PRD §3.9: "the exercise lands in `PASSED` when the logical clock reads at or before `deadline_at` and the ratio of reconciled (capped at basis) to basis is at least 0.995 — a recovery percentage of at least 99.5 — and in `FAILED` when the deadline has passed or the ratio falls short."
        PRD §3.9: "A `FAILED` exercise fires the full noncompliance cascade: a `TRACEABILITY` record with severity `CRITICAL` is created for the plant with `created_by` set to the completing operator and a null `production_day_id`, the plant suspends, and every `OPEN` production day of the plant suspends behind it."

        Design: Difficulty/boundary_precision_check/recall_recovery_threshold_99_5_boundary
        """
        env, lot, label, fl, ex = fixtures.setup_recall_exercise(
            establishment_number="EST-1645-L2",
            units_produced=100, unit_weight_lbs=10.0,
        )
        done = validate_success(
            api.complete_recall_exercise(
                ex["id"], complete_recall_payload(reconciled_weight_lbs=994.9),
                fixtures.make_qa_manager_headers(QA_MANAGER_1),
            ),
            200,
        )
        # 994.9 / 1000.0 = 0.9949 < 0.995 -> FAILED; reported pct is 99.49.
        assert_pct(done["recovery_pct"], 99.49)
        assert done["status"] == "FAILED"
        assert done.get("completed_at"), "completion stamps completed_at"

        records, meta = validate_paginated(
            api.list_noncompliance_records(QA, params={"plant_id": env["plant"]["id"]})
        )
        assert len(records) == 1
        assert records[0]["category"] == "TRACEABILITY"
        assert records[0]["severity"] == "CRITICAL"
        assert records[0]["created_by"] == QA_MANAGER_1
        assert records[0].get("production_day_id") is None

        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert plant["operating_status"] == "SUSPENDED"
        day = validate_success(api.get_production_day(env["day"]["id"], QA), 200)
        assert day["status"] == "SUSPENDED"


class TestRecallCompletionRules:
    def test_complete_twice_returns_already_completed(self, api):
        """PRD §3.9: "Completion belongs to the `QAManager`, who supplies the `reconciled_weight_lbs` actually accounted for; an exercise no longer `INITIATED` rejects completion with `ERR_RECALL_ALREADY_COMPLETED`."

        Design: Corner/state_machines/recall_complete_twice_returns_already_completed
        """
        env, lot, label, fl, ex = fixtures.setup_recall_exercise(
            establishment_number="EST-1645-08",
            units_produced=100, unit_weight_lbs=10.0,
        )
        first = validate_success(
            api.complete_recall_exercise(
                ex["id"], complete_recall_payload(reconciled_weight_lbs=1000.0),
                fixtures.make_qa_manager_headers(QA_MANAGER_1),
            ),
            200,
        )
        assert first["status"] == "PASSED", "100.0 recovery within the deadline"

        again = api.complete_recall_exercise(
            ex["id"], complete_recall_payload(reconciled_weight_lbs=1000.0),
            fixtures.make_qa_manager_headers(QA_MANAGER_1),
        )
        validate_error(again, ApiErrorId.ERR_RECALL_ALREADY_COMPLETED)
        assert again.status_code == 409

    def test_complete_after_deadline_fails_despite_full_recovery(self, api):
        """PRD §3.9: "the exercise lands in `PASSED` when the logical clock reads at or before `deadline_at` and the ratio of reconciled (capped at basis) to basis is at least 0.995 — a recovery percentage of at least 99.5 — and in `FAILED` when the deadline has passed or the ratio falls short."
        PRD §3.9: "Initiation stamps `initiated_at` from the clock, sets `deadline_at` to twenty-four hours later, snapshots the target lot's `total_weight_lbs` as `basis_weight_lbs` (the one-hundred-percent recovery basis), and lands the exercise in `INITIATED`."

        Design: Corner/calculations/recall_complete_after_deadline_fails_despite_full_recovery
        """
        env, lot, label, fl, ex = fixtures.setup_recall_exercise(
            establishment_number="EST-1645-20",
            units_produced=100, unit_weight_lbs=10.0, shelf_life_days=30,
            scope="ONE_STEP_FORWARD",
        )
        assert_instant_equals(ex["deadline_at"], "2026-08-02T07:00:00Z")

        # One hour past the deadline; recovery itself would be perfect.
        fixtures.set_clock("2026-08-02T08:00:00Z")
        done = validate_success(
            api.complete_recall_exercise(
                ex["id"], complete_recall_payload(reconciled_weight_lbs=1000.0),
                fixtures.make_qa_manager_headers(QA_MANAGER_1),
            ),
            200,
        )
        assert_pct(done["recovery_pct"], 100.0)
        assert done["status"] == "FAILED", "the deadline leg dominates"

        records, _meta = validate_paginated(
            api.list_noncompliance_records(QA, params={"plant_id": env["plant"]["id"]})
        )
        assert len(records) == 1
        assert records[0]["category"] == "TRACEABILITY"


class TestRecallTargetValidation:
    def test_target_from_other_plant_returns_target_invalid(self, api):
        """PRD §3.9: "A `PlantAdmin` initiates a traceability exercise against a `target_finished_lot_id` — which must belong to the plant named in the path, otherwise `ERR_RECALL_TARGET_INVALID` — and a `scope` of `ONE_STEP_BACK`, `ONE_STEP_FORWARD`, or `FULL`."

        Design: Corner/validations/recall_target_from_other_plant_returns_target_invalid
        """
        # Plant B carries the finished lot; plant A is the path plant.
        plant_a = fixtures.create_plant(establishment_number="EST-1645-34A")
        env_b, lot_b, label_b, fl_b = fixtures.setup_finished_lot(
            establishment_number="EST-1645-34B"
        )

        resp = api.create_recall_exercise(
            plant_a["id"],
            create_recall_exercise_payload(
                target_finished_lot_id=fl_b["id"], scope="FULL"
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_RECALL_TARGET_INVALID)
        assert resp.status_code == 422

        exercises, meta = validate_paginated(
            api.list_recall_exercises(QA, params={"plant_id": plant_a["id"]})
        )
        assert exercises == []
        assert meta["total_count"] == 0
