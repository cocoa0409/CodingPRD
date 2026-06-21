"""RBAC (authentication, role authorization) and list/retrieval endpoint
behavior (pagination envelope, both job dimensions, quote-line subresource).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    # fixtures
    create_customer,
    create_technician,
    create_sent_quote,
    accept_quote_get_job,
    schedule_job,
    create_quote,
    add_line,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Corner / rbac / missing_headers_returns_unauthenticated
# ===========================================================================
def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_customer(
        {"full_name": "No Auth", "email": "noauth-1@example.com", "service_address": "25 Main"},
        {},  # no X-User-ID / X-User-Role headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ===========================================================================
# Corner / rbac / dispatcher_cannot_complete_job_forbidden
# ===========================================================================
def test_dispatcher_cannot_complete_job_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 (`/jobs/{id}/complete`): authorized role Technician.

    Design: Corner/rbac/dispatcher_cannot_complete_job_forbidden
    """
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED")
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    job = schedule_job(job["id"], technician["id"])
    tech_h = make_technician_headers(technician["id"])
    get_success_data(api.depart_job(job["id"], tech_h))
    get_success_data(api.arrive_job(job["id"], tech_h))
    # Complete attempted as Dispatcher (a Technician-only op).
    resp = api.complete_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ===========================================================================
# Corner / rbac / servicemanager_cannot_accept_quote_forbidden
# ===========================================================================
def test_service_manager_cannot_accept_quote_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 (`/quotes/{id}/accept`): authorized role Customer.

    Design: Corner/rbac/servicemanager_cannot_accept_quote_forbidden
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    # Accept attempted as ServiceManager (a Customer-only op).
    resp = api.accept_quote(quote["id"], SM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ===========================================================================
# Corner / endpoints / list_quotes_pagination_envelope
# ===========================================================================
def test_list_quotes_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries the pagination
    bookkeeping fields `limit`, `offset`, `total_count` (the number of records
    matching the query before the page window is applied), and `has_more` (true
    when records remain beyond the current window)."

    Design: Corner/endpoints/list_quotes_pagination_envelope
    """
    customer = create_customer()
    create_quote(customer["id"], quote_type="SERVICE_CALL", service_call_fee_cents=5000)
    create_quote(customer["id"], quote_type="SERVICE_CALL", service_call_fee_cents=5000)
    resp = api.list_quotes(SM, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"Expected has_more True with limit 1 of 2, got {meta['has_more']}"
    assert len(data) == 1, f"Expected one item in the page window, got {len(data)}"


# ===========================================================================
# Corner / endpoints / get_job_returns_both_dimensions
# ===========================================================================
def test_get_job_returns_both_status_dimensions(api):
    """PRD §3.5: "It carries two independent status dimensions, the
    `dispatch_status` and the `billing_status`, each advancing on its own. The
    dispatch dimension begins at `UNSCHEDULED`."
    PRD §3.8: "The billing dimension of a job runs in parallel with the dispatch
    dimension and begins at `PENDING`."

    Design: Corner/endpoints/get_job_returns_both_dimensions
    """
    customer = create_customer()
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    fetched = get_success_data(api.get_job(job["id"], SM))
    assert fetched["dispatch_status"] == "UNSCHEDULED", (
        f"Expected dispatch_status UNSCHEDULED, got {fetched['dispatch_status']}"
    )
    assert fetched["billing_status"] == "PENDING", (
        f"Expected billing_status PENDING, got {fetched['billing_status']}"
    )


# ===========================================================================
# Corner / endpoints / quote_lines_subresource_reverse_reachability
# ===========================================================================
def test_quote_lines_subresource_lists_created_line(api):
    """PRD §3.13: "Quote lines are listed under their owning quote."
    PRD §4 (`GET /quotes/{id}/lines`): List a quote's lines.

    Design: Corner/endpoints/quote_lines_subresource_reverse_reachability
    """
    customer = create_customer()
    quote = create_quote(customer["id"], quote_type="SERVICE_CALL", service_call_fee_cents=5000)
    line = add_line(quote["id"], "LABOR", qty=45)
    data, _meta = validate_paginated(api.list_quote_lines(quote["id"], SM))
    line_ids = [row["id"] for row in data]
    assert line["id"] in line_ids, (
        f"Expected created QuoteLine {line['id']} in the listing, got {line_ids}"
    )
