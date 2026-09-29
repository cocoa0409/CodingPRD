"""Addressing an audit record the system does not hold.

Every kind of record an audit wave is assembled from — the program, the
subscriber, the dependent, the case, the proof submission, the appeal, the
termination notice and the claims recovery — answers an unresolvable reference
with its own identifier rather than with one generic 404, and it does so whether
the reference arrived in the request path or inside the request body.
"""
from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import ORIGIN_INSTANT
from test_helpers.test_users import ANALYST, PROGRAM_ADMIN, RECOVERY_AGENT, REVIEWER


def _census_of_one_household(b):
    """One registered subscriber holding one enrolled dependent."""
    b.set_clock(ORIGIN_INSTANT)
    employee = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    dependent = b.dependent(employee["id"], "SPOUSE")
    return employee, dependent


def _assert_error_meta(response) -> None:
    """An error envelope still carries the two server-generated meta fields."""
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str), meta
    assert meta["api_request_id"].startswith("req_"), meta
    assert isinstance(meta.get("api_request_timestamp"), str), meta


ADDRESSED_RESOURCE_KINDS = (
    pytest.param(
        lambda client: client.get_program(NON_EXISTENT_UUID, PROGRAM_ADMIN),
        E.ERR_PROGRAM_NOT_FOUND,
        id="audit_program",
    ),
    pytest.param(
        lambda client: client.get_employee(NON_EXISTENT_UUID, PROGRAM_ADMIN),
        E.ERR_EMPLOYEE_NOT_FOUND,
        id="employee",
    ),
    pytest.param(
        lambda client: client.get_dependent(NON_EXISTENT_UUID, PROGRAM_ADMIN),
        E.ERR_DEPENDENT_NOT_FOUND,
        id="dependent",
    ),
    pytest.param(
        lambda client: client.get_proof_submission(NON_EXISTENT_UUID, ANALYST),
        E.ERR_SUBMISSION_NOT_FOUND,
        id="proof_submission",
    ),
    pytest.param(
        lambda client: client.get_appeal(NON_EXISTENT_UUID, REVIEWER),
        E.ERR_APPEAL_NOT_FOUND,
        id="appeal",
    ),
    pytest.param(
        lambda client: client.get_notice(NON_EXISTENT_UUID, PROGRAM_ADMIN),
        E.ERR_NOTICE_NOT_FOUND,
        id="termination_notice",
    ),
    pytest.param(
        lambda client: client.get_claim_recovery(NON_EXISTENT_UUID, RECOVERY_AGENT),
        E.ERR_RECOVERY_NOT_FOUND,
        id="claim_recovery",
    ),
)


@pytest.mark.parametrize("read_missing_record,expected_error_id", ADDRESSED_RESOURCE_KINDS)
def test_each_addressed_record_kind_reports_its_own_lookup_failure_with_http_404(
    b, client, read_missing_record, expected_error_id
):
    """A missing program yields `ERR_PROGRAM_NOT_FOUND`, a missing employee
    `ERR_EMPLOYEE_NOT_FOUND`, a missing dependent `ERR_DEPENDENT_NOT_FOUND`, a
    missing case `ERR_CASE_NOT_FOUND`, a missing proof submission
    `ERR_SUBMISSION_NOT_FOUND`, a missing appeal `ERR_APPEAL_NOT_FOUND`, a missing
    termination notice `ERR_NOTICE_NOT_FOUND`, and a missing claim recovery
    `ERR_RECOVERY_NOT_FOUND`. All eight carry HTTP 404.

    Design: Corner/errors/corner_every_addressed_resource_kind_has_its_own_not_found_error
    """
    _census_of_one_household(b)

    response = read_missing_record(client)

    assert expected_error_id in E.NOT_FOUND_ERRORS, expected_error_id
    validate_error(response, expected_error_id, expected_status=404)
    assert response.json()["response_type"] == "error", response.json()
    _assert_error_meta(response)


def test_offering_proof_against_a_case_that_does_not_exist_reports_the_case_lookup_failure(
    b, client
):
    """The identical family of errors is raised when a reference supplied inside a
    request body — rather than in the path — cannot be resolved: submitting proof
    against a nonexistent case, filing an amnesty removal or appeal against a
    nonexistent dependent, opening a recovery against a nonexistent termination
    notice, or enrolling a dependent under a nonexistent employee all produce the
    corresponding 404.

    Design: Corner/errors/corner_every_addressed_resource_kind_has_its_own_not_found_error
    """
    _employee, dependent = _census_of_one_household(b)

    response = client.create_proof_submission(
        f.proof_submission_payload(
            NON_EXISTENT_UUID, dependent["id"], "MARRIAGE_CERTIFICATE"
        ),
        ANALYST,
    )

    assert E.ERR_CASE_NOT_FOUND in E.NOT_FOUND_ERRORS, E.NOT_FOUND_ERRORS
    validate_error(response, E.ERR_CASE_NOT_FOUND, expected_status=404)
    _assert_error_meta(response)

    _rows, meta = b.submissions(dependent_id=dependent["id"])
    assert meta["total_count"] == 0, meta
