"""Entity creation / validation / listing, job state-precondition enforcement,
exhibit duplicate-label and confidential filtering, and the RBAC peer-role
boundaries.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_case,
    make_attorney,
    make_case,
    make_reporter,
    make_videographer,
    make_job,
    add_assignment,
    confirm_job,
    cancel_job,
    set_clock,
    start_job,
    current_job_version,
    setup_adjourned_reporter_job,
    setup_certified_transcript,
    setup_delivered_transcript,
    order_transcript,
    add_exhibit,
    deliver_rough,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_case_payload,
    create_resource_payload,
    create_job_payload,
    create_attorney_payload,
    create_certify_payload,
    create_invoice_payload,
    make_schedule_coordinator_headers,
    make_billing_clerk_headers,
    make_attorney_headers,
    make_reporter_headers,
)

COORD = make_schedule_coordinator_headers()
BILLING = make_billing_clerk_headers()


# ---------------------------------------------------------------------------
# Entities section (corner)
# ---------------------------------------------------------------------------
def test_create_case_returns_201_with_all_fields(api):
    """PRD §3.1: "A `ScheduleCoordinator` (or a `PlatformAdmin`) opens a case by
    supplying its `caption`... and its `docket_number`... The case also carries a
    `jurisdiction`." PRD §2.4: "`version` is an integer that starts at its initial
    value on creation."

    Design: Corner/entities/create_case_returns_201_with_all_fields
    """
    att = make_attorney()
    resp = api.create_case(create_case_payload(
        caption="Alpha v Beta", docket_number="C-CASE-201",
        jurisdiction="STATE_CA", noticing_attorney_id=att["id"]), COORD)
    data = validate_success(resp, expected_status=201)
    assert_case(data)
    assert data["jurisdiction"] == "STATE_CA", (
        f"jurisdiction should echo STATE_CA, got {data['jurisdiction']}")
    assert data["version"] == 1, f"new case version should be 1, got {data['version']}"


def test_get_job_not_found_returns_404(api):
    """PRD §2.5: "the system validates existence left-to-right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path
    that does not resolve to an existing resource."

    Design: Corner/entities/get_job_not_found_returns_404
    """
    resp = api.get_job(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_case_missing_docket_number_rejected(api):
    """PRD §3.15: "Every create and update endpoint requires its mandatory body
    fields to be present and well-typed... a missing required field, a malformed
    type, or an out-of-set enum value is rejected with `ERR_INVALID_REQUEST`."
    docket_number is mandatory (PRD §3.1: "its `docket_number`... which must be
    non-empty").

    Design: Corner/entities/create_case_missing_docket_number_returns_invalid_request
    """
    att = make_attorney()
    payload = create_case_payload(noticing_attorney_id=att["id"])
    payload.pop("docket_number")
    resp = api.create_case(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_job_requires_videographer_defaults_false(api):
    """PRD §3.2: "The notice also declares the staffing requirements as booleans:
    `requires_videographer` and `requires_interpreter` (each defaulting to false)."

    Design: Corner/entities/job_requires_videographer_defaults_false
    """
    att = make_attorney()
    case = make_case(att["id"])
    job = make_job(case["id"], scheduled_start="2026-07-01T09:00:00Z",
                   scheduled_end="2026-07-01T11:00:00Z")
    assert job["requires_videographer"] is False, (
        f"requires_videographer should default to false, got {job['requires_videographer']}")


def test_job_staffing_posture_computed_unstaffed_at_create(api):
    """PRD §3.2: "A freshly noticed job enters `status` `NOTICED` and
    `staffing_posture` `UNSTAFFED`." PRD §3.4: "A job's `staffing_posture` is a
    derived field." A new job with no assignments is UNSTAFFED.

    Design: Corner/entities/job_staffing_posture_is_computed_unstaffed_at_create
    """
    att = make_attorney()
    case = make_case(att["id"])
    job = make_job(case["id"], scheduled_start="2026-07-02T09:00:00Z",
                   scheduled_end="2026-07-02T11:00:00Z")
    assert job["staffing_posture"] == "UNSTAFFED", (
        f"new job posture should be UNSTAFFED, got {job['staffing_posture']}")


def test_create_resource_invalid_kind_enum_rejected(api):
    """PRD §3.15: "enum-valued fields restricted to their declared sets; a missing
    required field, a malformed type, or an out-of-set enum value is rejected with
    `ERR_INVALID_REQUEST`." kind=STENOGRAPHER is out of the declared set.

    Design: Corner/entities/create_resource_invalid_kind_enum_returns_invalid_request
    """
    resp = api.create_resource(create_resource_payload(
        full_name="Bad Kind", kind="STENOGRAPHER", hourly_appearance_cents=5000), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_case_duplicate_docket_rejected(api):
    """PRD §3.1: "a `docket_number`... which must be non-empty and unique across
    all cases; a second case attempting to reuse a docket number is rejected with
    `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/create_case_duplicate_docket_number_returns_duplicate_key
    """
    att = make_attorney()
    make_case(att["id"], docket_number="C-DUP-2005")
    resp = api.create_case(create_case_payload(
        caption="Second", docket_number="C-DUP-2005", jurisdiction="STATE_NY",
        noticing_attorney_id=att["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_create_job_wrong_case_id_returns_not_found(api):
    """PRD §2.5: "The same 404 governs foreign-key references supplied in a request
    body: if a body field names a parent or related resource that does not exist,
    the request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/create_job_wrong_case_id_returns_not_found
    """
    resp = api.create_job(create_job_payload(
        case_id=NON_EXISTENT_UUID, scheduled_start="2026-07-03T09:00:00Z",
        scheduled_end="2026-07-03T11:00:00Z"), COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_jobs_pagination_envelope_fields(api):
    """PRD §2.3: "Every list-style response includes these fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`." A
    case with two jobs, listed with limit=1, reports total_count==2 and
    has_more==true.

    Design: Corner/entities/list_jobs_pagination_envelope_fields
    """
    att = make_attorney()
    case = make_case(att["id"])
    make_job(case["id"], scheduled_start="2026-07-04T09:00:00Z",
             scheduled_end="2026-07-04T11:00:00Z")
    make_job(case["id"], scheduled_start="2026-07-05T09:00:00Z",
             scheduled_end="2026-07-05T11:00:00Z")
    rows, meta = validate_paginated(api.list_jobs(
        COORD, params={"case_id": case["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more should be True, got {meta['has_more']}"


# ---------------------------------------------------------------------------
# Job state-precondition enforcement (corner state_machines)
# ---------------------------------------------------------------------------
def test_confirm_unstaffed_job_rejected(api):
    """PRD §3.5: "Confirmation requires that the job's staffing posture is `READY`
    — every required role covered — and that the job's `scheduled_start` is still
    in the future relative to the logical clock; if either precondition fails the
    transition is rejected." An UNSTAFFED job cannot confirm.

    Design: Corner/state_machines/confirm_job_from_unstaffed_returns_invalid_state
    """
    att = make_attorney()
    case = make_case(att["id"])
    job = make_job(case["id"], scheduled_start="2026-07-06T09:00:00Z",
                   scheduled_end="2026-07-06T11:00:00Z")
    resp = api.confirm_job(job["id"], {"expected_job_version": job["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_double_cancel_job_rejected(api):
    """PRD §3.5: "Cancelling a job is available from either `NOTICED` or
    `CONFIRMED` — the job's status must be one of those two states." PRD §3.5: "Any
    state transition attempted from a status that does not define it... is rejected
    with `ERR_INVALID_STATE`." A second cancel on an already-CANCELLED job is
    rejected.

    Design: Corner/state_machines/cancel_already_cancelled_job_returns_invalid_state
    """
    att = make_attorney()
    case = make_case(att["id"])
    job = make_job(case["id"], scheduled_start="2026-07-07T09:00:00Z",
                   scheduled_end="2026-07-07T11:00:00Z")
    cancel_job(job["id"])
    resp = api.cancel_job(job["id"], {"expected_job_version": current_job_version(job["id"])}, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_job_before_scheduled_start_rejected(api):
    """PRD §3.5: "Starting the session advances a `CONFIRMED` job to `IN_SESSION`.
    This requires the job to be `CONFIRMED` and the logical clock to have reached
    or passed the job's `scheduled_start`." With the clock at the 2026-01-01
    default, a job scheduled later cannot start.

    Design: Corner/state_machines/start_job_before_scheduled_start_returns_invalid_state
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    job = make_job(case["id"], scheduled_start="2026-07-08T09:00:00Z",
                   scheduled_end="2026-07-08T11:00:00Z")
    add_assignment(job["id"], rep["id"], "REPORTER")
    confirm_job(job["id"])  # clock at default 2026-01-01, scheduled_start in future: ok
    resp = api.start_job(job["id"], {"expected_job_version": current_job_version(job["id"])}, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Exhibits (corner validations + endpoints)
# ---------------------------------------------------------------------------
def test_duplicate_exhibit_label_rejected(api):
    """PRD §3.9: "The label must be non-empty and unique within its transcript
    order; a repeat label on the same transcript is rejected with
    `ERR_DUPLICATE_EXHIBIT_LABEL`."

    Design: Corner/validations/duplicate_exhibit_label_returns_duplicate_exhibit_label
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-07-24T09:00:00Z",
        scheduled_end="2026-07-24T11:00:00Z")
    order_transcript(sc, turnaround_tier="STANDARD", certified_copy=True,
                     estimated_pages=30)
    add_exhibit(sc, "Exhibit 1", 5)
    resp = api.create_exhibit(sc.transcript_order_id, {
        "marked_label": "Exhibit 1", "page_count": 9},
        make_attorney_headers(sc.attorney_id))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXHIBIT_LABEL.value)


def test_list_exhibits_filtered_by_confidential(api):
    """PRD §3.9: "when true the exhibit is sealed and excluded from the default
    e-delivery bundle." A confidential=false filter returns only the public
    exhibit.

    Design: Corner/endpoints/list_exhibits_filtered_by_confidential_flag
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-07-28T09:00:00Z",
        scheduled_end="2026-07-28T11:00:00Z")
    order_transcript(sc, turnaround_tier="STANDARD", certified_copy=True,
                     estimated_pages=30)
    add_exhibit(sc, "Exhibit 1", 5, confidential=False)
    add_exhibit(sc, "Exhibit 2", 7, confidential=True)
    rows, meta = validate_paginated(api.list_exhibits(
        sc.transcript_order_id, BILLING, params={"confidential": "false"}))
    assert meta["total_count"] == 1, (
        f"only the non-confidential exhibit should be listed, total_count={meta['total_count']}")


# ---------------------------------------------------------------------------
# Errors section (corner)
# ---------------------------------------------------------------------------
def test_duplicate_attorney_email_rejected(api):
    """PRD §3.1: "The email must be non-empty and unique across all attorneys; a
    duplicate is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/errors/error_duplicate_attorney_email_triggerable
    """
    api.create_attorney(create_attorney_payload(
        full_name="First Att", firm_name="F LLP", bar_state="CA",
        email="dup@x.com"), COORD)
    resp = api.create_attorney(create_attorney_payload(
        full_name="Second Att", firm_name="S LLP", bar_state="NY",
        email="dup@x.com"), COORD)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


# ---------------------------------------------------------------------------
# RBAC peer-role boundaries (corner)
# ---------------------------------------------------------------------------
def test_billing_clerk_cannot_certify_transcript(api):
    """PRD §2.1: "When an authenticated role attempts an operation that the
    role-based access matrix does not grant it, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." Certify is a Reporter/PlatformAdmin
    operation (PRD §4); a BillingClerk is forbidden.

    Design: Corner/rbac/billing_clerk_cannot_certify_transcript_returns_forbidden
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-07-30T09:00:00Z",
        scheduled_end="2026-07-30T11:00:00Z")
    order_transcript(sc, turnaround_tier="STANDARD", certified_copy=True,
                     estimated_pages=30)
    deliver_rough(sc)
    resp = api.certify_transcript(
        sc.transcript_order_id, create_certify_payload(final_pages=30), BILLING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_reporter_cannot_create_invoice(api):
    """PRD §2.1: "When an authenticated role attempts an operation that the
    role-based access matrix does not grant it, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." Creating an invoice is a
    BillingClerk/PlatformAdmin operation (PRD §4); a Reporter is forbidden.

    Design: Corner/rbac/reporter_cannot_create_invoice_returns_forbidden
    """
    sc, _ = setup_delivered_transcript(
        jurisdiction="STATE_CA", turnaround_tier="STANDARD",
        certified_copy=True, estimated_pages=30, final_pages=30)
    resp = api.create_invoice(create_invoice_payload(
        job_id=sc.job_id, transcript_order_id=sc.transcript_order_id),
        make_reporter_headers(sc.reporter_id))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)." A request bearing an unrecognized role is rejected.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    anon_headers = build_user_headers("anon-1", "Anonymous")
    resp = api.create_case(create_case_payload(
        caption="No Auth", docket_number="C-NOAUTH-1", jurisdiction="STATE_CA",
        noticing_attorney_id=NON_EXISTENT_UUID), anon_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
