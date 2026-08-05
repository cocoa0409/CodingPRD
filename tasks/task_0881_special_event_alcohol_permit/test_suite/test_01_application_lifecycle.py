"""Application creation, retrieval, and submission gatekeeping.

Covers Corner/entities, Corner/endpoints (retrieval), and Corner/state_machines
and Corner/validations instances tied to the DRAFT -> SUBMITTED boundary.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_application_payload,
    assert_application,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["clerk_headers"]
APPLICANT = TEST_USERS["applicant_headers"]


def test_create_application_starts_in_draft(api):
    """PRD §3.2: "A newly created application begins in `DRAFT` with `balance_due_cents`
    at zero, `deposit_status` of `NONE`, a null `permit_number`, and all review counts at zero."

    Design: Corner/entities/application_create_success
    """
    venue = fixtures.create_venue(api)
    resp = api.create_application(create_application_payload(venue["id"]), APPLICANT)
    data = validate_success(resp, expected_status=201)
    assert_application(data)
    assert data["status"] == "DRAFT"
    assert data["balance_due_cents"] == 0
    assert data["deposit_status"] == "NONE"
    assert data["permit_number"] is None
    assert data["version"] == 1


def test_get_missing_application_returns_404(api):
    """PRD §2.5: "If any referenced resource does not exist, the request is rejected
    with the not-found error specific to that resource — `ERR_APPLICATION_NOT_FOUND`,
    `ERR_VENUE_NOT_FOUND`, ..."

    Design: Corner/entities/application_not_found_returns_404
    """
    resp = api.get_application(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_create_application_missing_event_name_rejected(api):
    """PRD §2.9: "Field-shape problems (a missing or wrongly typed body field, or an
    attendance figure that exceeds the venue's occupancy limit at submit) surface as
    `ERR_VALIDATION`".

    Design: Corner/entities/application_missing_required_field_returns_invalid_request
    """
    venue = fixtures.create_venue(api)
    payload = create_application_payload(venue["id"])
    payload.pop("event_name")
    resp = api.create_application(payload, APPLICANT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_application_wrapped_in_object_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources." and "The `api_request_id` is a server-generated
    unique identifier for the request that starts with `req_`."

    Design: Corner/endpoints/get_application_response_envelope
    """
    app = fixtures.create_application(api)
    resp = api.get_application(app["id"], APPLICANT)
    validate_success(resp)
    body = resp.json()
    assert body["response_type"] == "object"
    assert "api_request_id" in body["meta"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["data"]["id"] == app["id"]


def test_submit_already_submitted_application_rejected(api):
    """PRD §3.3: "Submission is refused unless the application is currently `DRAFT`
    (`ERR_APPLICATION_NOT_DRAFT`) and every gatekeeping condition below holds".

    Design: Corner/state_machines/submit_from_non_draft_rejected
    """
    ctx = fixtures.create_submitted_application(api)
    resp = api.submit_application(ctx["application"]["id"], APPLICANT)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT)


def test_submit_without_documents_rejected(api):
    """PRD §3.3: "At least one event server, at least one insurance policy, and at least
    one security plan already exist for the application, else `ERR_MISSING_REQUIRED_DOCUMENTS`."

    Design: Corner/validations/missing_documents_submit_rejected
    """
    app = fixtures.create_application(api)
    resp = api.submit_application(app["id"], APPLICANT)
    validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_DOCUMENTS)


