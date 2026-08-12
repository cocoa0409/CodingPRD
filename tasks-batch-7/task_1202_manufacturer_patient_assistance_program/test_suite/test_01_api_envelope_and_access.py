"""API-wide concerns: response envelope, authentication, endpoint authorization,
not-found handling, and list pagination (PRD §2.1, §2.2, §2.3, §2.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_program,
    create_minimal_program_payload,
    create_patient_record,
    is_valid_uuid,
    make_patient_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_missing_auth_headers_returns_401():
    """PRD §2.1: "A request missing either header, or carrying a role string
    outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api_client._request("GET", "/pap/programs", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_patient_cannot_create_program():
    """PRD §2.1: "A request whose role is valid but not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 restricts
    POST /pap/programs to ProgramAdministrator.

    Design: Corner/validations/patient_cannot_create_program
    """
    patient = create_patient_record(full_name="Ada Aft")
    resp = api_client.create_program(
        create_minimal_program_payload(name="Sneaky", unit_cost_per_unit="1.0000",
                                       max_units_per_enrollment=1, max_units_per_shipment=1,
                                       max_annual_benefit_cents=100),
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_get_unknown_program_returns_404():
    """PRD §2.7: "Every identifier in the path and body resolves to an existing
    resource — program, budget period, patient, prescriber, screening, document,
    application, appeal, enrollment, circumstance, copay card, lot, shipment, or
    reconciliation run (`ERR_NOT_FOUND`)."

    Design: Corner/entities/program_not_found_returns_404
    """
    resp = api_client.get_program(NON_EXISTENT_UUID, fx.CW)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_error_envelope_shape_on_not_found():
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and error data carries
    `error_id` plus a `message` that "provides a human-readable explanation of
    what went wrong."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    resp = api_client.get_patient(NON_EXISTENT_UUID, fx.CW)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"], "meta.api_request_id must be present"


def test_programs_list_pagination_envelope():
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`." and "The `limit` parameter
    specifies the maximum number of items to return. If not provided, it
    defaults to 10, with a minimum of 1 and maximum of 100."

    Design: Corner/entities/programs_list_pagination_envelope
    """
    for _ in range(11):
        fx.create_program_record(**create_minimal_program_payload())

    page1, meta1 = validate_paginated(api_client.list_programs(fx.CW, params={"limit": 10, "offset": 0}))
    assert len(page1) == 10, f"page 1 must hold exactly 10 items, got {len(page1)}"
    assert meta1["total_count"] == 11
    assert meta1["has_more"] is True
    for row in page1:
        assert_program(row)
        assert is_valid_uuid(row["id"])

    page2, meta2 = validate_paginated(api_client.list_programs(fx.CW, params={"limit": 10, "offset": 10}))
    assert len(page2) == 1, f"page 2 must hold exactly 1 item, got {len(page2)}"
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 11
    ids1 = {r["id"] for r in page1}
    assert page2[0]["id"] not in ids1
