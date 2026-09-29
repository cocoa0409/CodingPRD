"""Two readings a hundredth of a diopter apart on a 0.13 diopter tolerance."""

from test_helpers import fixtures

AT_TOLERANCE_OD = {
    "measured_sphere": -3.13,
    "measured_cylinder": -1.25,
    "measured_axis": 90,
    "measured_prism": 0.5,
}
ONE_HUNDREDTH_OVER_OS = {
    "measured_sphere": -2.89,
    "measured_cylinder": -1.0,
    "measured_axis": 85,
    "measured_prism": 0.0,
}


def test_a_delta_exactly_equal_to_the_tolerance_passes(api):
    """A 0.13 sphere delta against a 0.13 tolerance is not an exceedance.

    PRD 3.7: "Every comparison is strictly greater-than, so a delta exactly equal to
    its tolerance passes."

    Design: Difficulty/boundary_precision_check/sphere_delta_exactly_at_tolerance_passes_and_one_hundredth_over_fails
    """
    scenario = fixtures.surfaced_edged_job(api)

    inspection = fixtures.inspect_eye(
        api, scenario["job_id"], "OD", **AT_TOLERANCE_OD
    )

    assert inspection["sphere_delta"] == 0.13
    assert inspection["verdict"] == "PASS"
    assert inspection["failed_metrics"] == []
    assert inspection["cycle_index"] == 0
    assert inspection["tolerance_standard_id"] == scenario["standard_id"]


def test_one_hundredth_of_a_diopter_more_fails_on_sphere_alone(api):
    """A 0.14 delta exceeds the same tolerance and reports SPHERE only.

    PRD 3.7: "`SPHERE` fails when `sphere_delta` is strictly greater than
    `sphere_tolerance_diopters`."

    Design: Difficulty/boundary_precision_check/sphere_delta_exactly_at_tolerance_passes_and_one_hundredth_over_fails
    """
    scenario = fixtures.surfaced_edged_job(api)
    fixtures.inspect_eye(api, scenario["job_id"], "OD", **AT_TOLERANCE_OD)

    inspection = fixtures.inspect_eye(
        api, scenario["job_id"], "OS", **ONE_HUNDREDTH_OVER_OS
    )

    assert inspection["sphere_delta"] == 0.14
    assert inspection["verdict"] == "FAIL"
    assert inspection["failed_metrics"] == ["SPHERE"]
    assert inspection["cycle_index"] == 0
    assert inspection["tolerance_standard_id"] == scenario["standard_id"]


def test_the_failing_eye_alone_decides_the_job_outcome(api):
    """The passing eye cannot save the pair; the job rewinds for rework.

    PRD 3.7: "A `FAIL` recorded while the job's `rework_cycle_count` is below 2 drives
    the job `EDGED → REWORK_QUEUED` and raises `rework_cycle_count` by 1 — which
    invalidates any `PASS` recorded at the previous cycle index, since those records
    now sit at a stale `cycle_index` and can no longer complete a pair."

    Design: Difficulty/boundary_precision_check/sphere_delta_exactly_at_tolerance_passes_and_one_hundredth_over_fails
    """
    scenario = fixtures.surfaced_edged_job(api)
    fixtures.inspect_eye(api, scenario["job_id"], "OD", **AT_TOLERANCE_OD)
    fixtures.inspect_eye(api, scenario["job_id"], "OS", **ONE_HUNDREDTH_OVER_OS)

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "REWORK_QUEUED"
    assert job["rework_cycle_count"] == 1
