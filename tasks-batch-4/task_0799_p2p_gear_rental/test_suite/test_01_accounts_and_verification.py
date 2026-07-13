"""Accounts, identity verification, authentication and role gating."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_user_payload, create_verification_payload, create_listing_payload,
    assert_user, ApiErrorId, NON_EXISTENT_UUID,
    make_renter_headers, platform_headers as _platform_headers,
    register_user,
)


def test_register_user_defaults_trust_and_verification(api):
    """PRD §3.1: "A newly registered user starts with verification_status of
    UNVERIFIED, a trust_score of 300, a null avg_rating, and zeroed rating_count,
    late_return_count, upheld_claim_count, and total_earnings_cents."

    Design: Corner/entities/user_registration_returns_created_with_fields
    """
    resp = api.create_user(create_user_payload(email="u_create_defaults@x.com"))
    data = validate_success(resp, expected_status=201)
    assert_user(data)
    assert data["trust_score"] == 300, f"trust_score default must be 300, got {data['trust_score']}"
    assert data["verification_status"] == "UNVERIFIED"
    assert data["avg_rating"] is None
    assert data["rating_count"] == 0
    assert data["late_return_count"] == 0
    assert data["upheld_claim_count"] == 0
    assert data["total_earnings_cents"] == 0


def test_get_nonexistent_user_returns_not_found(api):
    """PRD §2.7: "Existence — every path- or body-referenced resource exists,
    validated left-to-right, else ERR_NOT_FOUND (404)."

    Design: Corner/entities/get_nonexistent_user_returns_not_found
    """
    resp = api.get_user(NON_EXISTENT_UUID, _platform_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_email_registration_rejected(api):
    """PRD §3.1: "The email must be unique across all users; a duplicate
    registration is rejected with ERR_DUPLICATE_EMAIL."

    Design: Corner/entities/duplicate_email_registration_rejected
    """
    api.create_user(create_user_payload(email="dup_reg@x.com", full_name="First"))
    resp = api.create_user(create_user_payload(email="dup_reg@x.com", full_name="Second"))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_decide_already_approved_verification_invalid(api):
    """PRD §3.1: "A decision may only be applied to a record that is still PENDING;
    otherwise the transition is rejected as an illegal state change."

    Design: Corner/state_machines/decide_already_approved_verification_invalid
    """
    renter = register_user(api, email="renter_idem@x.com")
    rid = renter["id"]
    ver = get_success_data(
        api.create_verification(rid, create_verification_payload(), make_renter_headers(rid))
    )
    api.decide_verification(ver["id"], {"decision": "APPROVE"}, _platform_headers())
    resp = api.decide_verification(
        ver["id"], {"decision": "REJECT", "reject_reason": "changed mind"}, _platform_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_unauthenticated_request_rejected(api, anonymous_headers):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    resp = api.list_bookings(anonymous_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_renter_cannot_create_listing_forbidden(api):
    """PRD §2.1: "When a caller is authenticated but not permitted to perform the
    requested operation — either because their role is not authorized for it, or
    because they are an ownership-scoped user acting on a resource they do not own —
    the request is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/renter_cannot_create_listing_forbidden
    """
    user = register_user(api, email="u_rbac_listing@x.com")
    resp = api.create_listing(create_listing_payload(user["id"]), make_renter_headers(user["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
