"""Resource creation defaults and validation, not-found handling, role/ownership access control,
and a reverse-reachability list endpoint.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    assert_client,
    register_client, create_stylist, create_active_engagement, schedule_session,
    setup_confirmed_session,
    register_client_payload, create_stylist_payload, complete_session_payload,
    make_anonymous_headers, make_admin_headers, make_client_headers, make_stylist_headers,
)


# ─────────────── Corner: entities ───────────────
def test_register_client_returns_201_with_defaults(api):
    """PRD §3.1: "Registration creates a Client in ACTIVE status with wallet_credit_cents starting
    at 0 and has_paid_invoice starting false."

    Design: Corner/entities/client_register_returns_201_with_defaults
    """
    data = validate_success(api.register_client(
        register_client_payload(full_name="New Client", email="new_c1@x.com"),
        make_anonymous_headers()), 201)
    assert_client(data)
    assert data["wallet_credit_cents"] == 0
    assert data["has_paid_invoice"] is False
    assert data["status"] == "ACTIVE"


def test_get_nonexistent_client_returns_404(api):
    """PRD §2.9: "The not-found codes are ERR_CLIENT_NOT_FOUND ... each returning HTTP 404."

    Design: Corner/entities/get_client_nonexistent_returns_404
    """
    resp = api.get_client(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


def test_register_without_email_returns_422(api):
    """PRD §3.1: "A prospective client joins by self-registering with a full_name and an email;
    the email must be unique across clients."

    Design: Corner/entities/register_missing_email_returns_422
    """
    resp = api.register_client({"full_name": "No Email"}, make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_register_ignores_supplied_wallet_credit(api):
    """PRD §3.1: "Registration creates a Client in ACTIVE status with wallet_credit_cents starting
    at 0 and has_paid_invoice starting false."

    Design: Corner/entities/register_wallet_input_ignored
    """
    data = validate_success(api.register_client(
        {"full_name": "Sneaky", "email": "sneaky1@x.com", "wallet_credit_cents": 99999},
        make_anonymous_headers()), 201)
    assert data["wallet_credit_cents"] == 0, "wallet is server-controlled and starts at 0"


def test_create_stylist_with_bad_tier_returns_422(api):
    """PRD §3.1: "a seniority tier of JUNIOR, SENIOR, or LEAD (informational only; it does not
    affect pricing)."

    Design: Corner/entities/stylist_create_bad_tier_returns_422
    """
    resp = api.create_stylist(
        create_stylist_payload(full_name="Bad Tier", email="bt1@x.com", commission_pct=0.3,
                               tier="PLATINUM"),
        make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ─────────────── Corner: validations / RBAC ───────────────
def test_client_cannot_create_stylist(api):
    """PRD §2.1: "A request whose role is not permitted for the target operation is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/client_cannot_create_stylist
    """
    cl = register_client(api)
    resp = api.create_stylist(
        create_stylist_payload(full_name="Nope", email="nope_c@x.com", commission_pct=0.3,
                               tier="SENIOR"),
        make_client_headers(cl["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_cannot_cancel_another_clients_engagement(api):
    """PRD §2.1: "A Client may act only on engagements it owns (the engagement's client_id equals
    X-User-ID) ... An entity_backed principal ... that attempts to act on a resource it does not
    own is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/client_cannot_cancel_others_engagement
    """
    sty = create_stylist(api)
    owner = register_client(api)
    other = register_client(api)
    eng = create_active_engagement(api, owner["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    resp = api.cancel_engagement(eng["id"], make_client_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_stylist_cannot_complete_another_stylists_session(api):
    """PRD §2.1: "A Stylist may act only on sessions, purchase items, and lookbooks belonging to
    engagements whose stylist_id equals X-User-ID."

    Design: Corner/validations/stylist_cannot_complete_others_session
    """
    ctx = setup_confirmed_session(api)
    other_stylist = create_stylist(api)
    resp = api.complete_session(ctx["session"]["id"], complete_session_payload(90),
                                make_stylist_headers(other_stylist["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ─────────────── Corner: endpoints ───────────────
def test_list_sessions_of_engagement_returns_array(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and has_more inside the
    meta object of the envelope."

    Design: Corner/endpoints/list_sessions_of_engagement_returns_array
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    schedule_session(api, eng["id"], cl["id"], eng["version"], session_type="VIRTUAL",
                     modality="VIRTUAL", scheduled_start="2026-04-22T10:00:00Z",
                     scheduled_end="2026-04-22T11:00:00Z")
    sessions, meta = validate_paginated(api.list_sessions(eng["id"], make_client_headers(cl["id"])))
    assert len(sessions) == 1, f"exactly one scheduled session, got {len(sessions)}"
    assert meta["total_count"] == 1
