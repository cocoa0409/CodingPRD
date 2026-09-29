"""Homebuyer education enrollments, module outcomes, and their readiness cascades."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import COORDINATOR


def test_the_third_missed_session_fails_the_curriculum_and_unwinds_readiness(api):
    """Two misses are survivable; the third ends the enrollment and the readiness.

    "The record that brings `missed_session_count` to 3 — the third miss, arriving
    when two had already been recorded — fails the enrollment: `IN_PROGRESS →
    FAILED`." That failure bubbles up: "Failure of the core curriculum cascades the
    other way: readiness falls `EDUCATION_IN_PROGRESS → NOT_READY`."

    Enrolling had pushed readiness the other way, since "enrolling a household in
    `HOMEBUYER_CORE` while its readiness is `NOT_READY` moves readiness `NOT_READY →
    EDUCATION_IN_PROGRESS`".

    Design: Corner/state_machines/third_missed_session_fails_education_and_regresses_readiness
    """
    program = X.setup_program(api)
    household = X.setup_selected_household(api, program["id"])["household"]

    enrollment = X.setup_enrollment(api, household["id"], required_module_count=4)
    assert enrollment["status"] == C.ENROLLMENT_ENROLLED

    first = X.record_module(api, enrollment["id"], outcome=C.OUTCOME_MISSED, module_code="M1")
    assert first["status"] == C.ENROLLMENT_IN_PROGRESS
    second = X.record_module(api, enrollment["id"], outcome=C.OUTCOME_MISSED, module_code="M2")
    # The SECOND miss does not fail the enrollment.
    assert second["status"] == C.ENROLLMENT_IN_PROGRESS
    assert second["missed_session_count"] == 2
    assert second["passed_module_count"] == 0

    before = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert before["partnership_readiness"] == C.READINESS_EDUCATION_IN_PROGRESS
    assert before["selection_status"] == C.SELECTION_SELECTED

    failed = validate_success(
        api.record_module_completion(
            enrollment["id"],
            F.module_completion_payload(outcome=C.OUTCOME_MISSED, module_code="M3"),
            headers=COORDINATOR,
        )
    )
    assert failed["status"] == C.ENROLLMENT_FAILED
    assert failed["missed_session_count"] == 3
    assert failed["completed_on"] is None
    assert failed["expires_on"] is None

    after = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert after["partnership_readiness"] == C.READINESS_NOT_READY
    # The two dimensions of the household moved independently.
    assert after["selection_status"] == C.SELECTION_SELECTED

    validate_error(
        api.record_module_completion(
            enrollment["id"],
            F.module_completion_payload(outcome=C.OUTCOME_PASSED, module_code="M4"),
            headers=COORDINATOR,
        ),
        E.ERR_ALREADY_TERMINAL,
        409,
    )


def test_enrollment_uniqueness_is_scoped_to_the_curriculum_not_the_household(api):
    """A second core enrollment is refused while the other two curricula open freely.

    "A household may hold only one enrollment per curriculum in `ENROLLED`,
    `IN_PROGRESS`, or `COMPLETED` status — a second one is refused with
    `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/validations/a_second_open_homebuyer_core_enrollment_is_rejected
    """
    program = X.setup_program(api)
    household = X.setup_selected_household(api, program["id"])["household"]

    enrollment = X.setup_enrollment(api, household["id"], required_module_count=2)
    X.record_module(api, enrollment["id"], outcome=C.OUTCOME_PASSED, module_code="HBC-01")

    validate_error(
        api.create_enrollment(
            F.enrollment_payload(household["id"], required_module_count=2), headers=COORDINATOR
        ),
        E.ERR_DUPLICATE_ENROLLMENT,
        409,
    )

    budget = validate_success(
        api.create_enrollment(
            F.enrollment_payload(
                household["id"], curriculum_code=C.CURRICULUM_BUDGET_COACHING, required_module_count=1
            ),
            headers=COORDINATOR,
        ),
        201,
    )
    assert budget["status"] == C.ENROLLMENT_ENROLLED
    maintenance = validate_success(
        api.create_enrollment(
            F.enrollment_payload(
                household["id"], curriculum_code=C.CURRICULUM_HOME_MAINTENANCE, required_module_count=1
            ),
            headers=COORDINATOR,
        ),
        201,
    )
    assert maintenance["status"] == C.ENROLLMENT_ENROLLED

    core_rows, core_meta = validate_paginated(
        api.list_enrollments(
            {"household_id": household["id"], "curriculum_code": C.CURRICULUM_HOMEBUYER_CORE},
            headers=COORDINATOR,
        )
    )
    assert core_meta["total_count"] == 1
    assert core_rows[0]["id"] == enrollment["id"]
    assert core_rows[0]["passed_module_count"] == 1
    assert core_rows[0]["status"] == C.ENROLLMENT_IN_PROGRESS

    _, all_meta = validate_paginated(
        api.list_enrollments({"household_id": household["id"]}, headers=COORDINATOR)
    )
    assert all_meta["total_count"] == 3
