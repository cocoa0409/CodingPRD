"""Commission-cancel cascade, budget release, RBAC, and list pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId,
    make_certify_payload,
    make_artist_headers,
    create_project, create_certified_project, create_commission, create_artist,
    setup_open_call_with_submission,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_cancel_commission_cascades_to_call_and_submission(api):
    """PRD §3.2: "Cancellation also cascades to the solicitation: the linked artist
    call, if it is in `OPEN` or `CLOSED`, transitions to `CANCELLED`, and in turn
    every non-terminal submission on that call — those in `SUBMITTED`,
    `REVISION_REQUESTED`, or `SCORED` — transitions to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/commission_cancel_call_submission_withdraw_cascade
    """
    ctx = setup_open_call_with_submission(api, allocation_cents=500000)
    commission = validate_success(api.cancel_commission(ctx["commission"]["id"], ADMIN), 200)
    assert commission["status"] == "CANCELLED"
    call = get_success_data(api.get_call(ctx["call"]["id"], ADMIN))
    assert call["status"] == "CANCELLED"
    submission = get_success_data(api.get_submission(ctx["submission"]["id"], ADMIN))
    assert submission["status"] == "WITHDRAWN"


def test_cancel_commission_releases_budget(api):
    """PRD §3.2: "Cancellation releases the budget: the commission is dropped from
    the committed sum, so the project's `committed_cents` decreases by
    `allocation_cents` and `uncommitted_cents` increases by the same amount,
    restoring the budget invariant."

    Design: Difficulty/transitive_cascade/commission_cancel_call_submission_withdraw_cascade
    """
    ctx = setup_open_call_with_submission(api, allocation_cents=500000)
    validate_success(api.cancel_commission(ctx["commission"]["id"], ADMIN), 200)
    project = get_success_data(api.get_project(ctx["project"]["id"], ADMIN))
    assert project["committed_cents"] == 0
    assert project["uncommitted_cents"] == 2000000


def test_artist_cannot_certify_project(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/artist_cannot_certify_project_unauthorized
    """
    project = create_project(api, name="Rbacpark")
    artist = create_artist(api, display_name="Qi Vale", email="qi@x.com")
    resp = api.certify_project(
        project["id"], make_certify_payload(190000000), make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.create_site({"name": "NoAuth", "address": "1 Void"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_list_commissions_reports_pagination_fields(api):
    """PRD §2.3: "The pagination fields `limit`, `offset`, `total_count`, and
    `has_more` are reported in the `meta` object of list responses, where
    `total_count` is the count of all records matching the query before pagination
    and `has_more` is true whenever more records exist beyond the current page."

    Design: Corner/endpoints/list_commissions_pagination_fields
    """
    project = create_certified_project(api, construction_budget_cents=200000000,
                                       certified_construction_budget_cents=200000000)
    create_commission(api, project["id"], allocation_cents=500000, title="C1")
    create_commission(api, project["id"], allocation_cents=500000, title="C2")
    data, meta = validate_paginated(
        api.list_commissions(ADMIN, params={"project_id": project["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
