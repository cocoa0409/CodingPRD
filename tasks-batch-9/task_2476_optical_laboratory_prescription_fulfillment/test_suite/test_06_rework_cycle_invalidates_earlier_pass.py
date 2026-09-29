"""The rework loop, the cycle index and the two-eye join."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.test_users import TECHNICIAN_A_HEADERS

CYCLE0_OD_PASS = {
    "measured_sphere": -3.13,
    "measured_cylinder": -1.25,
    "measured_axis": 90,
    "measured_prism": 0.5,
}
CYCLE0_OS_FAIL = {
    "measured_sphere": -2.55,
    "measured_cylinder": -1.0,
    "measured_axis": 85,
    "measured_prism": 0.0,
}
CYCLE1_OD_PASS = {
    "measured_sphere": -3.0,
    "measured_cylinder": -1.25,
    "measured_axis": 90,
    "measured_prism": 0.5,
}
CYCLE1_OS_PASS = {
    "measured_sphere": -2.75,
    "measured_cylinder": -1.0,
    "measured_axis": 85,
    "measured_prism": 0.0,
}


def _edged_job_with_one_passing_eye(api):
    """An edged surfaced job whose OD reading already passed at cycle 0."""
    scenario = fixtures.surfaced_edged_job(api)
    od = fixtures.inspect_eye(api, scenario["job_id"], "OD", **CYCLE0_OD_PASS)
    assert od["verdict"] == "PASS"
    assert od["cycle_index"] == 0
    return scenario


def test_a_failing_eye_raises_the_cycle_count_and_queues_rework(api):
    """A 0.20 sphere delta against a 0.13 tolerance fails and rewinds the job.

    PRD 3.7: "A `FAIL` recorded while the job's `rework_cycle_count` is below 2
    drives the job `EDGED → REWORK_QUEUED` and raises `rework_cycle_count` by 1 —
    which invalidates any `PASS` recorded at the previous cycle index, since those
    records now sit at a stale `cycle_index` and can no longer complete a pair."

    Design: Difficulty/non_linear_state_machine/lab_job_rework_cycle_reenters_edged_and_invalidates_the_previous_cycle_pass
    """
    scenario = _edged_job_with_one_passing_eye(api)

    inspection = fixtures.inspect_eye(
        api, scenario["job_id"], "OS", **CYCLE0_OS_FAIL
    )

    assert inspection["verdict"] == "FAIL"
    assert inspection["failed_metrics"] == ["SPHERE"]
    assert inspection["sphere_delta"] == 0.20

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "REWORK_QUEUED"
    assert job["rework_cycle_count"] == 1


def test_re_edging_a_rework_queued_job_brings_it_back_to_edged(api):
    """A second edging window on the same bay reopens the job for inspection.

    PRD 3.7: "The rework loop then runs again: a rework-queued job may be
    re-surfaced or re-edged, returns to `EDGED` on completion, and is inspected
    afresh."

    Design: Difficulty/non_linear_state_machine/lab_job_rework_cycle_reenters_edged_and_invalidates_the_previous_cycle_pass
    """
    scenario = _edged_job_with_one_passing_eye(api)
    fixtures.inspect_eye(api, scenario["job_id"], "OS", **CYCLE0_OS_FAIL)

    operation = fixtures.book_edging(
        api, scenario, "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z"
    )
    validate_success(api.start_lab_operation(operation["id"], TECHNICIAN_A_HEADERS))
    completed = validate_success(
        api.complete_lab_operation(operation["id"], TECHNICIAN_A_HEADERS)
    )

    assert completed["status"] == "COMPLETED"
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "EDGED"


def test_the_cycle_zero_pass_no_longer_completes_the_two_eye_join(api):
    """One passing eye at cycle 1 leaves the job EDGED; only the pair reaches PASSED.

    PRD 3.7: "Two eyes must agree before a job may leave inspection, so the join
    fires only when both eyes hold a `PASS` at the *current* `cycle_index`."

    Design: Difficulty/non_linear_state_machine/lab_job_rework_cycle_reenters_edged_and_invalidates_the_previous_cycle_pass
    """
    scenario = _edged_job_with_one_passing_eye(api)
    fixtures.inspect_eye(api, scenario["job_id"], "OS", **CYCLE0_OS_FAIL)
    scenario = fixtures.surfaced_edged_job(
        api, scenario, "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z"
    )

    cycle1_od = fixtures.inspect_eye(api, scenario["job_id"], "OD", **CYCLE1_OD_PASS)
    assert cycle1_od["cycle_index"] == 1
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "EDGED"

    fixtures.inspect_eye(api, scenario["job_id"], "OS", **CYCLE1_OS_PASS)

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "PASSED"
    assert job["rework_cycle_count"] == 1
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == "IN_LAB"
