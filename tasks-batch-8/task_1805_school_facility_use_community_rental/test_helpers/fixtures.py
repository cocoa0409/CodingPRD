"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly restarted server with an empty database and
the logical clock at 2026-08-01T00:00:00Z (PRD §2.4), so each helper builds
its preconditions from scratch using only PRD-declared endpoints. Internal
setup calls use get_success_data() so setup failures surface as clear
"Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_site_payload,
    create_facility_payload,
    create_rate_policy_payload,
    create_renter_payload,
    create_insurance_payload,
    create_request_payload,
    create_damage_assessment_payload,
    create_calendar_event_payload,
)
from .test_users import TEST_USERS, make_renter_headers

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ─── Tier 1/2: inventory, policy, renter, insurance ─────────────────────────

def make_site(site_code="RHS", **overrides):
    """Create a school site. Returns the SchoolSite row."""
    return get_success_data(api_client.create_site(
        create_site_payload(site_code=site_code, **overrides), ADMIN))


def make_facility(site_id, **overrides):
    """Create a facility within a site. Returns the Facility row."""
    return get_success_data(api_client.create_facility(
        site_id, create_facility_payload(**overrides), ADMIN))


def make_policy(**overrides):
    """Create a rate class policy. Returns the RateClassPolicy row."""
    return get_success_data(api_client.create_rate_policy(
        create_rate_policy_payload(**overrides), ADMIN))


def make_renter(org_name="Riverview PTA", rate_class="NONPROFIT", **overrides):
    """Register a renter organization (FacilitiesDirector). Returns the org row."""
    payload = create_renter_payload(org_name=org_name, rate_class=rate_class, **overrides)
    if rate_class != "NONPROFIT":
        payload.pop("nonprofit_registration_no", None)
    return get_success_data(api_client.create_renter(payload, DIRECTOR))


def make_insurance(org_id, **overrides):
    """Upload an insurance certificate as the org's own representative."""
    return get_success_data(api_client.upload_insurance_certificate(
        org_id, create_insurance_payload(**overrides), make_renter_headers(org_id)))


def make_booking_env(site_code="RHS", facility_overrides=None, policy_overrides=None,
                     org_name="Riverview PTA", rate_class="NONPROFIT",
                     insurance=True, insurance_overrides=None):
    """Site + facility + rate policy + renter (+ VALID insurance certificate).

    Returns dict with keys: site, facility, policy, org, cert (cert None when
    insurance=False)."""
    site = make_site(site_code)
    facility = make_facility(site["id"], **(facility_overrides or {}))
    policy = make_policy(**(policy_overrides or {}))
    org = make_renter(org_name, rate_class)
    cert = None
    if insurance:
        cert = make_insurance(org["id"], **(insurance_overrides or {}))
    return {"site": site, "facility": facility, "policy": policy, "org": org, "cert": cert}


# ─── Tier 1: request state progression ──────────────────────────────────────

def make_draft_request(env, **overrides):
    """Create a DRAFT rental request as the org's representative."""
    org_id = env["org"]["id"]
    payload = create_request_payload(env["facility"]["id"], **overrides)
    return get_success_data(api_client.create_request(org_id, payload, make_renter_headers(org_id)))


def submit_request(env, request_id):
    """DRAFT -> SUBMITTED. Returns the updated request row."""
    org_id = env["org"]["id"]
    return get_success_data(api_client.submit_request(org_id, request_id, make_renter_headers(org_id)))


def begin_review(request_id):
    """SUBMITTED/RESUBMITTED -> UNDER_REVIEW. Returns the updated request row
    (its `version` is the value approve() must carry in expected_request_version)."""
    return get_success_data(api_client.begin_review(request_id, COORDINATOR))


def make_under_review_request(env, **overrides):
    """Create -> submit -> begin_review. Returns the UNDER_REVIEW request row."""
    req = make_draft_request(env, **overrides)
    submit_request(env, req["id"])
    return begin_review(req["id"])


def approve(request_id, expected_request_version):
    """Approve an UNDER_REVIEW request. Returns the created Permit row."""
    return get_success_data(api_client.approve_request(
        request_id, {"expected_request_version": expected_request_version}, DIRECTOR))


# ─── Tier 3: full lifecycle shortcuts ───────────────────────────────────────

def setup_approved_permit(site_code="RHS", facility_overrides=None, policy_overrides=None,
                          org_name="Riverview PTA", rate_class="NONPROFIT",
                          insurance=True, insurance_overrides=None, **request_overrides):
    """Full chain through approval. Returns (env, request, permit)."""
    env = make_booking_env(site_code, facility_overrides, policy_overrides,
                           org_name, rate_class, insurance, insurance_overrides)
    req = make_under_review_request(env, **request_overrides)
    permit = approve(req["id"], req["version"])
    return env, req, permit


def capture_deposit(env, permit_id, amount_cents, idempotency_key):
    """Post a DEPOSIT_CAPTURE payment as the org's representative."""
    return get_success_data(api_client.post_payment(
        permit_id,
        {"txn_kind": "DEPOSIT_CAPTURE", "amount_cents": amount_cents,
         "idempotency_key": idempotency_key},
        make_renter_headers(env["org"]["id"])))


