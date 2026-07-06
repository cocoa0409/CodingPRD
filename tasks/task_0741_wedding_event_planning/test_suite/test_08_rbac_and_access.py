"""Role authorization, ownership on entity-backed roles, and header authentication.

All queue B rbac corners.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_event_payload,
    create_event,
    make_client_headers,
    setup_sent_contract_event,
    setup_signed_contract_event,
)


def test_vendor_cannot_create_event_unauthorized(api, vendor_headers):
    """PRD §2.1: "When a well-identified principal attempts an operation their role is
    not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Creating an event is Planner-only; a Vendor is rejected.

    Design: Corner/rbac/vendor_cannot_create_event_returns_unauthorized
    """
    validate_error(
        api.create_event(create_event_payload(total_budget_cents=5_000_000), vendor_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_client_cannot_countersign_unauthorized(api):
    """PRD §3.1: "A `SIGNED` contract is countersigned by the `Planner`, moving
    `SIGNED → COUNTERSIGNED`; this requires the contract to be `SIGNED`, otherwise
    `ERR_CONTRACT_NOT_SIGNED`."
    PRD §2.1: "When a well-identified principal attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`."

    The acting Client owns the event (so ownership would pass), but countersign is
    Planner-only — the role-authorization gate rejects it first.

    Design: Corner/rbac/client_cannot_countersign_returns_unauthorized
    """
    event, contract = setup_signed_contract_event(total_budget_cents=5_000_000)
    validate_error(
        api.countersign_contract(contract["id"], make_client_headers(event["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_client_signs_foreign_event_contract_ownership_violation(api):
    """PRD §2.1: "Whenever an entity-backed principal (`Client` or `Vendor`) acts on a
    resource whose owning identifier does not equal their `X-User-ID`, the request is
    rejected with `ERR_OWNERSHIP_VIOLATION`."

    The Client is authorized to sign, but its X-User-ID is event2 while the SENT contract
    belongs to event1.

    Design: Corner/rbac/client_signs_foreign_event_contract_returns_ownership_violation
    """
    _event1, contract1 = setup_sent_contract_event(total_budget_cents=5_000_000)
    event2 = create_event(total_budget_cents=5_000_000)
    validate_error(
        api.sign_contract(contract1["id"], make_client_headers(event2["id"])),
        ApiErrorId.ERR_OWNERSHIP_VIOLATION.value,
    )


def test_missing_headers_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one of
    the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_HEADERS`."

    Design: Corner/rbac/auth_missing_user_role_header_returns_400
    """
    validate_error(api.list_events(headers={}), ApiErrorId.ERR_MISSING_OR_INVALID_HEADERS.value)
