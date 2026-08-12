"""Authentication and authorization ordering (PRD §2.1, §2.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_case_payload,
    create_customer,
    create_staff,
    create_transaction_payload,
    validate_error,
)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    staff = create_staff()
    customer = create_customer(staff)
    res = api.create_case(create_case_payload(customer["id"]), None)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
    assert res.status_code == 401


def test_unknown_entity_backed_identity_returns_401(api):
    """PRD §2.1: "When `X-User-Role` is `BSAAnalyst`, `QAReviewer`, or
    `BSAManager`, `X-User-ID` is the `id` of an existing `Analyst` record;
    ownership checks compare resource foreign-key fields (for example
    `assigned_analyst_id`, `drafted_by_analyst_id`, `proposed_by_analyst_id`,
    `reviewer_id`) against `X-User-ID`, and a role-without-analyst reference is
    rejected with `ERR_UNAUTHENTICATED`."

    No Analyst rows exist, so the entity-backed id cannot resolve.

    Design: Corner/rbac/unknown_entity_backed_identity_returns_401
    """
    staff = create_staff()
    customer = create_customer(staff)
    ghost = build_user_headers(NON_EXISTENT_UUID, "BSAAnalyst")
    res = api.create_case(create_case_payload(customer["id"]), ghost)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
    assert res.status_code == 401


def test_forbidden_role_checked_before_existence(api):
    """PRD §2.10: "Priority order, from highest to lowest, is:
    malformed-request checks (missing fields, bad enums, non-positive amounts,
    incoherent date windows, a QA review lacking exactly one target, or a
    duplicate active QA sample on the same target — all `ERR_INVALID_REQUEST`);
    then authentication (`ERR_UNAUTHENTICATED`); then role authorization
    (`ERR_FORBIDDEN_ROLE`); then segregation-of-duties
    (`ERR_SEGREGATION_OF_DUTIES`); then existence of every referenced id
    (`ERR_NOT_FOUND`); then state-machine legality (`ERR_INVALID_STATE`)".
    PRD §4: POST /accounts/{id}/transactions is authorized for
    `ComplianceAdmin` only.

    A BSAAnalyst posting to a non-existent account learns only that the role
    is forbidden — never whether the id exists.

    Design: Corner/validations/forbidden_role_beats_not_found
    """
    staff = create_staff()
    res = api.post_transaction(
        NON_EXISTENT_UUID, create_transaction_payload(), staff.analyst)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert res.status_code == 403
