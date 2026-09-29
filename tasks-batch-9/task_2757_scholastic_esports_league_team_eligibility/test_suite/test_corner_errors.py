"""Breadth tests for the ``errors`` design section.

One walk through seven catalogued statuses on the district / school / student
family, asserting the §2.2 error envelope is identical in shape every time and
that the error channel never leaks a domain field.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import HTTP_STATUS_CODES, ApiErrorId
from test_helpers.test_users import (
    ELIGIBILITY_OFFICER_ID,
    eligibility_officer_headers,
    headers_for_role,
    league_admin_headers,
    make_coach_headers,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _assert_error_envelope(response, error_id, status):
    """PRD §2.2 error envelope: ``response_type`` "error", ``data`` holding
    exactly ``error_id`` and ``message``, and the two ``meta`` fields."""
    assert response.status_code == status, (
        f"expected HTTP {status} for {error_id}, got {response.status_code}: "
        f"{response.text}"
    )
    validate_error(response, error_id, status)
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error body leaked domain fields: {sorted(body['data'].keys())}"
    )
    assert body["data"]["error_id"] == error_id
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""
    assert body["meta"]["api_request_id"].startswith("req_")
    A.assert_three_digit_millis(body["meta"]["api_request_timestamp"])
    return response.status_code


def _build_one_district_one_school_one_student(api):
    """A district, a school pinned to the paperwork code ``NCES-001``, and one
    freshly enrolled student at version 1."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"], nces_code="NCES-001")
    student = fx.make_student(api, school["id"])
    return {"district": district, "school": school, "student": student}


def test_seven_catalogued_statuses_share_one_error_envelope(api):
    """401, 403, 404, 400, 422, 409 and 412 on one entity family, each with the
    catalogued status and the same envelope.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`. The `error_id` is a unique,
    machine-readable string that identifies the specific error. The `message`
    provides a human-readable explanation of what went wrong."  PRD §2.1: "If
    either header is absent, or if `X-User-Role` is not one of the seven role
    names declared below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before anything else about the request is examined. Once the
    caller is authenticated, the role must appear in the target operation's
    authorized-role list ... rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "a district whose `probation_gpa_floor` is greater than its
    `min_gpa` is nonsensical and is refused with `ERR_INVALID_GPA_THRESHOLDS`"
    and "[the `nces_code`] must be unique among the schools of the same
    district; a collision is refused with `ERR_DUPLICATE_NCES_CODE`."  PRD §2.6:
    "If `expected_student_version` does not equal the student's current
    `version`, the posting is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §5: "Every error response uses the envelope of §2.2 and carries one of
    the identifiers below."

    Design: Corner/errors/every_error_response_uses_the_declared_error_envelope_and_its_catalogued_status
    """
    world = _build_one_district_one_school_one_student(api)
    student = world["student"]
    stale_version = student["version"]
    observed = []

    observed.append(
        _assert_error_envelope(
            api.get_district(
                world["district"]["id"], headers_for_role("Superintendent", "someone")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
    )

    observed.append(
        _assert_error_envelope(
            api.create_title(
                {
                    "name": "Rocket Clash",
                    "publisher": "Astro Interactive",
                    "age_rating": "E10",
                    "min_player_age": 13,
                },
                make_coach_headers("coach-x"),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
    )

    observed.append(
        _assert_error_envelope(
            api.get_student(MISSING_ID, league_admin_headers()),
            ApiErrorId.ERR_STUDENT_NOT_FOUND.value,
            404,
        )
    )

    observed.append(
        _assert_error_envelope(
            api.create_school(
                {"district_id": world["district"]["id"], "nces_code": "NCES-777"},
                league_admin_headers(),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
    )

    observed.append(
        _assert_error_envelope(
            api.create_district(
                {
                    "name": "Bad Thresholds District",
                    "state_code": "CA",
                    "min_gpa": 1.500,
                    "probation_gpa_floor": 2.000,
                },
                league_admin_headers(),
            ),
            ApiErrorId.ERR_INVALID_GPA_THRESHOLDS.value,
            422,
        )
    )

    observed.append(
        _assert_error_envelope(
            api.create_school(
                {
                    "district_id": world["district"]["id"],
                    "name": "Duplicate Code High",
                    "nces_code": "NCES-001",
                },
                league_admin_headers(),
            ),
            ApiErrorId.ERR_DUPLICATE_NCES_CODE.value,
            409,
        )
    )

    accepted = api.post_academic_term(
        student["id"],
        {
            "term_label": "2026-FALL",
            "term_gpa": 3.200,
            "term_credits": 6.0,
            "expected_student_version": stale_version,
        },
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
    )
    validate_success(accepted)
    posted = A.data_of(accepted)
    assert posted["version"] == stale_version + 1
    A.assert_gpa(posted["latest_term_gpa"], 3.200)

    observed.append(
        _assert_error_envelope(
            api.post_academic_term(
                student["id"],
                {
                    "term_label": "2026-SPRING",
                    "term_gpa": 2.900,
                    "term_credits": 6.0,
                    "expected_student_version": stale_version,
                },
                eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
            ),
            ApiErrorId.ERR_STALE_VERSION.value,
            412,
        )
    )

    assert observed == [401, 403, 404, 400, 422, 409, 412]
    assert len(set(observed)) == 7
    for error_id, status in (
        (ApiErrorId.ERR_UNAUTHENTICATED, 401),
        (ApiErrorId.ERR_UNAUTHORIZED, 403),
        (ApiErrorId.ERR_STUDENT_NOT_FOUND, 404),
        (ApiErrorId.ERR_INVALID_REQUEST, 400),
        (ApiErrorId.ERR_INVALID_GPA_THRESHOLDS, 422),
        (ApiErrorId.ERR_DUPLICATE_NCES_CODE, 409),
        (ApiErrorId.ERR_STALE_VERSION, 412),
    ):
        assert HTTP_STATUS_CODES[error_id] == status

    unchanged = fx.get_student(api, student["id"])
    assert unchanged["version"] == stale_version + 1
    A.assert_gpa(unchanged["latest_term_gpa"], 3.200)
    assert unchanged["latest_term_label"] == "2026-FALL"
    assert unchanged["prior_term_gpa"] is None
    assert unchanged["prior_term_credits"] is None
