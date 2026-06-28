"""Authentication, role authorization, and validation ordering at the auth tier.

Translates Corner queue (B) instances from `validations` (auth) and `rbac`, plus
the Difficulty queue (A) priority-pair instance whose winning error is an auth
error (finalize_audit_forbidden_role_beats_not_found).
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    make_pool_admin_headers,
    make_pool_operator_headers,
    make_participant_headers,
)
import test_helpers as H

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing or malforming either header is rejected with
    ERR_MISSING_AUTH."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    resp = api.get_account(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value, expected_status=401)


def test_participant_cannot_create_account(api):
    """PRD §2.1: "When a well-authenticated caller attempts an operation their
    role is not permitted to perform, the request is rejected with
    ERR_FORBIDDEN_FOR_ROLE." PRD §2.1: "a Participant ... may not mint assets, run
    audits, request collections, open repairs, or bill."

    Design: Corner/rbac/participant_cannot_create_account
    """
    H.create_policy()
    account = H.create_account()
    resp = api.create_account(
        {"legal_name": "Sneaky", "role_type": "RETAILER", "credit_limit_cents": 9},
        make_participant_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)


def test_pool_operator_cannot_void_invoice(api):
    """PRD §2.1: "A PoolOperator is pooling-operator staff ... but cannot void,
    suspend, close, cancel, or set the clock." PRD §3.9: "A draft invoice may
    instead be voided by a PoolAdmin, moving status to VOID".

    Design: Corner/rbac/pool_operator_cannot_void_invoice
    """
    H.create_policy()
    account = H.create_account(role_type="RETAILER")
    inv = H.create_invoice(account["id"])
    resp = api.void_invoice(inv["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)


def test_finalize_audit_forbidden_role_beats_not_found(api):
    """PRD §2.10: "Authentication of the headers comes first (ERR_MISSING_AUTH),
    then role authorization (ERR_FORBIDDEN_FOR_ROLE), then existence of every
    referenced resource validated left-to-right through the path and then the body
    foreign keys (ERR_NOT_FOUND)". PRD §3.6: "Finalizing an audit advances it
    DRAFT to FINALIZED and is performed by a PoolAdmin or PoolOperator."

    Design: Difficulty/priority_pair_validation_conflict/finalize_audit_forbidden_role_beats_not_found
    """
    H.create_policy()
    account = H.create_account()
    # Participant is not permitted to finalize audits; the audit id does not exist.
    resp = api.finalize_audit(
        NON_EXISTENT_UUID, make_participant_headers(account["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)


def test_finalize_audit_forbidden_role_beats_not_found_distinct_missing_id(api):
    """PRD §2.10: "then role authorization (ERR_FORBIDDEN_FOR_ROLE), then
    existence of every referenced resource validated left-to-right through the
    path and then the body foreign keys (ERR_NOT_FOUND)." PRD §2.1: "a Participant
    ... may not ... run audits".

    Design: Difficulty/priority_pair_validation_conflict/finalize_audit_forbidden_role_beats_not_found
    """
    H.create_policy()
    account = H.create_account()
    # A second non-existent id confirms auth precedence is not id-specific.
    resp = api.finalize_audit(
        "11111111-1111-4111-8111-111111111111",
        make_participant_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)
