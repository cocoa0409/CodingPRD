"""Platform-wide claims: authentication context, the response envelope with
pagination defaults, and configuration uniqueness (PRD §2.1, §2.2, §2.3,
§3.3, §3.6, §3.8)."""
from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    book_appointment,
    create_health_fee_pool_payload,
    create_immunization_requirement_payload,
    create_medication_stock_payload,
    create_student_payload,
    make_provider,
    make_student,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system
    does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    res = api.create_student(
        create_student_payload(external_ref="S33", full_name="No Auth"),
        ANONYMOUS_HEADERS,
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        expected_status=400,
    )


def test_appointment_list_envelope_and_pagination_defaults(api, health_admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`" and "`response_type` is either
    "object" for a single resource or "array" for a list of resources".
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10 ... The `offset` parameter
    specifies the number of items to skip and defaults to 0."
    PRD §2.3: "Paginated list-based responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/appointment_list_envelope_and_pagination_defaults
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S50", "Envelope")
    provider = make_provider("Dr U")
    book_appointment(
        student["id"], provider["id"], "FOLLOW_UP",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )

    res = api.list_appointments(health_admin_headers)
    body = res.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "array"

    data, meta = validate_paginated(res)
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["offset"] == 0, "default offset is 0"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1


def test_duplicate_configuration_rejected(api, health_admin_headers,
                                          pharmacist_headers):
    """PRD §3.3: "redefining an existing code is rejected with
    `ERR_DUPLICATE_REQUIREMENT`".
    PRD §3.6: "Creating a medication stock item requires a unique
    `medication_code` (duplicates are rejected with `ERR_DUPLICATE_MEDICATION`)".
    PRD §3.8: "At most one pool may be `OPEN` at any time — creating one while
    another is still open is rejected with `ERR_DUPLICATE_POOL_TERM`".

    Design: Corner/cross_cutting_layers/duplicate_configuration_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    validate_success(
        api.create_immunization_requirement(
            create_immunization_requirement_payload(
                vaccine_code="MMR", required_doses=2, min_interval_days=28,
                deadline_date="2026-08-01", grace_period_days=0,
            ),
            health_admin_headers,
        ),
        201,
    )
    validate_success(
        api.create_medication_stock(
            create_medication_stock_payload(
                medication_code="DOXY", medication_name="Doxycycline",
                initial_on_hand=10, reorder_threshold=0,
            ),
            pharmacist_headers,
        ),
        201,
    )
    validate_success(
        api.create_health_fee_pool(
            create_health_fee_pool_payload(
                term_code="SP26", budget_cents=100000, term_end_date="2026-08-31"
            ),
            health_admin_headers,
        ),
        201,
    )

    res1 = api.create_immunization_requirement(
        create_immunization_requirement_payload(
            vaccine_code="MMR", required_doses=1, min_interval_days=0,
            deadline_date="2026-09-01", grace_period_days=3,
        ),
        health_admin_headers,
    )
    validate_error(res1, ApiErrorId.ERR_DUPLICATE_REQUIREMENT, expected_status=409)

    res2 = api.create_medication_stock(
        create_medication_stock_payload(
            medication_code="DOXY", medication_name="Doxy Again",
            initial_on_hand=5, reorder_threshold=1,
        ),
        pharmacist_headers,
    )
    validate_error(res2, ApiErrorId.ERR_DUPLICATE_MEDICATION, expected_status=409)

    res3 = api.create_health_fee_pool(
        create_health_fee_pool_payload(
            term_code="SP26", budget_cents=50000, term_end_date="2026-08-31"
        ),
        health_admin_headers,
    )
    validate_error(res3, ApiErrorId.ERR_DUPLICATE_POOL_TERM, expected_status=409)
