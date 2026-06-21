"""Job intake / CRUD, role-based access control, existence errors, and reverse-reachable
list reads.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_policy, create_customer, create_crew, create_truck, create_job,
    submit_estimate, accept_estimate, get_crew_version,
    create_haul_job_payload, create_job_item_payload, create_dispatch_payload,
    create_customer_payload,
    make_customer_headers,
    build_user_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
NONEXISTENT_UUID_2 = "00000000-0000-4000-8000-000000000001"


# ─── corner: entities (creation / validation / computed) ──

def test_create_haul_job_returns_draft_with_pinned_active_policy(api):
    """PRD §3.2: "The job is created in `DRAFT`, and its `pricing_policy_id` is set to the
    currently active policy".
    PRD §4: "Operations that create a new, stand-alone resource or append a new resource
    to a collection return a `201 Created` status code."

    Design: Corner/entities/create_hauljob_returns_201_with_draft_and_pinned_policy
    """
    policy = create_policy()
    cust = create_customer()
    resp = api.create_haul_job(
        create_haul_job_payload(cust["id"], service_type="SCHEDULED", address="1 A St"),
        make_customer_headers(cust["id"]),
    )
    job = validate_success(resp, expected_status=201)
    assert job["status"] == "DRAFT", f"status={job['status']}"
    assert job["pricing_policy_id"] == policy["id"], f"pinned={job['pricing_policy_id']}"


def test_create_haul_job_missing_service_type_returns_invalid_request(api):
    """PRD §2.7: "Request well-formedness, evaluated at the fourth tier, covers: required
    fields are present ... Any violation of these structural rules is `ERR_INVALID_REQUEST`."
    PRD §3.2: "A customer (or a dispatcher acting on their behalf) opens a job by
    supplying the `customer_id`, the `service_type`, and the pickup `address`."

    Design: Corner/entities/create_hauljob_missing_service_type_returns_invalid_request
    """
    create_policy()
    cust = create_customer()
    resp = api.create_haul_job(
        {"customer_id": cust["id"], "address": "2 A St"}, make_customer_headers(cust["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_haul_job_returns_not_found(api):
    """PRD §2.6: "a missing job yields `ERR_JOB_NOT_FOUND` before the estimate is ever
    looked up".

    Design: Corner/entities/get_hauljob_nonexistent_returns_not_found
    """
    create_policy()
    resp = api.get_haul_job(NONEXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_FOUND.value)


def test_create_haul_job_with_no_active_policy_returns_no_active_policy(api):
    """PRD §3.2: "its `pricing_policy_id` is set to the currently active policy; if no
    policy is `ACTIVE` at that moment, the creation is rejected with
    `ERR_NO_ACTIVE_POLICY`."

    No pricing policy is ever created, so none is ACTIVE.

    Design: Corner/entities/create_hauljob_with_no_active_policy_returns_no_active_policy
    """
    cust = validate_success(api.create_customer(create_customer_payload(), ADMIN), expected_status=201)
    resp = api.create_haul_job(
        create_haul_job_payload(cust["id"], service_type="SCHEDULED", address="3 A St"),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY.value)


def test_add_job_item_quantity_zero_returns_invalid_request(api):
    """PRD §2.7: "a `quantity` is at least 1 ... Any violation of these structural rules
    is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_jobitem_invalid_quantity_zero_returns_invalid_request
    """
    create_policy()
    cust = create_customer()
    job = create_job(cust["id"])
    resp = api.add_job_item(
        job["id"], create_job_item_payload(category="MATTRESS", quantity=0), make_customer_headers(cust["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_new_customer_outstanding_balance_starts_zero(api):
    """PRD §2.9: "A newly registered customer starts with an outstanding balance of 0."
    PRD §3.1: "the customer is created with `status` `ACTIVE`, and its
    `outstanding_balance_cents` starts at 0."

    Design: Corner/entities/computed_outstanding_balance_starts_zero
    """
    create_policy()
    resp = api.create_customer(create_customer_payload(), ADMIN)
    cust = validate_success(resp, expected_status=201)
    assert cust["outstanding_balance_cents"] == 0, f"balance={cust['outstanding_balance_cents']}"


# ─── corner: errors (existence ordering) ──────────────

def test_dispatch_nonexistent_crew_returns_crew_not_found(api):
    """PRD §2.6: "a dispatch create resolves its `crew_id`, `truck_id`, and the referenced
    job, each producing its own not-found error (`ERR_CREW_NOT_FOUND`,
    `ERR_TRUCK_NOT_FOUND`, `ERR_JOB_NOT_FOUND`)."

    Design: Corner/errors/dispatch_nonexistent_crew_returns_crew_not_found
    """
    create_policy()
    cust = create_customer()
    truck = create_truck()
    real_crew = create_crew()
    crew_v = get_crew_version(real_crew["id"])
    job = create_job(cust["id"])
    est = submit_estimate(job["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job["id"], est["id"], cust["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(job["id"], NONEXISTENT_UUID_2, truck["id"], crew_v), DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_FOUND.value)


def test_accept_nonexistent_estimate_returns_estimate_not_found(api):
    """PRD §2.6: "A job-scoped estimate path, for instance, validates the job identifier
    before the estimate identifier ... and only once the job is confirmed does a missing
    estimate yield `ERR_ESTIMATE_NOT_FOUND`."

    Design: Corner/errors/accept_estimate_with_no_submitted_returns_estimate_not_found
    """
    create_policy()
    cust = create_customer()
    job = create_job(cust["id"])  # exists, but no estimate with the supplied id
    resp = api.accept_photo_estimate(job["id"], NONEXISTENT_UUID_2, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_NOT_FOUND.value)


# ─── corner: rbac ─────────────────────────────────────

def test_customer_cannot_create_dispatch_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership-bound actor is acting on a resource
    it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /dispatches is authorized for Dispatcher only.

    Design: Corner/rbac/customer_cannot_create_dispatch_forbidden
    """
    create_policy()
    cust = create_customer()
    crew = create_crew()
    truck = create_truck()
    job = create_job(cust["id"])
    est = submit_estimate(job["id"], cust["id"], raw_fraction=0.10)
    accept_estimate(job["id"], est["id"], cust["id"])
    crew_v = get_crew_version(crew["id"])
    resp = api.create_dispatch(
        create_dispatch_payload(job["id"], crew["id"], truck["id"], crew_v),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_cannot_cancel_other_customers_job_forbidden(api):
    """PRD §2.1: "ownership checks on any resource that references a `Customer` compare the
    resource's customer foreign key (`customer_id`) to `X-User-ID`. A customer may only
    create, estimate, accept, revise, cancel, or dispute against jobs and invoices it
    owns."

    Customer B attempts to cancel customer A's job.

    Design: Corner/rbac/customer_cannot_cancel_other_customers_job_forbidden
    """
    create_policy()
    cust_a = create_customer()
    cust_b = create_customer()
    job = create_job(cust_a["id"])
    est = submit_estimate(job["id"], cust_a["id"], raw_fraction=0.10)
    accept_estimate(job["id"], est["id"], cust_a["id"])
    resp = api.cancel_haul_job(job["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_unknown_role_returns_missing_or_invalid_auth(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_AUTH`."

    A request with an unrecognized role header is rejected before any other check.

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    create_policy()
    cust = create_customer()
    ghost_headers = build_user_headers(cust["id"], "Ghost")
    resp = api.create_haul_job(
        create_haul_job_payload(cust["id"], service_type="SCHEDULED", address="23 A St"), ghost_headers
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_AUTH.value)


# ─── corner: endpoints (reverse-reachable list reads) ─

def test_list_job_items_returns_array_with_pagination(api):
    """PRD §3.10: "as can a crew's dispatches, a truck's dispatches, a job's items, photo
    estimates, diversion records, dump tickets, and invoices ... Each of these supports
    the standard `limit` and `offset` pagination."
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object
    of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_job_items_returns_array_with_pagination_fields
    """
    create_policy()
    cust = create_customer()
    job = create_job(cust["id"])
    validate_success(api.add_job_item(job["id"], create_job_item_payload("MATTRESS", quantity=1), make_customer_headers(cust["id"])), expected_status=201)
    validate_success(api.add_job_item(job["id"], create_job_item_payload("APPLIANCE", quantity=1), make_customer_headers(cust["id"])), expected_status=201)
    data, meta = validate_paginated(api.list_job_items(job["id"], DISPATCHER))
    assert meta["total_count"] == 2, f"total_count={meta['total_count']}"
    assert len(data) == 2, f"len={len(data)}"


def test_list_diversions_surfaces_recorded_record(api):
    """PRD §3.10: "as can a crew's dispatches, a truck's dispatches, a job's items, photo
    estimates, diversion records, dump tickets, and invoices".

    A diversion is recorded on an ON_SITE job and then surfaced through the job's diversion
    list (its only discovery channel).

    Design: Corner/endpoints/reverse_reachable_diversions_list_returns_created_records
    """
    from test_helpers import setup_on_site_job, record_diversion
    ctx = setup_on_site_job(raw_fraction=0.10)
    div = record_diversion(ctx["job"]["id"], ctx["crew"]["id"], destination="DONATION", tons=0.5)
    data, meta = validate_paginated(api.list_diversions(ctx["job"]["id"], DISPATCHER))
    assert len(data) == 1, f"len={len(data)}"
    assert any(d["id"] == div["id"] for d in data), "recorded diversion must appear in the list"
