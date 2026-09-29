"""Corner queue - section validations, part A: the top of the precedence ladder."""
from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    licensed_respondent,
    make_respondent_headers,
    new_jurisdiction,
    open_questionnaire,
    read_respondent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, RM, RM_ID


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_missing_auth_headers_win_over_a_nonexistent_path_id(api):
    """The request is invalid twice over, so the answer proves the authentication rung is
    evaluated before the path is resolved; an unknown role name is the same rung.

    Design: Corner/validations/missing_auth_headers_win_over_a_nonexistent_path_id
    """
    response = api.get_respondent(NON_EXISTENT_UUID, {})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    unknown_role = api.get_respondent(
        NON_EXISTENT_UUID, build_user_headers("user-auditor-01", "Auditor")
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_forbidden_role_is_decided_before_the_path_id_is_resolved(api):
    """A role outside the endpoint's list addressing an unknown id learns only that the role is
    wrong, never that the row is missing.

    Design: Corner/validations/forbidden_role_is_decided_before_the_path_id_is_resolved
    """
    response = api.amend_respondent(
        NON_EXISTENT_UUID, {"legal_name": "Renamed Bank AG"}, COMMITTEE
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_respondent_contact_cannot_reach_another_respondents_questionnaire(api):
    """The acting role is permitted on the endpoint, so the refusal has to come from the
    ownership rung, which must be resolved through the parent row rather than from the URL.

    Design: Corner/validations/respondent_contact_cannot_reach_another_respondents_questionnaire
    """
    _de()
    first = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    second = licensed_respondent(
        "DE", legal_name="Sudbank AG", swift_bic="SUEDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    questionnaire = open_questionnaire(first["id"])

    response = api.create_control_assessment(
        questionnaire["id"],
        {"control_domain": "GOVERNANCE", "self_rating": 3},
        make_respondent_headers(second["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RESPONDENT_SCOPE_VIOLATION, expected_status=403)

    _rows, meta = validate_paginated(
        api.list_control_assessments(ANALYST, params={"questionnaire_id": questionnaire["id"]})
    )
    assert meta["total_count"] == 0


def test_path_id_resolution_precedes_body_referential_checks(api):
    """Two different rows are unresolvable at once, one named in the path and one in the body,
    and the path is what the caller is told about.

    Design: Corner/validations/path_id_resolution_precedes_body_referential_checks
    """
    response = api.create_observation(
        NON_EXISTENT_UUID,
        {"period_month": "2026-07", "corridor_jurisdiction_code": "ZZ",
         "aggregate_usd": 1000.00, "txn_count": 3},
        ANALYST,
    )
    validate_error(
        response, ApiErrorId.ERR_MONITORING_PROFILE_NOT_FOUND, expected_status=404
    )


def test_missing_required_field_on_respondent_creation(api):
    """A required input with no default is missing, which is a body-shape failure rather than
    a uniqueness or referential one, and nothing is written.

    Design: Corner/validations/missing_required_field_on_respondent_creation
    """
    _de()

    response = api.create_respondent(
        {"legal_name": "Nordbank AG", "home_jurisdiction_code": "DE",
         "relationship_manager_user_id": RM_ID, "expected_monthly_volume_usd": 500000.00,
         "expected_monthly_count": 100},
        RM,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST_BODY, expected_status=400)

    _rows, meta = validate_paginated(api.list_respondents(RM))
    assert meta["total_count"] == 0


def test_type_wrong_numeric_field_is_a_body_error_not_a_range_error(api):
    """A numeric field arriving as prose fails the declared-type rung, which sits above the
    numeric-domain rung, so the range error never gets a chance to fire.

    Design: Corner/validations/type_wrong_numeric_field_is_a_body_error_not_a_range_error
    """
    _de()

    response = api.create_respondent(
        {"legal_name": "Nordbank AG", "swift_bic": "NORDDEFF", "home_jurisdiction_code": "DE",
         "relationship_manager_user_id": RM_ID,
         "expected_monthly_volume_usd": "half a million", "expected_monthly_count": 100},
        RM,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST_BODY, expected_status=400)


def test_unknown_payload_fields_are_ignored_on_creation(api):
    """Undeclared keys are ignored rather than rejected, and a system-managed field supplied
    in the body is ignored too rather than being honoured.

    Design: Corner/validations/unknown_payload_fields_are_ignored_on_creation
    """
    _de()

    created = validate_success(
        api.create_respondent(
            {"legal_name": "Nordbank AG", "swift_bic": "NORDDEFF",
             "home_jurisdiction_code": "DE", "relationship_manager_user_id": RM_ID,
             "expected_monthly_volume_usd": 500000.00, "expected_monthly_count": 100,
             "internal_underwriting_notes": "ignore me", "dd_state": "APPROVED"},
            RM,
        ),
        expected_status=201,
    )

    assert "internal_underwriting_notes" not in created
    assert created["dd_state"] == "PROSPECT"
    assert read_respondent(created["id"])["dd_state"] == "PROSPECT"
