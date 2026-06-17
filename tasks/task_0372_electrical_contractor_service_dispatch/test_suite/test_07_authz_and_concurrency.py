"""Authentication, role authorization, resource ownership, and OCC on estimate create.

Queue B (Corner): validations (stale version on estimate), errors, rbac sections.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    build_user_headers, make_customer_headers, make_technician_headers,
    make_customer, make_technician, make_job,
    quote_and_accept, dispatch_tech, file_permit,
)

DISP = TEST_USERS["dispatcher_headers"]
INSP = TEST_USERS["inspector_headers"]


# ─── Queue B: OCC stale version on estimate create ────────────────────────
def test_stale_version_on_estimate_create(api):
    """PRD §2.5: "When a client submits a request to create an estimate, the supplied
    `expected_job_version` must equal the target job's current `version`. If another writer
    has advanced the job's `version` since the client last read it ... the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_version_on_estimate_create
    """
    cust = make_customer(email="sv@x.com", service_zip="32001")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    # first estimate create advances the job version off v0
    validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 10000},
        DISP), 201)
    # second create still carrying v0 is stale
    resp = api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 11000},
        DISP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ─── Queue B: errors section ──────────────────────────────────────────────
def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a known
    role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    resp = api._request("GET", "/v1/customers", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_forbidden_role_customer_creates_technician(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation according to the authorization rules in this document,
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 authorizes POST /v1/technicians for Dispatcher only.

    Design: Corner/errors/forbidden_role_customer_creates_technician
    """
    cust = make_customer(email="fb@x.com", service_zip="45001")
    resp = api.create_technician(
        {"full_name": "Sneaky", "license_class": "MASTER", "service_zone": "450", "hourly_rate_cents": 9000},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_not_resource_owner_other_customer_accepts(api):
    """PRD §2.1: "When an entity-backed actor (a `Customer` or a `Technician`) targets a
    resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
    For example, a `Customer` may only accept, reject, cancel, or file callbacks against jobs
    whose `customer_id` equals their own `X-User-ID`."

    Design: Corner/errors/not_resource_owner_other_customer_accepts
    """
    custA = make_customer(email="owna@x.com", service_zip="46001")
    custB = make_customer(email="othb@x.com", service_zip="46002")
    job = make_job(custA["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    est = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 10000},
        DISP), 201)
    api.send_estimate(est["id"], DISP)
    resp = api.accept_estimate(est["id"], make_customer_headers(custB["id"]))  # B does not own the job
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ─── Queue B: rbac section ────────────────────────────────────────────────
def test_technician_not_assigned_cannot_depart(api):
    """PRD §2.1: "a `Technician` may only depart, arrive, or record material against
    dispatches and trucks tied to their own `X-User-ID`."

    Design: Corner/rbac/technician_not_assigned_cannot_depart
    """
    cust = make_customer(email="rb@x.com", service_zip="47001")
    tech1 = make_technician(full_name="Tech One", service_zone="470", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    tech2 = make_technician(full_name="Tech Two", service_zone="470", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech1["id"], "2026-08-17T09:00:00Z", "2026-08-17T10:00:00Z")
    resp = api.depart_dispatch(disp["id"], make_technician_headers(tech2["id"]))  # tech2 is not assigned
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_inspector_only_issues_permit(api):
    """PRD §4 authorizes POST /v1/permits/{permitId}/issue for Inspector only.
    PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation according to the authorization rules in this document,
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/inspector_only_issues_permit
    """
    cust = make_customer(email="in@x.com", service_zip="48001")
    job = make_job(cust["id"], scope="PANEL", job_class="INSTALL")
    permit = file_permit(job["id"], jurisdiction="County", permit_number="IN-1")
    resp = api.issue_permit(permit["id"], DISP)  # Dispatcher attempting an Inspector-exclusive op
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_shared_op_customer_can_create_own_job(api):
    """PRD §3.3: "A customer may open a job for themselves, or a dispatcher may open one on
    their behalf."
    PRD §4 authorizes POST /v1/service-jobs for Dispatcher and Customer.

    Design: Corner/rbac/shared_op_customer_and_dispatcher_create_job
    """
    cust = make_customer(email="sh@x.com", service_zip="49001")
    resp = api.create_service_job(
        {"customer_id": cust["id"], "scope": "OUTLET", "job_class": "SERVICE"},
        make_customer_headers(cust["id"]),
    )
    data = validate_success(resp, 201)
    assert data["customer_id"] == cust["id"]
    assert data["status"] == "DRAFT"
