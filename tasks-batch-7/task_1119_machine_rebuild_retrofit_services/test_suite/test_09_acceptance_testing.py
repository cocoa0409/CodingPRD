"""Geometric acceptance testing: the WORST_CASE / ISO_STATISTICAL evaluation
variants, inclusive verdict boundaries, scheduling gates, segregation of
duties, and immediate visibility of the acceptance cascade."""

import pytest

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    make_inspector_headers,
    validate_error,
    validate_success,
)

DIVERGENT_SAMPLES = [10, 12, -8, 9, -11]


class TestAcceptanceVariantsDiverge:
    def test_worst_case_variant_passes_dispersed_samples(self, api):
        """PRD §3.6: "Under `WORST_CASE` — chosen when the decision is `RETROFIT_ONLY` or `MECHANICAL_REBUILD` — the `statistic_value` is simply the `max_abs_sample_microns`; the distribution shape is ignored."
        PRD §3.6: "The server first derives `max_abs_sample_microns`, the largest absolute value among the five samples, rounded half-up to two decimal places."
        PRD §3.6: "The verdict uses inclusive boundaries on both checks: the test passes only when the `statistic_value` is at most 20.0 microns and the `repeatability_microns` is at most 10.0 microns; breaching either tolerance fails the test."

        Design: Difficulty/dual_variant_calc/acceptance_worst_case_vs_iso_diverge
        """
        ctx = fx.setup_scheduled_test(decision="MECHANICAL_REBUILD")
        recorded = fx.record_test(ctx.test["id"], samples=DIVERGENT_SAMPLES, repeatability=5.0)

        assert recorded["evaluation_variant"] == "WORST_CASE"
        assert recorded["max_abs_sample_microns"] == pytest.approx(12.0, abs=0.001)
        assert recorded["statistic_value"] == pytest.approx(12.0, abs=0.001)
        assert recorded["status"] == "PASSED"

        project = fx.get_project(ctx.project["id"])
        assert project["work_status"] == "ACCEPTED"

    def test_iso_statistical_variant_fails_same_samples(self, api):
        """PRD §3.6: "Under `ISO_STATISTICAL` — chosen when the decision is `FULL_REBUILD` — the mean of the five samples is computed, then the population standard deviation (the square root of the average squared deviation from that mean, dividing by the sample count of five, not four), and the `statistic_value` is the absolute value of the mean plus two times that standard deviation, rounded half-up to two decimal places; this branch is the stricter one for dispersed samples."
        PRD §3.6: "The verdict uses inclusive boundaries on both checks: the test passes only when the `statistic_value` is at most 20.0 microns and the `repeatability_microns` is at most 10.0 microns; breaching either tolerance fails the test."

        Design: Difficulty/dual_variant_calc/acceptance_worst_case_vs_iso_diverge
        """
        # wear 123.00 (30/12/9) -> recommended FULL_REBUILD; decision matches it.
        ctx = fx.setup_scheduled_test(decision="FULL_REBUILD", pd=30, sr=12, bl=9)
        recorded = fx.record_test(ctx.test["id"], samples=DIVERGENT_SAMPLES, repeatability=5.0)

        # mean = 2.4; population stddev = sqrt(96.24) = 9.8101...; 2.4 + 2*std = 22.02
        assert recorded["evaluation_variant"] == "ISO_STATISTICAL"
        assert recorded["max_abs_sample_microns"] == pytest.approx(12.0, abs=0.001)
        assert recorded["statistic_value"] == pytest.approx(22.02, abs=0.001)
        assert recorded["status"] == "FAILED"

        project = fx.get_project(ctx.project["id"])
        assert project["work_status"] == "REWORK"


class TestAcceptanceSchedulingGate:
    def test_create_rejected_while_rebuild_in_progress(self, api):
        """PRD §3.6: "Scheduling requires the project to be `AWAITING_ACCEPTANCE` (otherwise `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE`), requires that no other test of the same project is still `SCHEDULED` (otherwise `ERR_OPEN_ACCEPTANCE_TEST`), and is segregated from the rebuild work: the scheduling inspector must not be the project's `assigned_engineer_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/cross_entity_state_dependency/acceptance_test_requires_project_awaiting_acceptance
        """
        ctx = fx.setup_project_rebuild_in_progress()
        res = api.create_acceptance_test(ctx.project["id"], make_inspector_headers("qi-1"))
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_AWAITING_ACCEPTANCE.value)

    def test_create_succeeds_after_declare_ready(self, api):
        """PRD §3.6: "The server records the caller as `inspector_id` and computes `attempt_number` as one plus the count of prior tests for the project."
        PRD §3.6: "The new test is born `SCHEDULED`, and tests can be listed with an optional `project_id` filter."
        PRD §3.6: "When the assigned `RebuildEngineer` judges the machine ready, they declare readiness, moving `work_status` to `AWAITING_ACCEPTANCE` — from `REBUILD_IN_PROGRESS` on the first pass, or from `REWORK` on each rework cycle."

        Design: Difficulty/cross_entity_state_dependency/acceptance_test_requires_project_awaiting_acceptance
        """
        ctx = fx.setup_project_rebuild_in_progress()
        fx.declare_ready(ctx.project["id"], engineer_id=ctx.engineer_id)

        test = validate_success(
            api.create_acceptance_test(ctx.project["id"], make_inspector_headers("qi-1")), 201
        )
        assert test["status"] == "SCHEDULED"
        assert test["attempt_number"] == 1
        assert test["inspector_id"] == "qi-1"
        fx.assert_acceptance_test(test)


