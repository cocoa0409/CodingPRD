"""Supplier–ingredient pairing decisions, segregation of duties, and pairing
RBAC (PRD §2.10, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_pairing,
    create_ingredient,
    create_pairing,
    create_supplier,
    make_qa_approver_headers,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)


def test_sia_rejected_pairing_is_terminal_and_stamped(api):
    """PRD §3.2: "Every decision stamps the pairing's `decided_by` with the acting
    `X-User-ID` and `decided_at` with the decision timestamp."
    PRD §3.2: "Both `REJECTED` and `REVOKED` are terminal for a pairing."
    PRD §2.10: "a resource already in a terminal state accepts no further
    transitions at all and rejects them with `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/sia_rejected_pairing_is_terminal_and_stamped
    """
    supplier = create_supplier(approve=True)
    ingredient = create_ingredient()
    pairing = create_pairing(supplier["id"], ingredient["id"], requester_user_id="qa-requester-01")

    approver = make_qa_approver_headers("qa-approver-01")
    rejected = validate_success(api.reject_pairing(pairing["id"], approver))
    assert_pairing(rejected)
    assert rejected["approval_state"] == "REJECTED"
    assert rejected["decided_by"] == "qa-approver-01"
    assert is_iso8601_timestamp(rejected["decided_at"])

    resp = api.approve_pairing(pairing["id"], approver)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value)


def test_sia_revoke_from_pending_review_fails(api, qa_approver_headers):
    """PRD §3.2: "A `QAApprover` may revoke a pairing currently in `APPROVED`,
    moving it to `REVOKED`"
    PRD §2.10: "Fourth, transition validity: the requested action must correspond
    to a transition that exists from the resource's current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/sia_revoke_from_pending_review_fails
    """
    supplier = create_supplier()
    ingredient = create_ingredient()
    pairing = create_pairing(supplier["id"], ingredient["id"])
    assert pairing["approval_state"] == "PENDING_REVIEW"

    resp = api.revoke_pairing(pairing["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pairing_approve_blocked_until_supplier_approved(api):
    """PRD §3.2: "Approval additionally requires that the supplier itself
    currently sits in `APPROVED` — otherwise `ERR_SUPPLIER_NOT_APPROVED`
    (HTTP 422)"
    PRD §3.2: "Approval moves the pairing to `APPROVED` and recomputes the
    supplier's `approved_ingredient_count`"

    Design: Corner/validations/pairing_approve_blocked_until_supplier_approved
    """
    supplier = create_supplier()  # PROVISIONAL
    ingredient = create_ingredient()
    pairing = create_pairing(
        supplier["id"], ingredient["id"], requester_user_id="qa-requester-11"
    )

    approver = make_qa_approver_headers("qa-approver-11")
    blocked = api.approve_pairing(pairing["id"], approver)
    validate_error(blocked, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED.value)

    validate_success(api.approve_supplier(supplier["id"], make_qa_approver_headers("qa-admin-11")))
    approved = validate_success(api.approve_pairing(pairing["id"], approver))
    assert approved["approval_state"] == "APPROVED"


def test_rbac_denied_quality_analyst_approve_pairing(api, quality_analyst_headers):
    """PRD §2.1: "A request whose role is valid but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: the pairing-approval endpoint is authorized for `QAApprover`.

    Design: Corner/rbac/rbac_denied_quality_analyst_approve_pairing
    """
    supplier = create_supplier(approve=True)
    ingredient = create_ingredient()
    pairing = create_pairing(supplier["id"], ingredient["id"])

    resp = api.approve_pairing(pairing["id"], quality_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    current = validate_success(api.get_pairing(pairing["id"], quality_analyst_headers))
    assert current["approval_state"] == "PENDING_REVIEW"


def test_sod_same_user_decide_own_pairing_blocked(api):
    """PRD §3.2: "On both approval and rejection, the deciding user must not be
    the user who submitted the pairing request; a violation is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403), and this check is evaluated before any other
    business rule on the decision."

    Design: Corner/rbac/sod_same_user_decide_own_pairing_blocked
    """
    supplier = create_supplier(approve=True)
    ingredient = create_ingredient()
    pairing = create_pairing(
        supplier["id"], ingredient["id"], requester_user_id="qa-requester-99"
    )

    same_user = api.approve_pairing(pairing["id"], make_qa_approver_headers("qa-requester-99"))
    validate_error(same_user, ApiErrorId.ERR_SOD_VIOLATION.value)

    approved = validate_success(
        api.approve_pairing(pairing["id"], make_qa_approver_headers("qa-approver-99"))
    )
    assert approved["approval_state"] == "APPROVED"
    assert approved["decided_by"] == "qa-approver-99"
