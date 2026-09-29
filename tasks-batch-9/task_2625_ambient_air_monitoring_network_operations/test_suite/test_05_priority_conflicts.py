"""Rejection precedence when one request breaks two rules at once."""

from test_helpers import (
    ADMIN_HEADERS,
    EPA_HEADERS,
    ERR_CERTIFICATION_DEADLINE_PASSED,
    ERR_MEMBER_BATCH_NOT_VALIDATED,
    ERR_METHOD_NOT_DESIGNATED,
    ERR_MONITOR_QC_DELINQUENT,
    PM_HEADERS,
    QA2_HEADERS,
    QA_HEADERS,
    canonical_environment,
    get_success_data,
    set_clock,
    submitted_package,
    twelve_validated_quarters,
    validate_error,
    validate_success,
)


def _package_with_a_reopened_member_past_the_deadline(api):
    env = twelve_validated_quarters(api)
    submitted_package(env, year=2025)
    validate_success(
        api.reopen_batch(
            env.batch_id(2025, 1),
            {"reopen_reason": "Audit flagged the first quarter"},
            QA_HEADERS,
        )
    )
    set_clock(api, "2026-06-01T00:00:00Z")
    return env


def test_the_member_state_gate_answers_before_the_deadline_gate(api):
    """A reopened member quarter blocks certification even a month past the deadline.

    PRD 3.8: "The state gate comes first: every quarter in the package's scope that is
    already in `submission_status` `SUBMITTED` must still have `validation_status`
    `VALIDATED`, so a quarter reopened after the package was submitted blocks
    certification with `ERR_MEMBER_BATCH_NOT_VALIDATED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/certify_member_batch_state_conflict_beats_deadline_conflict
    """
    env = _package_with_a_reopened_member_past_the_deadline(api)

    response = api.certify_package(
        env.package_id,
        {"certification_statement": "Data certified as complete and accurate"},
        PM_HEADERS,
    )
    error = validate_error(response, ERR_MEMBER_BATCH_NOT_VALIDATED, 409)
    assert error["error_id"] != ERR_CERTIFICATION_DEADLINE_PASSED


def test_the_refused_certification_leaves_the_package_and_quarter_untouched(api):
    """Nothing is certified and the pinned deadline is still readable.

    PRD 3.8: "First, `certification_deadline` is pinned to the first of May of the year
    following `year`, at midnight UTC."

    Design: Difficulty/priority_pair_validation_conflict/certify_member_batch_state_conflict_beats_deadline_conflict
    """
    env = _package_with_a_reopened_member_past_the_deadline(api)
    api.certify_package(env.package_id, {}, PM_HEADERS)

    package = get_success_data(api.get_package(env.package_id, PM_HEADERS))
    assert package["status"] == "SUBMITTED"
    assert package["certified_by_user_id"] is None
    assert package["certification_deadline"].startswith("2026-05-01T00:00:00")

    assert env.read_batch(2025, 1)["submission_status"] == "SUBMITTED"


def _withdrawn_method_over_a_delinquent_instrument(api):
    env = canonical_environment(
        api, clock="2025-11-01T00:00:00Z", span_check_at="2025-11-01T00:00:00Z"
    )
    batch = get_success_data(
        api.create_data_batch(
            {
                "monitor_id": env.monitor_id,
                "year": 2025,
                "quarter": 3,
                "scheduled_hour_count": 2208,
                "quarterly_mean_concentration": 9.1,
            },
            QA_HEADERS,
        )
    )
    validate_success(api.begin_validation(batch["id"], {}, QA_HEADERS))
    validate_success(
        api.change_designation(
            env.method_id,
            {
                "new_designation_status": "WITHDRAWN",
                "determination_note": "Method designation withdrawn by the Administrator",
            },
            EPA_HEADERS,
        )
    )
    set_clock(api, "2026-01-05T00:00:00Z")
    return env, batch["id"]


def test_the_referential_designation_gate_answers_before_the_safety_gate(api):
    """A withdrawn designation outranks a delinquent instrument on validation.

    PRD 2.11: "The practical consequence to keep in mind is that a delinquent-posture
    failure on a quarter validation surfaces as `ERR_MONITOR_QC_DELINQUENT` only when the
    segregation-of-duties bar has already passed, and a withdrawn method designation
    surfaces as `ERR_METHOD_NOT_DESIGNATED` before either of them, because referential
    rules precede safety rules."

    Design: Difficulty/priority_pair_validation_conflict/validate_method_designation_beats_qc_delinquency
    """
    env, batch_id = _withdrawn_method_over_a_delinquent_instrument(api)

    response = api.validate_batch(batch_id, {"validation_note": "Quarter reviewed"}, QA2_HEADERS)
    error = validate_error(response, ERR_METHOD_NOT_DESIGNATED, 422)
    assert error["error_id"] != ERR_MONITOR_QC_DELINQUENT


def test_both_failing_conditions_are_genuinely_present_on_the_refused_quarter(api):
    """The withdrawal is stamped and the instrument really is delinquent.

    PRD 3.3: "An elapsed-days figure no greater than the interval yields `QC_CURRENT`; an
    elapsed figure greater than the interval but no greater than the interval plus a grace
    period of one week yields `QC_DUE`; anything beyond that yields `QC_DELINQUENT`."

    Design: Difficulty/priority_pair_validation_conflict/validate_method_designation_beats_qc_delinquency
    """
    env, batch_id = _withdrawn_method_over_a_delinquent_instrument(api)
    api.validate_batch(batch_id, {}, QA2_HEADERS)

    method = get_success_data(api.get_reference_method(env.method_id, ADMIN_HEADERS))
    assert method["designation_status"] == "WITHDRAWN"
    assert method["withdrawn_on"].startswith("2025-11-01T00:00:00")

    assert env.read_monitor()["qc_posture"] == "QC_DELINQUENT"

    quarter = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
    assert quarter["validation_status"] == "IN_VALIDATION"
    assert quarter["validated_by_user_id"] is None