def test_acceptance_boundaries_inclusive(api):
    """PRD §3.6: "The verdict uses inclusive boundaries on both checks: the test passes only when the `statistic_value` is at most 20.0 microns and the `repeatability_microns` is at most 10.0 microns; breaching either tolerance fails the test."

    Design: Corner/calculations/acceptance_boundaries_inclusive
    """
    ctx = fx.setup_scheduled_test(decision="MECHANICAL_REBUILD")

    # statistic exactly 20.0 passes the position tolerance, but repeatability
    # 10.1 breaches the 10.0 tolerance -> FAILED.
    first = fx.record_test(ctx.test["id"], samples=[20, 20, 20, 20, 20], repeatability=10.1)
    assert first["statistic_value"] == pytest.approx(20.0, abs=0.001)
    assert first["status"] == "FAILED"

    # Rework cycle: declare readiness again and schedule the second attempt.
    fx.declare_ready(ctx.project["id"], engineer_id=ctx.engineer_id)
    second_test = fx.schedule_acceptance_test(ctx.project["id"], inspector_id=ctx.inspector_id)
    second = fx.record_test(second_test["id"], samples=[20, 20, 20, 20, 20], repeatability=10.0)
    assert second["statistic_value"] == pytest.approx(20.0, abs=0.001)
    assert second["status"] == "PASSED"


def test_open_acceptance_test_blocks_second_test(api):
    """PRD §3.6: "Scheduling requires the project to be `AWAITING_ACCEPTANCE` (otherwise `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE`), requires that no other test of the same project is still `SCHEDULED` (otherwise `ERR_OPEN_ACCEPTANCE_TEST`), and is segregated from the rebuild work: the scheduling inspector must not be the project's `assigned_engineer_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/validations/open_acceptance_test_blocks_second_test
    """
    ctx = fx.setup_scheduled_test()

    res = api.create_acceptance_test(ctx.project["id"], make_inspector_headers("qi-2"))
    validate_error(res, ApiErrorId.ERR_OPEN_ACCEPTANCE_TEST.value)

    first_after = validate_success(api.get_acceptance_test(ctx.test["id"], PM), 200)
    assert first_after["status"] == "SCHEDULED"


def test_acceptance_inspector_equals_assigned_engineer_rejected(api):
    """PRD §3.6: "Scheduling requires the project to be `AWAITING_ACCEPTANCE` (otherwise `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE`), requires that no other test of the same project is still `SCHEDULED` (otherwise `ERR_OPEN_ACCEPTANCE_TEST`), and is segregated from the rebuild work: the scheduling inspector must not be the project's `assigned_engineer_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/state_machines/acceptance_inspector_equals_assigned_engineer_rejected
    """
    ctx = fx.setup_project_awaiting_acceptance()
    assert ctx.engineer_id == "eng-1"

    # A QualityInspector caller whose X-User-ID equals the assigned engineer id.
    res = api.create_acceptance_test(ctx.project["id"], make_inspector_headers("eng-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    ok = validate_success(
        api.create_acceptance_test(ctx.project["id"], make_inspector_headers("qi-1")), 201
    )
    assert ok["status"] == "SCHEDULED"


def test_immediate_visibility_of_acceptance_cascade(api):
    """PRD §3.6: "A passing recording moves the test to the terminal `PASSED` and fires the acceptance cascade on the project: `work_status` moves from `AWAITING_ACCEPTANCE` to `ACCEPTED`, `consecutive_fail_count` resets to zero, the project's `accepted_positioning_microns` — null until this moment — is set to the passing test's `max_abs_sample_microns`, and a TrainingRecord is auto-created in `PLANNED` with its `sessions_required` derived from the decision class."
    PRD §3.7: "Training records can be listed with an optional `project_id` filter."

    Design: Corner/consistency_model/immediate_visibility_of_acceptance_cascade
    """
    ctx = fx.setup_scheduled_test(decision="MECHANICAL_REBUILD")
    recorded = fx.record_test(ctx.test["id"], samples=[8, -8, 8, -8, 0], repeatability=5.0)
    assert recorded["status"] == "PASSED"

    # The very next reads observe the completed cascade — no lag.
    project = fx.get_project(ctx.project["id"])
    assert project["work_status"] == "ACCEPTED"
    assert project["accepted_positioning_microns"] == pytest.approx(8.0, abs=0.001)
    assert project["consecutive_fail_count"] == 0

    record = fx.find_training_record_for_project(ctx.project["id"])
    assert record["status"] == "PLANNED"
    assert record["sessions_required"] == 2
    fx.assert_training_record(record)
