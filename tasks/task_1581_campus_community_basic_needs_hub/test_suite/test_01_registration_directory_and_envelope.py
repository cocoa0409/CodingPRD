"""Registration, staff directory, and response-envelope claims."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_client,
    create_client_payload,
    create_coordinator,
    create_staff_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["hub_admin_headers"]


def test_student_with_fewer_than_six_credits_rejected(api, anonymous_headers):
    """PRD §3.1: "The optional `enrolled_credits` defaults to 0 and may
    legitimately be 0, except that an `ENROLLED_STUDENT` must carry at least
    6 credits this term; fewer is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/client_create_student_with_five_credits_returns_400
    """
    res = api.create_client(
        create_client_payload(
            alias_name="u", population_type="ENROLLED_STUDENT", enrolled_credits=3
        ),
        anonymous_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    # The rejection halts the cascade (PRD §2.6): no client row is persisted.
    _, coord = create_coordinator()
    data, meta = validate_paginated(api.list_clients(coord))
    assert meta["total_count"] == 0, f"Rejected creation leaked a row: {data}"


def test_client_creation_applies_defaults(api, anonymous_headers):
    """PRD §3.1: "The optional `enrolled_credits` defaults to 0 ... A newly
    registered client is `INTAKE_PENDING` ... with `risk_tier` null until that
    first verification."
    PRD §2.5: "`id` — a server-minted unique identifier formatted as a UUID,
    with no type prefix."

    Design: Corner/entities/client_create_defaults_applied
    """
    res = api.create_client(
        create_client_payload(alias_name="d", contact_channel="NONE"),
        anonymous_headers,
    )
    client = validate_success(res, 201)
    assert_client(client)
    assert client["enrolled_credits"] == 0, (
        f"enrolled_credits default must be 0, got {client['enrolled_credits']}"
    )
    assert client["status"] == "INTAKE_PENDING"
    assert client["risk_tier"] is None
    assert is_valid_uuid(client["id"]), "id must be a bare UUID (no type prefix)"
    assert isinstance(client["version"], int)


def test_get_nonexistent_client_returns_404(api):
    """PRD §2.6: "The first identifier that does not resolve yields
    `ERR_NOT_FOUND`, and no later segment is examined."

    Design: Corner/entities/client_get_nonexistent_returns_404
    """
    _, coord = create_coordinator()
    res = api.get_client(NON_EXISTENT_UUID, coord)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_staff_duplicate_email_rejected(api, hub_admin_headers):
    """PRD §3.1: "The `email` must be unique across the directory; a duplicate
    is rejected with `ERR_DUPLICATE_STAFF_EMAIL`."

    Design: Corner/entities/staff_duplicate_email_rejected
    """
    first = api.create_staff(
        create_staff_payload(
            full_name="C Co", email="coord@hub.test", staff_role="INTAKE_COORDINATOR"
        ),
        hub_admin_headers,
    )
    validate_success(first, 201)
    res = api.create_staff(
        create_staff_payload(
            full_name="C Other", email="coord@hub.test", staff_role="PANTRY_STAFF"
        ),
        hub_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_STAFF_EMAIL, expected_status=409)


def test_clients_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped and defaults to 0. ...
    List responses carry `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."
    PRD §2.2: every success body carries meta.api_request_id,
    meta.api_request_timestamp, response_type, and data.

    Design: Corner/endpoints/clients_list_pagination_envelope
    """
    _, coord = create_coordinator()
    for i in range(12):
        res = api.create_client(
            create_client_payload(alias_name=f"p{i + 1:02d}"), ANON
        )
        validate_success(res, 201)

    page1, meta1 = validate_paginated(api.list_clients(coord, params={"limit": 10, "offset": 0}))
    assert len(page1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_clients(coord, params={"limit": 10, "offset": 10}))
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    # limit 0 is below the pagination minimum of 1.
    res = api.list_clients(coord, params={"limit": 0})
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_error_envelope_shape_on_business_failure(api):
    """PRD §2.2: error responses carry `response_type` "error" and a `data`
    object with a machine-readable `error_id` and a human-readable `message`;
    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §3.2: "Submission requires `consent_confidential` to be true, else
    `ERR_CONSENT_REQUIRED`".

    Design: Corner/endpoints/error_envelope_shape_on_business_failure
    """
    _, coord = create_coordinator()
    client = validate_success(
        api.create_client(create_client_payload(alias_name="env"), ANON), 201
    )
    assessment = validate_success(
        api.create_assessment(
            client["id"],
            {
                "household_size": 1,
                "monthly_income_cents": 50000,
                "housing_status": "STABLE",
                "dependents_under_18": 0,
                "receives_snap": False,
                "receives_childcare_subsidy": False,
                "food_insecurity_score": 1,
                "consent_confidential": False,
            },
            coord,
        ),
        201,
    )
    res = api.submit_assessment(client["id"], assessment["id"], coord)
    error = validate_error(res, ApiErrorId.ERR_CONSENT_REQUIRED, expected_status=422)
    assert error["message"].strip(), "error envelope must carry a human-readable message"

    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)

    # The rejected submit leaves the assessment DRAFT.
    listing = validate_success(
        api.list_assessments(coord, params={"client_id": client["id"]}), 200
    )
    assert listing[0]["status"] == "DRAFT"
