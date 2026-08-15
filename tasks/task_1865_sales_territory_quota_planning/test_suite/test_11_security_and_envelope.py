"""Auth pipeline, role exclusivity, ownership-scoped operations, segregation
of duties, and the standard response envelopes."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_assignment,
    create_change_request,
    create_plan,
    create_plan_year_payload,
    create_rep,
    create_territory_payload,
    is_valid_uuid,
    make_analyst_headers,
    make_manager_headers,
    make_sales_rep_headers,
    plan_version,
    setup_open_plan,
    setup_two_territory_communicated,
    submit,
    validate_error,
    get_change_request,
    get_submission,
)


def test_missing_auth_header_returns_400(api):
    """PRD: "A request in which either header is missing or malformed is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    The request is sent with both auth headers omitted.

    Design: Corner/validations/missing_auth_header_returns_400
    """
    validate_error(api.list_plan_years(headers={}),
                   ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


def test_response_envelope_success_and_error_shapes(api):
    """PRD: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources." and "The `api_request_id` is a
    server-generated unique identifier for the request that starts with
    `req_`."
    PRD: "All error API responses (4xx status codes) follow this standard
    envelope format:" with "The `error_id` is a unique, machine-readable
    string that identifies the specific error."

    Design: Corner/endpoints/response_envelope_success_and_error_shapes
    """
    resp = api.create_plan_year(create_plan_year_payload(label="FY27"), ADMIN)
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert is_valid_uuid(body["data"]["id"])

    err_resp = api.get_territory(NON_EXISTENT_UUID, ADMIN)
    err_body = err_resp.json()
    assert err_resp.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)
    assert len(err_body["data"]["message"]) > 0
    assert set(err_body["meta"].keys()) == {"api_request_id",
                                            "api_request_timestamp"}, \
        "error meta carries only api_request_id and api_request_timestamp"


def test_rep_cannot_create_territory_forbidden(api):
    """PRD: "Every endpoint declares which of these roles may call it (see §4);
    a caller whose role is not listed, or who fails an ownership check declared
    for the operation, is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: territory creation lists only SalesOpsAdmin — "| POST |
    `/sales-planning/territories` | Create a territory (status DRAFT) |
    SalesOpsAdmin |".

    Design: Corner/rbac/rep_cannot_create_territory_forbidden
    """
    plan = create_plan(label="FY27")
    rep = create_rep()
    validate_error(api.create_territory(
        create_territory_payload(plan["id"], name="T"),
        make_sales_rep_headers(rep["id"])),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


def test_manager_cannot_create_plan_year_forbidden(api):
    """PRD: "Every endpoint declares which of these roles may call it (see §4);
    a caller whose role is not listed, or who fails an ownership check declared
    for the operation, is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: plan-year creation lists only SalesOpsAdmin — "| POST |
    `/sales-planning/plan-years` | Create a plan year (status DRAFT, version
    1) | SalesOpsAdmin |".

    Design: Corner/rbac/manager_cannot_create_plan_year_forbidden
    """
    validate_error(api.create_plan_year(
        create_plan_year_payload(label="FY27"),
        make_manager_headers("mgr-1")),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


def test_analyst_cannot_resolve_dispute_forbidden(api):
    """PRD: "Tier two authorizes: the caller's role must be listed for the
    endpoint, and declared ownership checks — the withdrawing rep must own the
    submission, the withdrawing filer must own the dispute, the cancelling
    analyst must have created the change request — fail with
    `ERR_FORBIDDEN_FOR_ROLE`."
    PRD: "Every request is validated against an eight-tier pipeline, and the
    tiers are evaluated in strict order — a failure in an earlier tier masks
    everything behind it."

    The role gate (tier two) fires before the existence check (tier three), so
    an analyst resolving even a nonexistent dispute draws 403, not 404.

    Design: Corner/rbac/analyst_cannot_resolve_dispute_forbidden
    """
    validate_error(api.resolve_dispute(
        NON_EXISTENT_UUID, "UPHELD", make_analyst_headers("analyst-1")),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


def test_admin_cannot_file_dispute_forbidden(api):
    """PRD: "Every endpoint declares which of these roles may call it (see §4);
    a caller whose role is not listed, or who fails an ownership check declared
    for the operation, is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: dispute filing lists only SalesRep — "| POST |
    `/sales-planning/disputes` | Rep files an ownership dispute claiming the
    account for their territory (plan COMMUNICATED or LOCKED) | SalesRep |".

    The role gate at tier two precedes body existence checks, so the admin's
    request with nonexistent references still draws 403.

    Design: Corner/rbac/admin_cannot_file_dispute_forbidden
    """
    plan = create_plan(label="FY27")
    validate_error(api.create_dispute(
        {"plan_year_id": plan["id"], "account_id": NON_EXISTENT_UUID,
         "claimant_territory_id": NON_EXISTENT_UUID, "reason": "x"}, ADMIN),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


def test_rep_cannot_withdraw_others_submission_forbidden(api):
    """PRD: "The submitter, and only the submitter, may withdraw a live
    proposal while the plan remains `OPEN`, moving it from `SUBMITTED` to
    `WITHDRAWN`; anyone else is refused with `ERR_FORBIDDEN_FOR_ROLE`."

    Rep R2 holds the right role but the wrong X-User-ID for R1's submission.

    Design: Corner/rbac/rep_cannot_withdraw_others_submission_forbidden
    """
    base = setup_open_plan(label="FY27-WO")
    plan_id = base["plan"]["id"]
    r1 = create_rep(full_name="R1")
    r2 = create_rep(full_name="R2")
    create_assignment(plan_id, r1["id"], base["t"]["id"])
    sub = submit(plan_id, base["t"]["id"], 90000, r1["id"])

    validate_error(api.withdraw_submission(
        sub["id"], make_sales_rep_headers(r2["id"])),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    assert get_submission(sub["id"])["status"] == "SUBMITTED"


def test_self_approval_of_change_request_rejected(api):
    """PRD: "the approver's `X-User-ID` must differ from the request's
    `created_by_user_id`, a self-approval failing with
    `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)"

    Segregation of duties is keyed on the user id, not the role: an approver
    whose user id equals the creator's is rejected even though RevOpsManager
    is the correct role.

    Design: Corner/rbac/self_approval_of_change_request_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-SOD", owner_name="TF",
                                          claimant_name="TT")
    cr = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                               ns["tx"]["id"], ns["ty"]["id"], "2027-07-01",
                               creator="shared-user")
    pv = plan_version(ns["plan"]["id"])
    validate_error(api.approve_change_request(
        cr["id"], pv, make_manager_headers("shared-user")),
        ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN, 403)
    assert get_change_request(cr["id"])["status"] == "PENDING"


def test_change_cancel_by_non_creator_forbidden(api):
    """PRD: "The drafting analyst — and only the analyst who created it, anyone
    else drawing `ERR_FORBIDDEN_FOR_ROLE` — may cancel instead"

    Cancel is creator-scoped within the SalesOpsAnalyst role: a different
    analyst user id is rejected.

    Design: Corner/rbac/change_cancel_by_non_creator_forbidden
    """
    ns = setup_two_territory_communicated(label="FY27-CXO", owner_name="TF",
                                          claimant_name="TT")
    cr = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                               ns["tx"]["id"], ns["ty"]["id"], "2027-07-01",
                               creator="analyst-1")
    validate_error(api.cancel_change_request(
        cr["id"], make_analyst_headers("analyst-2")),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    assert get_change_request(cr["id"])["status"] == "PENDING"
