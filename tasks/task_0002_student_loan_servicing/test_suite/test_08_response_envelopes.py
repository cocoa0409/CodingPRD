"""Response envelope structure for success and error responses, per PRD §2.2."""
from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock, create_borrower,
)


def test_response_envelope_success_object_structure(api, servicer_headers):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body..."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_success_object_structure
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="envelope-test@example.com")
    res = api.get_borrower(borrower["id"], servicer_headers)
    assert res.status_code == 200
    body = res.json()
    assert "meta" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_'; got {body['meta']['api_request_id']!r}"
    )
    assert body["response_type"] == "object"
    assert body["data"]["id"] == borrower["id"]


def test_response_envelope_error_structure(api, servicer_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format..."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/endpoints/response_envelope_error_structure
    """
    res = api.get_borrower(NON_EXISTENT_UUID, servicer_headers)
    assert res.status_code == 404
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert body["data"]["error_id"].startswith("ERR_")
    assert isinstance(body["data"].get("message"), str)
    assert len(body["data"]["message"].strip()) > 0, "error message must be non-empty"
