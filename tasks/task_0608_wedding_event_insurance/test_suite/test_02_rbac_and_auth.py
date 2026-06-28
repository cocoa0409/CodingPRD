"""RBAC and authentication claims (queue B `rbac` section)."""
from test_helpers import (
    validate_success, validate_error, make_policyholder_headers, TEST_USERS,
)
from test_helpers import fixtures as FX

_uw = TEST_USERS["underwriter_headers"]


def test_policyholder_cannot_bind_policy(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 endpoint table: bind is authorized for UnderwritingAgent only.

    Design: Corner/rbac/policyholder_cannot_bind_policy
    """
    ctx = FX.setup_quoted_single_event()
    res = api.bind_policy(ctx["policy"]["id"], make_policyholder_headers("ph-1"))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", 403)
    policy = validate_success(api.get_policy(ctx["policy"]["id"], _uw), 200)
    assert policy["lifecycle_status"] == "QUOTED"


def test_underwriting_agent_cannot_approve_claim(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 endpoint table: claim approve is authorized for ClaimsAdjuster only.

    Design: Corner/rbac/underwriting_agent_cannot_approve_claim
    """
    ctx, claim = FX.setup_submitted_claim()
    res = api.approve_claim(ctx["policy"]["id"], claim["id"], _uw)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", 403)
    refreshed = validate_success(api.get_claim(ctx["policy"]["id"], claim["id"], _uw), 200)
    assert refreshed["status"] == "SUBMITTED"


def test_cancel_by_non_owner_policyholder_rejected(api):
    """PRD §2.1: "This ownership check guards paying the premium, cancelling the policy,
    resubmitting a claim, and attaching documents to a claim."
    PRD §2.1: "When a policyholder acts on a policy they do not own, the request is
    rejected with `ERR_NOT_POLICY_OWNER`."

    Design: Corner/rbac/cancel_by_non_owner_policyholder_rejected
    """
    ctx = FX.setup_in_force_policy_canc_only()
    pid = ctx["policy"]["id"]
    res = api.cancel_policy(pid, make_policyholder_headers("ph-999"))
    validate_error(res, "ERR_NOT_POLICY_OWNER", 403)
    policy = validate_success(api.get_policy(pid, TEST_USERS["admin_headers"]), 200)
    assert policy["lifecycle_status"] == "IN_FORCE"


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    res = api.create_policy({"policy_form": "SINGLE_EVENT"}, {})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", 401)