def setup_secured_permit(deposit_cents, idempotency_key="dep-1", **kwargs):
    """Approved permit + exact deposit captured (financial SECURED).
    Returns (env, request, permit)."""
    env, req, permit = setup_approved_permit(**kwargs)
    capture_deposit(env, permit["id"], deposit_cents, idempotency_key)
    permit = get_success_data(api_client.get_permit(permit["id"], DIRECTOR))
    return env, req, permit


def set_clock(to_iso8601):
    """Advance the server logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def setup_completed_permit(deposit_cents=10000, clock_after_end="2026-09-13T12:00:00Z",
                           actual_hours=None, idempotency_key="dep-1", **kwargs):
    """Secured permit driven through event completion.

    Clock advances past occupancy_end (which also activates the permit), then
    the SiteCoordinator marks completion. When actual_hours is given, the
    custodial work order is verified with those hours (drives the FINAL
    invoice's staffing component).

    Returns (env, request, permit, work_order_or_None).
    """
    env, req, permit = setup_secured_permit(deposit_cents, idempotency_key, **kwargs)
    set_clock(clock_after_end)
    get_success_data(api_client.complete_permit(permit["id"], COORDINATOR))
    work_order = None
    if env["facility"].get("requires_custodian", True):
        orders = get_success_data(api_client.list_permit_work_orders(permit["id"], SUPERVISOR))
        assert len(orders) == 1, f"Setup: expected one work order, got {len(orders)}"
        work_order = orders[0]
        if actual_hours is not None:
            work_order = get_success_data(api_client.verify_work_order(
                work_order["id"], {"actual_hours": actual_hours}, SUPERVISOR))
    permit = get_success_data(api_client.get_permit(permit["id"], DIRECTOR))
    return env, req, permit, work_order


# ─── Tier 4: finalized damage flow ──────────────────────────────────────────

def make_damage_assessment(permit_id, line_items, coordinator_headers=None):
    """Record damage intake on a COMPLETED permit (SiteCoordinator)."""
    return get_success_data(api_client.create_damage_assessment(
        permit_id, {"line_items": line_items}, coordinator_headers or COORDINATOR))


def setup_permit_with_final_damage(deposit_cents=10000, line_items=None,
                                   adjudicated_cents=8000, **kwargs):
    """Completed permit + OPEN assessment + adjudication + renter accept.

    Drives the permit through the deposit forfeiture allocation and returns
    (env, request, permit, assessment) after the assessment is FINAL.
    """
    env, req, permit, _wo = setup_completed_permit(deposit_cents, **kwargs)
    assessment = make_damage_assessment(permit["id"], line_items or [
        {"description": "Floor damage", "repair_cost_cents": 8000}])
    get_success_data(api_client.adjudicate_damage_assessment(
        assessment["id"], {"adjudicated_amount_cents": adjudicated_cents}, DIRECTOR))
    org_id = env["org"]["id"]
    assessment = get_success_data(api_client.accept_damage_assessment(
        assessment["id"], make_renter_headers(org_id)))
    permit = get_success_data(api_client.get_permit(permit["id"], DIRECTOR))
    return env, req, permit, assessment


# ─── Additional composite helpers (additive) ────────────────────────────────

def add_renter_with_insurance(org_name, rate_class="NONPROFIT", insurance_overrides=None,
                              **renter_overrides):
    """Register another renter organization and upload its VALID certificate.
    Returns (org, cert)."""
    org = make_renter(org_name, rate_class, **renter_overrides)
    cert = make_insurance(org["id"], **(insurance_overrides or {}))
    return org, cert


def make_approved_permit_in_env(env, **request_overrides):
    """Within an existing env: create -> submit -> begin_review -> approve.
    Returns (request, permit)."""
    req = make_under_review_request(env, **request_overrides)
    permit = approve(req["id"], req["version"])
    return req, permit


def make_calendar_event(site_id, **overrides):
    """Record a school calendar event (DistrictAdmin). Returns the event row."""
    return get_success_data(api_client.create_calendar_event(
        site_id, create_calendar_event_payload(**overrides), ADMIN))


def pay_fee(env, permit_id, invoice_id, amount_cents, idempotency_key):
    """Post a FEE_PAYMENT against a specific invoice as the org's representative."""
    return get_success_data(api_client.post_payment(
        permit_id,
        {"txn_kind": "FEE_PAYMENT", "amount_cents": amount_cents,
         "idempotency_key": idempotency_key, "invoice_id": invoice_id},
        make_renter_headers(env["org"]["id"])))


def get_single_work_order(permit_id):
    """Fetch the permit's unique custodial work order."""
    orders = get_success_data(api_client.list_permit_work_orders(permit_id, SUPERVISOR))
    assert len(orders) == 1, f"Setup: expected one work order, got {len(orders)}"
    return orders[0]


def complete_permit_at(permit_id, clock_iso):
    """Advance the logical clock (activating a SECURED permit) and mark the
    event complete. Returns the refreshed permit row."""
    set_clock(clock_iso)
    get_success_data(api_client.complete_permit(permit_id, COORDINATOR))
    return get_success_data(api_client.get_permit(permit_id, DIRECTOR))
