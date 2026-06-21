"""Body validation, cross-entity validation, RBAC, listing/pagination, and redeploy linkage.

Translates the Corner/validations, Corner/rbac, and Corner/endpoints sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, build_user_headers,
    setup_active_placement,
    create_skill, create_client, create_open_job_order, create_candidate,
    create_timesheet, submit_timesheet, create_draft_invoice,
    drive_submission_to_offer_extended, create_placement, start_placement, end_placement,
    make_account_manager_headers, make_recruiter_headers,
    make_client_headers, make_candidate_headers,
)

AM = make_account_manager_headers()
RECRUITER = make_recruiter_headers()


# --- validations -------------------------------------------------------------

def test_timesheet_invalid_week_interval_returns_422(api):
    """PRD 2.6: "a timesheet's `week_end` must be strictly after its `week_start` ... Any of these
    produces `ERR_VALIDATION`."

    Design: Corner/validations/timesheet_invalid_week_interval_returns_422
    """
    scen = setup_active_placement()
    cand_headers = make_candidate_headers(scen["candidate"]["id"])
    resp = api.create_timesheet(
        {"placement_id": scen["placement"]["id"], "week_start": "2026-06-22T00:00:00Z",
         "week_end": "2026-06-15T00:00:00Z", "hours": 40}, cand_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_line_item_referencing_unapproved_timesheet_returns_not_approved(api):
    """PRD 3.8: "A line item is added by supplying the `timesheet_id`; the referenced timesheet
    must be in `status` `APPROVED` (otherwise `ERR_TIMESHEET_NOT_APPROVED`)."

    A SUBMITTED (not APPROVED) timesheet cannot be billed by a line item.

    Design: Corner/validations/line_item_unapproved_timesheet_returns_not_approved
    """
    scen = setup_active_placement()
    pl, cand, cl = scen["placement"], scen["candidate"], scen["client"]
    ts = create_timesheet(pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    submit_timesheet(ts["id"], cand["id"])  # SUBMITTED, not APPROVED
    inv = create_draft_invoice(cl["id"])
    resp = api.add_invoice_line_item(inv["id"], {"timesheet_id": ts["id"]}, AM)
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_NOT_APPROVED)


# --- rbac --------------------------------------------------------------------

def test_candidate_cannot_create_job_order(api):
    """PRD 2.1: "When an authenticated caller attempts an operation their role is not permitted to
    perform ... the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 4 (endpoint table): `POST /staffing/job-orders` is authorized for AccountManager only.

    Design: Corner/rbac/candidate_cannot_create_job_order
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    cand = create_candidate(full_name="Cara Dev", skill_codes=["JAVA"])
    resp = api.create_job_order(
        {"client_id": cl["id"], "title": "Dev", "employment_type": "TEMP",
         "required_skill_code": "JAVA", "openings": 1, "bill_rate_cents": 12000,
         "target_pay_rate_cents": 8000}, make_candidate_headers(cand["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_recruiter_cannot_approve_timesheet(api):
    """PRD 2.1: "When an authenticated caller attempts an operation their role is not permitted to
    perform ... the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 3.6: "A `Client` then either approves or rejects a `SUBMITTED` timesheet."

    Design: Corner/rbac/recruiter_cannot_approve_timesheet
    """
    scen = setup_active_placement()
    pl, cand = scen["placement"], scen["candidate"]
    ts = create_timesheet(pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    submit_timesheet(ts["id"], cand["id"])
    resp = api.patch_timesheet(ts["id"], {"target_status": "APPROVED"}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unrecognized_role_returns_missing_user_context(api):
    """PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the recognized role
    names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_header_returns_401
    """
    stranger = build_user_headers("nobody-1", "Stranger")
    resp = api.create_client({"name": "Acme", "credit_limit_cents": 5000000}, stranger)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


# --- endpoints: listing / pagination / redeploy ------------------------------

def test_job_order_list_returns_paginated_array_envelope(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."
    PRD 2.3: "The `meta` object of a list response carries the `limit`, `offset`, `total_count`,
    and `has_more` fields, where `total_count` is the number of matching items before pagination
    and `has_more` indicates whether further items remain beyond the current page."

    One client with one job order: total_count == 1, has_more == false.

    Design: Corner/endpoints/list_pagination_envelope_fields
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    get_success_data(api.create_job_order(
        {"client_id": cl["id"], "title": "Dev", "employment_type": "TEMP",
         "required_skill_code": "JAVA", "openings": 1, "bill_rate_cents": 12000,
         "target_pay_rate_cents": 8000}, AM))
    resp = api.list_job_orders(AM, params={"client_id": cl["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"total_count {meta['total_count']}"
    assert meta["has_more"] is False, f"has_more {meta['has_more']}"


def test_redeploy_placement_links_predecessor_and_is_listable(api):
    """PRD 3.4: "The `predecessor_placement_id` is set only when this placement is a redeployment
    of an earlier ended placement, and it references that prior placement."
    PRD 4 (endpoint table): `GET /staffing/placements` filters by predecessor_placement_id.

    A candidate placed and started on order A, then ended, is redeployed onto order B carrying
    predecessor_placement_id = plA. Listing placements filtered by that predecessor returns exactly
    the redeployed placement.

    Design: Corner/endpoints/list_placements_filtered_by_predecessor_redeploy
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    cand = create_candidate(full_name="Redeploy Dev", skill_codes=["JAVA"])
    jo_a, jo_a_v = create_open_job_order(cl["id"], title="Dev A", openings=1)
    sub_a, _ = drive_submission_to_offer_extended(jo_a, cand, cl)
    pl_a = create_placement(sub_a["id"], jo_a_v, start_date="2026-06-15T00:00:00Z",
                            end_date="2026-09-15T00:00:00Z", standard_weekly_hours=40)
    start_placement(pl_a["id"])
    end_placement(pl_a["id"])

    jo_b, jo_b_v = create_open_job_order(cl["id"], title="Dev B", openings=1)
    sub_b, _ = drive_submission_to_offer_extended(
        jo_b, cand, cl)
    pl_b = get_success_data(api.create_placement(
        {"submission_id": sub_b["id"], "start_date": "2026-09-16T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_b_v,
         "standard_weekly_hours": 40, "predecessor_placement_id": pl_a["id"]}, RECRUITER))
    assert pl_b["predecessor_placement_id"] == pl_a["id"], (
        f"predecessor_placement_id {pl_b['predecessor_placement_id']!r} should be {pl_a['id']!r}"
    )
    resp = api.list_placements(RECRUITER, params={"predecessor_placement_id": pl_a["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"total_count {meta['total_count']}"
    assert len(data) == 1 and data[0]["id"] == pl_b["id"], (
        f"expected exactly the redeployed placement {pl_b['id']!r}, got {[d['id'] for d in data]}"
    )
