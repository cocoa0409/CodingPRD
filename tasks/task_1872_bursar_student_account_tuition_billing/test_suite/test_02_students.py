"""Student registration, authentication, existence errors, and the paginated
student directory (PRD §2.1, §2.2, §2.3, §2.9, §3.1)."""
from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    create_student_payload,
    create_term_payload,
    make_student,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_TERM_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_STUDENT_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_ACCOUNT_ID = "00000000-0000-4000-8000-0000000000a1"
UNKNOWN_ENROLLMENT_ID = "00000000-0000-4000-8000-0000000000a2"
UNKNOWN_PAYMENT_ID = "00000000-0000-4000-8000-0000000000a3"


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role string
    the system does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    res = api.list_students(ANONYMOUS_HEADERS)
    validate_error(
        res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT, expected_status=400
    )


def test_term_not_found_returns_404(api, registrar_headers):
    """PRD §2.9: "Requests that address nested resources validate path
    identifiers strictly left to right and reject with a 404 on the first
    identifier that does not resolve: a missing term id yields
    `ERR_TERM_NOT_FOUND`".

    Design: Corner/validations/term_not_found_returns_404
    """
    res = api.get_term(UNKNOWN_TERM_ID, registrar_headers)
    validate_error(res, ApiErrorId.ERR_TERM_NOT_FOUND, expected_status=404)


def test_error_envelope_shape_on_404(api, bursar_staff_headers):
    """PRD §2.2: error responses carry "response_type": "error" and a data
    object with "error_id" plus a human-readable "message"; "The `meta` object
    for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §2.9: "a missing student id `ERR_STUDENT_NOT_FOUND`".

    Design: Corner/endpoints/error_envelope_shape_on_404
    """
    res = api.get_student(UNKNOWN_STUDENT_ID, bursar_staff_headers)
    error = validate_error(res, ApiErrorId.ERR_STUDENT_NOT_FOUND, expected_status=404)
    assert error["message"].strip(), "error message must be non-empty"
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)


def test_duplicate_code_and_external_ref_conflicts(api, registrar_headers):
    """PRD §3.1: "A duplicate `code` is rejected with `ERR_DUPLICATE_CODE`
    (HTTP 409)." and "an `external_ref` from the student information system
    which must be unique across all students (duplicates rejected with
    `ERR_DUPLICATE_EXTERNAL_REF`)".

    Design: Corner/errors/duplicate_code_and_external_ref_conflicts
    """
    validate_success(api.create_term(create_term_payload(), registrar_headers), 201)
    make_student("S-DUP", "First")

    res = api.create_term(
        create_term_payload(code="FALL-26", name="Fall Again",
                            refund_policy="PRO_RATA"),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CODE, expected_status=409)

    res = api.create_student(
        create_student_payload(
            full_name="Second", external_ref="S-DUP",
            residency_status="OUT_OF_STATE", level="GRADUATE",
        ),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_EXTERNAL_REF, expected_status=409)


def test_student_create_missing_required_returns_invalid_request(
    api, registrar_headers
):
    """PRD §3.1: "A `RegistrarStaff` operator registers a student with a
    `full_name`, an `external_ref` ... a `residency_status` of `IN_STATE`,
    `OUT_OF_STATE`, or `INTERNATIONAL`, and a `level`" — omitting the required
    `residency_status` is a malformed request, and PRD §3.1 states "malformed
    payloads, missing fields, bad enum values, or violations of this ordering
    are rejected with `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/student_create_missing_required_returns_invalid_request
    """
    res = api.create_student(
        {"full_name": "NoResidency", "external_ref": "S-NR", "level": "UNDERGRADUATE"},
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_students_pagination_envelope(api, registrar_headers, bursar_staff_headers):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`, where
    `total_count` reports the full size of the filtered result set and
    `has_more` indicates whether further items exist beyond the returned page."
    PRD §3.1/§4: the directory supports an "optional `residency_status` filter".

    Design: Corner/endpoints/students_pagination_envelope
    """
    for i in range(1, 11):
        make_student(f"P{i:02d}", f"P{i:02d}")
    make_student("P11", "P11", residency_status="OUT_OF_STATE", level="GRADUATE")
    make_student("P12", "P12", residency_status="OUT_OF_STATE", level="GRADUATE")

    page1 = api.list_students(bursar_staff_headers, params={"limit": 10, "offset": 0})
    data1, meta1 = validate_paginated(page1)
    assert len(data1) == 10, f"page 1 must hold 10 rows, got {len(data1)}"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    body = page1.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)

    data2, meta2 = validate_paginated(
        api.list_students(bursar_staff_headers, params={"limit": 10, "offset": 10})
    )
    assert len(data2) == 2, f"page 2 must hold the final 2 rows, got {len(data2)}"
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(
        api.list_students(
            bursar_staff_headers, params={"residency_status": "OUT_OF_STATE"}
        )
    )
    assert len(filtered) == 2, "residency filter must return exactly 2 rows"
    assert {s["external_ref"] for s in filtered} == {"P11", "P12"}


def test_not_found_variants_by_resource(api, bursar_staff_headers):
    """PRD §2.9: "a missing account id `ERR_ACCOUNT_NOT_FOUND`, a missing
    enrollment id `ERR_ENROLLMENT_NOT_FOUND`, and any other missing path id —
    payment, waiver, agreement, invoice, plan, installment, hold, refund, or
    tax form — yields `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/errors/not_found_variants_by_resource
    """
    res = api.get_account(UNKNOWN_ACCOUNT_ID, bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_FOUND, expected_status=404)
    res = api.get_enrollment(UNKNOWN_ENROLLMENT_ID, bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND, expected_status=404)
    res = api.get_payment(UNKNOWN_PAYMENT_ID, bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)
