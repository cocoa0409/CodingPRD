"""Client registration shape/defaults, required-field and enum validation,
referenced-FK existence, listing envelopes, and RBAC enforcement
(PRD §2.1, §2.4, §2.7, §3.1).

Covers the entities, errors, and rbac corner probes.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    set_clock, create_client, submit_intake, cleared_client, accepting_therapist,
    propose_match, accept_match, create_subscription, subscription_with_paid_cycle,
    active_match, schedule_session, get_match_version,
    api_client, make_client_headers, make_therapist_headers,
)
from test_helpers import TEST_USERS


def _client(cid):
    return make_client_headers(cid)


def _therapist(tid):
    return make_therapist_headers(tid)


def _clinical():
    return TEST_USERS["clinical_admin_headers"]


def _billing():
    return TEST_USERS["billing_admin_headers"]


# ==========================================================================
# Corner (entities): create client returns 201 with system defaults
# ==========================================================================
def test_create_client_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created client begins in `PENDING_INTAKE` with `financial_aid_tier` of
    `NONE`, `wallet_credit_cents` of zero, and `risk_flag` of `NONE`"

    Design: Corner/entities/create_client_returns_201_with_defaults
    """
    set_clock("2026-05-01T00:00:00Z")
    client = validate_success(api.create_client(
        {"email": "c1@x.com", "full_name": "C One", "state_code": "CA"},
        TEST_USERS["client_headers"],
    ), 201)
    assert client["status"] == "PENDING_INTAKE", client
    assert client["financial_aid_tier"] == "NONE", client
    assert client["wallet_credit_cents"] == 0, client
    assert client["risk_flag"] == "NONE", client


def test_new_client_version_starts_at_one(api):
    """PRD §2.4: "The `version` field is an integer that begins at its initial value and increments
    by one on every mutation; it underpins the optimistic-concurrency mechanism in §2.9."
    PRD §3.1: "A newly created client begins in `PENDING_INTAKE`"

    Design: Corner/entities/system_fields_generated_id_ignored_on_input
    """
    set_clock("2026-05-01T00:00:00Z")
    client = validate_success(api.create_client(
        {"email": "c5@x.com", "full_name": "C Five", "state_code": "CA"},
        TEST_USERS["client_headers"],
    ), 201)
    assert client["version"] == 1, client
    assert client["status"] == "PENDING_INTAKE", client


# ==========================================================================
# Corner (entities): not-found on missing client
# ==========================================================================
def test_get_client_not_found(api):
    """PRD §2.7: "the server validates the path identifiers left to right and rejects the request
    with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing
    resource."

    Design: Corner/entities/get_client_not_found_returns_404
    """
    resp = api.get_client(NON_EXISTENT_UUID, _clinical())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ==========================================================================
# Corner (entities): missing required field on create
# ==========================================================================
def test_create_client_missing_state_code_rejected(api):
    """PRD §3.1: "A person joins the platform by self-registering as a `Client`, supplying their
    `email`, their `full_name`, and the `state_code` of their US state of residence."
    PRD §2.11: "the request body inspected for well-formedness — required fields present ... with
    any failure raising `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_client_missing_required_field_returns_invalid_request
    """
    resp = api.create_client(
        {"email": "c2@x.com", "full_name": "C Two"}, TEST_USERS["client_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# Corner (entities): bad enum state_code on create
# ==========================================================================
def test_create_client_bad_state_code_rejected(api):
    """PRD §2.9: "its `state_code` is one of `CA`, `NY`, `TX`, `FL`, `WA`, or `IL`."
    PRD §2.11: "the request body inspected for well-formedness — required fields present, enum
    values within their allowed sets ... with any failure raising `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/create_client_bad_enum_state_returns_invalid_request
    """
    resp = api.create_client(
        {"email": "c3@x.com", "full_name": "C Three", "state_code": "ZZ"},
        TEST_USERS["client_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# Corner (entities): referenced FK not found on subscription create
# ==========================================================================
def test_subscription_create_referenced_client_not_found(api):
    """PRD §2.7: "when a create request carries a foreign key in its body that points to a
    resource which does not exist, the request is rejected with `ERR_REFERENCED_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/referenced_fk_not_found_on_subscription_create
    """
    resp = api.create_subscription({"client_id": NON_EXISTENT_UUID}, _billing())
    validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND.value)


# ==========================================================================
# Corner (entities): list clients pagination envelope
# ==========================================================================
def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_clients_pagination_envelope
    """
    set_clock("2026-05-01T00:00:00Z")
    create_client(state_code="CA")
    create_client(state_code="NY")
    items, meta = validate_paginated(api.list_clients(_clinical()))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta


# ==========================================================================
# Corner (rbac): Client cannot charge a cycle (BillingAdmin-exclusive)
# ==========================================================================
def test_client_cannot_charge_cycle(api):
    """PRD §2.1: "When a recognized, authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/client_cannot_charge_cycle_unauthorized
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    resp = api.charge_cycle(sub["id"], _client(client["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ==========================================================================
# Corner (rbac): Therapist cannot complete another therapist's session
# ==========================================================================
def test_therapist_cannot_complete_other_therapists_session(api):
    """PRD §2.1: "When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting
    `Therapist`; ownership checks on any resource that references a therapist compare the
    resource's match `therapist_id` to `X-User-ID`. When such an entity-backed role acts on a
    resource it does not own ... the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/therapist_cannot_complete_other_therapists_session_not_owner
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist_a = accepting_therapist(state_code="CA", full_name="T A3")
    therapist_b = accepting_therapist(state_code="CA", full_name="T B3")
    proposed = propose_match(client["id"], therapist_a["id"])
    match = accept_match(proposed["id"], client["id"])
    sub, cycle = subscription_with_paid_cycle(client["id"])
    ls = schedule_session(match["id"], client["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    set_clock("2026-06-02T10:30:00Z")
    resp = api.complete_live_session(ls["id"], _therapist(therapist_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ==========================================================================
# Corner (rbac): missing auth header -> unauthenticated
# ==========================================================================
def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    set_clock("2026-05-01T00:00:00Z")
    client = create_client(state_code="CA")
    resp = api.get_client(client["id"], build_user_headers("nobody", "Nobody"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
