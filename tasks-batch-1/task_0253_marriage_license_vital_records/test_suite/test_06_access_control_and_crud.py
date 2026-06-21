"""Access control (RBAC / auth), not-found handling, pagination, and the
append-only ledger row shape. Corner (queue B) instances."""
from test_helpers import (
    validate_error,
    validate_paginated,
    get_success_data,
    build_user_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_application_payload,
    create_two_applicants,
    create_under_review_application,
    make_applicant_headers,
    setup_issued_license,
    setup_submitted_return,
    CLERK_1,
)


# ===========================================================================
# Not found (queue B: entities)
# ===========================================================================
def test_get_applicant_nonexistent_returns_not_found(api):
    """PRD §2.4: "The first identifier that does not resolve to an existing resource
    causes the request to fail with ERR_NOT_FOUND before any later reference is
    examined."

    Design: Corner/entities/get_applicant_nonexistent_returns_not_found
    """
    resp = api.get_applicant(NON_EXISTENT_UUID, CLERK_1)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


# ===========================================================================
# Append-only ledger row shape (queue B: entities)
# ===========================================================================
def test_ledger_entry_has_no_version_field_and_records_license_charge(api):
    """PRD §2.4: "A FeeLedgerEntry therefore carries only an id and a created_at; it
    has neither an updated_at nor a version field."

    Design: Corner/entities/ledger_entry_immutable_no_version_field
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    ledger, _ = validate_paginated(api.list_application_ledger(base["application"]["id"], CLERK_1))
    assert len(ledger) == 1
    row = ledger[0]
    assert row["kind"] == "CHARGE"
    assert row["amount_cents"] == 9000
    assert row["source_entity"] == "LICENSE"
    assert "version" not in row, "FeeLedgerEntry must not carry a version field"
    assert "updated_at" not in row, "FeeLedgerEntry must not carry an updated_at field"


# ===========================================================================
# Pagination envelope (queue B: endpoints)
# ===========================================================================
def test_list_applications_pagination_envelope(api):
    """PRD §2.3: "List responses carry the pagination bookkeeping in the meta object
    of the envelope, exposing limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_applications_pagination_envelope
    """
    a, b = create_two_applicants()
    get_success_data(api.create_application(create_application_payload(a["id"], b["id"]), CLERK_1))
    get_success_data(api.create_application(create_application_payload(b["id"], a["id"]), CLERK_1))
    data, meta = validate_paginated(api.list_applications(CLERK_1, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# RBAC: exclusive-op denials (queue B: rbac)
# ===========================================================================
def test_applicant_cannot_decide_application(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_FORBIDDEN."

    Design: Corner/rbac/applicant_cannot_decide_application
    """
    a, b = create_two_applicants()
    app = create_under_review_application(a["id"], b["id"])
    resp = api.decide_application(app["id"], {"decision": "APPROVE"}, make_applicant_headers(a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    assert get_success_data(api.get_application(app["id"], CLERK_1))["status"] == "UNDER_REVIEW"


def test_clerk_cannot_accept_return(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_FORBIDDEN."

    Design: Corner/rbac/clerk_cannot_accept_return
    """
    base = setup_submitted_return()
    resp = api.accept_return(base["return"]["id"], build_user_headers("clerk-9", "Clerk"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    assert get_success_data(api.get_return(base["return"]["id"], CLERK_1))["status"] == "SUBMITTED"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.create_applicant(
        {"full_name": "No Auth", "date_of_birth": "1990-01-01"},
        build_user_headers("nobody-1", "Nobody"))  # unrecognized role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
