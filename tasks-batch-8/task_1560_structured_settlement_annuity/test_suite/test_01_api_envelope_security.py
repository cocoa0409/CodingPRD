"""API envelope, authentication, authorization, and read-path errors (PRD §2.1, §2.2, §2.3)."""
from test_helpers import (
    validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_profile, create_payee, setup_executed_agreement, add_draft_schedule,
    create_settlement_agreement_payload, create_scheduled_payment_payload,
    TEST_USERS, make_operations_specialist_headers, make_payee_headers,
)

# create_settlement_agreement_payload is imported for the unknown-state-profile case.

ADMIN = TEST_USERS["platform_admin_headers"]
CASE_MGR = TEST_USERS["case_manager_headers"]
READER = TEST_USERS["reader_headers"]


def test_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request missing either header, or presenting a role string outside
    this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/errors/missing_auth_headers_returns_400
    """
    resp = api.list_payees(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_get_nonexistent_payee_returns_not_found(api):
    """PRD §2.10: "Existence: path identifiers are validated left to right, then
    body-referenced identifiers (`payee_id`, `settlement_agreement_id`, and the like)
    must resolve — `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/errors/get_nonexistent_payee_returns_not_found
    """
    resp = api.get_payee(NON_EXISTENT_UUID, READER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_unknown_state_profile_returns_404(api):
    """PRD §2.8: "Any state code that fails to resolve to a registered profile — a
    payee's `address_state_code`, an agreement's `court_state_code`, or a change
    request's `new_address_state_code` — fails the request with
    `ERR_STATE_PROFILE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/unknown_state_profile_returns_404
    """
    create_profile()
    payee = create_payee()
    resp = api.create_settlement_agreement(
        create_settlement_agreement_payload(payee["id"], case_number="ER-001",
                                            court_state_code="ZZ"), CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_STATE_PROFILE_NOT_FOUND)


def test_error_envelope_shape_on_state_error(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_on_state_error
    """
    ctx = setup_executed_agreement()
    resp = api.execute_settlement_agreement(ctx["agreement"]["id"], CASE_MGR)
    error_data = validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)
    body = resp.json()
    assert body["response_type"] == "error"
    assert error_data["error_id"] == "ERR_AGREEMENT_INVALID_STATE"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id is a server-generated identifier that starts with req_"
    )


def test_list_endpoint_envelope_and_pagination(api):
    """PRD §2.3: "The `meta` object of a list response carries four pagination fields:
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `offset` parameter sets the number of items skipped and defaults to 0."

    Design: Corner/endpoints/list_endpoint_envelope_and_pagination
    """
    create_profile()
    created = [create_payee(full_name=f"Page {name}", tax_id=f"474-0{i}-000{i}")
               for i, name in enumerate(("One", "Two", "Three"), start=1)]

    page1, meta1 = validate_paginated(api.list_payees(READER, params={"limit": 2}))
    assert len(page1) == 2, f"page 1 should hold 2 payees, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_payees(READER, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1, f"page 2 should hold 1 payee, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    seen = {p["id"] for p in page1} | {p["id"] for p in page2}
    assert seen == {p["id"] for p in created}, "pages must cover all payees with no duplicates"


def test_rbac_operations_specialist_cannot_open_batch(api):
    """PRD §2.1: "A request whose role is well-formed but not authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /annuity/escheatment-batches is authorized for ComplianceOfficer only.

    Design: Corner/rbac/rbac_operations_specialist_cannot_open_batch
    """
    create_profile(state_code="OR", sspa_max_discount_rate_bps=1500,
                   disclosure_cooling_off_days=15, ipa_required=False,
                   dormancy_years=1)
    resp = api.create_escheatment_batch(
        {"state_code": "OR", "batch_period": "2027-09"},
        make_operations_specialist_headers("ops-9"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_rbac_payee_cannot_create_scheduled_payment(api):
    """PRD §2.1: "A request whose role is well-formed but not authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /annuity/scheduled-payments is authorized for CaseManager only.

    Design: Corner/rbac/rbac_payee_cannot_create_scheduled_payment
    """
    ctx = setup_executed_agreement()
    add_draft_schedule(ctx, [])
    resp = api.create_scheduled_payment(
        create_scheduled_payment_payload(ctx["schedule"]["id"], ctx["payee"]["id"], 1,
                                         "2027-01-01", 50000),
        make_payee_headers(ctx["payee"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
