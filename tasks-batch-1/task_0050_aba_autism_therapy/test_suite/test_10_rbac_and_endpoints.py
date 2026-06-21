"""Role-based access control, authentication, the success envelope, and a
foreign-key-filtered list."""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_rbt_headers,
    setup_active_authorization,
    create_payer,
    schedule_session,
    factories,
)


# ─── Corner: RBAC denials ────────────────────────────────────────────────────

def test_rbt_cannot_create_authorization(api):
    """PRD §3.4: "Once a plan is approved, a `BillingSpecialist` creates an
    `Authorization` to fund it."
    PRD §2.1: "When a request carries valid headers but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbt_cannot_create_authorization
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    resp = api.create_authorization(
        factories.create_authorization_payload(sc["plan"]["id"], sc["payer"]["id"]),
        make_rbt_headers(sc["rbt"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_caregiver_cannot_create_client(api):
    """PRD §3.1: "An `IntakeCoordinator` then registers a `Client` — the child".
    PRD §2.1: "When a request carries valid headers but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/caregiver_cannot_create_client
    """
    payer = create_payer(api)
    resp = api.create_client(
        factories.create_client_payload(payer["id"], full_name="Cg Child",
                                        caregiver_user_id="cg-self"),
        TEST_USERS["caregiver_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    resp = api.raw_get("/payers/00000000-0000-4000-8000-000000000001", headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ─── Corner: FK-filtered list ────────────────────────────────────────────────

def test_list_sessions_filtered_by_authorization(api):
    """PRD §3.6: "Sessions can be listed and optionally filtered by
    `authorization_id` or `provider_id`".

    Design: Corner/endpoints/fk_filter_list_therapy_sessions_by_authorization
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-02-02T09:00:00Z",
                     scheduled_end="2026-02-02T11:00:00Z", scheduled_units=8)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-02-03T09:00:00Z",
                     scheduled_end="2026-02-03T10:00:00Z", scheduled_units=4)
    resp = api.list_sessions(TEST_USERS["billing_headers"],
                             params={"authorization_id": sc["authorization"]["id"]})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(data) == 2, f"expected 2 filtered sessions, got {len(data)}"
    assert all(s["authorization_id"] == sc["authorization"]["id"] for s in data)


# ─── Corner: success envelope on create ──────────────────────────────────────

def test_success_envelope_has_meta_and_object_type(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_meta_present_on_success
    """
    resp = api.create_payer(factories.create_payer_payload(name="Env Payer"),
                            TEST_USERS["billing_headers"])
    validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object", body["response_type"]
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["id"]
