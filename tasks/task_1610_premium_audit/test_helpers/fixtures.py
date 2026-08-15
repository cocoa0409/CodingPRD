"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Insured calls are entity-backed by Policy and Auditor
calls are entity-backed by Auditor. Every context dict carries per-instance
headers built from the real entity ids via the make_* builders; ownership-
gated calls never fall back to the shared constants.

The dominant return shape is a context dict ("ctx") with keys:
  cc               primary classification code
  policy           the policy under audit
  auditor          the assigned auditor (None when with_auditor=False)
  work_order       the current work order snapshot (refreshed by helpers)
  requests         list of records requests created on the work order
  result           the audit result, once drafted/issued (None before)
  billing          the first billing transaction of the result (None if none)
  dispute          the dispute, once filed (None before)
  manager          AuditManager headers for "mgr-1"
  manager2         AuditManager headers for "mgr-2" (segregation of duties)
  underwriter      Underwriter headers
  billing_clerk    BillingClerk headers
  auditor_headers  Auditor headers bound to auditor["id"]
  insured_headers  Insured headers bound to policy["id"]
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CC_WINDOW_END,
    CC_WINDOW_START,
    TERM_END,
    TERM_START,
)
from .factories import (
    create_appointment_payload,
    create_auditor_payload,
    create_certificate_payload,
    create_classification_code_payload,
    create_dispute_payload,
    create_payroll_allocation_payload,
    create_policy_payload,
    create_records_request_payload,
    create_subcontractor_exposure_payload,
    record_payment_payload,
)
from .test_users import (
    TEST_USERS,
    make_audit_manager_headers,
    make_auditor_headers,
    make_billing_clerk_headers,
    make_insured_headers,
    make_underwriter_headers,
)

MANAGER = TEST_USERS["audit_manager_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_class_code(code="8810", description="Clerical", state_code="CA",
                      coverage_line="WC", rate_per_100_cents=40,
                      high_hazard=False, effective_from=CC_WINDOW_START,
                      effective_to=CC_WINDOW_END):
    """Create a classification code. Returns the code."""
    payload = create_classification_code_payload(
        code=code, description=description, state_code=state_code,
        coverage_line=coverage_line, rate_per_100_cents=rate_per_100_cents,
        high_hazard=high_hazard, effective_from=effective_from,
        effective_to=effective_to)
    return get_success_data(api_client.create_classification_code(payload,
                                                                  UNDERWRITER))


def create_policy(policy_number, class_code_ids, coverage_line="WC",
                  state_code="CA", effective_date=TERM_START,
                  expiration_date=TERM_END,
                  estimated_annual_premium_cents=600000,
                  minimum_premium_cents=10000,
                  payroll_estimate_dollars=100000,
                  experience_mod_factor=None, insured_name=None):
    """Create a policy (born ACTIVE, version 1). Returns the policy."""
    payload = create_policy_payload(
        policy_number=policy_number,
        insured_name=insured_name or f"{policy_number} Insured",
        coverage_line=coverage_line, state_code=state_code,
        effective_date=effective_date, expiration_date=expiration_date,
        estimated_annual_premium_cents=estimated_annual_premium_cents,
        minimum_premium_cents=minimum_premium_cents,
        payroll_estimate_dollars=payroll_estimate_dollars,
        class_code_ids=list(class_code_ids))
    if experience_mod_factor is not None:
        payload["experience_mod_factor"] = experience_mod_factor
    return get_success_data(api_client.create_policy(payload, UNDERWRITER))


def create_auditor(full_name="Ada Auditor", territory_states=("CA",),
                   level="SENIOR"):
    """Register a field auditor. Returns the auditor."""
    payload = create_auditor_payload(full_name=full_name,
                                     territory_states=list(territory_states),
                                     level=level)
    return get_success_data(api_client.create_auditor(payload, MANAGER))


def set_clock(to_iso8601, headers=None):
    """Advance the logical clock (runs the sweeps). Returns the payload."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or MANAGER))


# ---------------------------------------------------------------------------
# Tier 2: selection and work-order genesis
# ---------------------------------------------------------------------------

def run_selection():
    """Run an audit selection pass over the book. Returns the run."""
    return get_success_data(api_client.run_audit_selection(MANAGER))


def find_work_order(policy_id, headers=None):
    """Return the first work order listed for the policy."""
    data, _meta = validate_paginated(
        api_client.list_work_orders(headers or MANAGER,
                                    params={"policy_id": policy_id}))
    assert len(data) >= 1, f"Expected a work order for policy {policy_id}"
    return data[0]


def get_work_order(work_order_id, headers=None):
    return get_success_data(api_client.get_work_order(work_order_id,
                                                      headers or MANAGER))


def refresh_work_order(ctx):
    """Re-read the work order into the context; returns it."""
    ctx["work_order"] = get_work_order(ctx["work_order"]["id"])
    return ctx["work_order"]


def wo_version(ctx):
    return refresh_work_order(ctx)["version"]


def assign_auditor(ctx, auditor=None):
    """Assign the context auditor to the work order."""
    auditor = auditor or ctx["auditor"]
    ctx["work_order"] = get_success_data(api_client.assign_work_order(
        ctx["work_order"]["id"], {"auditor_id": auditor["id"]}, MANAGER))
    return ctx["work_order"]


def add_records_request(ctx, request_type="PAYROLL_SUMMARY"):
    """Create a records request on the work order; tracks it in ctx."""
    req = get_success_data(api_client.create_records_request(
        ctx["work_order"]["id"], create_records_request_payload(
            request_type=request_type), MANAGER))
    ctx["requests"].append(req)
    refresh_work_order(ctx)
    return req


def receive_request(ctx, request):
    """The assigned auditor records receipt of a records request."""
    req = get_success_data(api_client.receive_records_request(
        request["id"], ctx["auditor_headers"]))
    return req


def receive_all_requests(ctx):
    for req in list(ctx["requests"]):
        receive_request(ctx, req)


# ---------------------------------------------------------------------------
# Tier 2.5: the base context (code + policy + auditor + selection + intake)
# ---------------------------------------------------------------------------

def setup_selected_work_order(
        policy_number="WC-FX-1",
        estimated_annual_premium_cents=600000,
        minimum_premium_cents=10000,
        payroll_estimate_dollars=100000,
        experience_mod_factor=1.00,
        rate_per_100_cents=40,
        high_hazard=False,
        class_code="8810",
        extra_codes=None,
        effective_date=TERM_START,
        expiration_date=TERM_END,
        state_code="CA",
        coverage_line="WC",
        with_auditor=True,
        assign=True,
        request_types=("PAYROLL_SUMMARY",),
        receive_requests=False):
    """Class code + policy + selection run + work order; optionally an
    assigned auditor and records requests. Returns the context dict.

    extra_codes: optional list of create_class_code kwargs for additional
    class codes; every created code's id is bound to the policy at inception
    and the codes are stored in ctx["ccs"] keyed by their code digits."""
    cc = create_class_code(code=class_code, state_code=state_code,
                           coverage_line=coverage_line,
                           rate_per_100_cents=rate_per_100_cents,
                           high_hazard=high_hazard)
    ccs = {class_code: cc}
    for code_kwargs in (extra_codes or []):
        code_kwargs.setdefault("state_code", state_code)
        code_kwargs.setdefault("coverage_line", coverage_line)
        extra = create_class_code(**code_kwargs)
        ccs[extra["code"]] = extra
    policy = create_policy(
        policy_number, [c["id"] for c in ccs.values()],
        coverage_line=coverage_line,
        state_code=state_code, effective_date=effective_date,
        expiration_date=expiration_date,
        estimated_annual_premium_cents=estimated_annual_premium_cents,
        minimum_premium_cents=minimum_premium_cents,
        payroll_estimate_dollars=payroll_estimate_dollars,
        experience_mod_factor=experience_mod_factor)
    auditor = create_auditor(territory_states=(state_code,)) if with_auditor \
        else None
    run_selection()
    work_order = find_work_order(policy["id"])
    ctx = {
        "cc": cc,
        "ccs": ccs,
        "policy": policy,
        "auditor": auditor,
        "work_order": work_order,
        "requests": [],
        "result": None,
        "billing": None,
        "dispute": None,
        "manager": make_audit_manager_headers("mgr-1"),
        "manager2": make_audit_manager_headers("mgr-2"),
        "underwriter": make_underwriter_headers("uw-1"),
        "billing_clerk": make_billing_clerk_headers("bill-1"),
        "auditor_headers": (make_auditor_headers(auditor["id"])
                            if auditor else None),
        "insured_headers": make_insured_headers(policy["id"]),
    }
    if assign and auditor is not None:
        assign_auditor(ctx)
    for request_type in request_types:
        add_records_request(ctx, request_type)
    if receive_requests:
        receive_all_requests(ctx)
    refresh_work_order(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: field work and drafting
# ---------------------------------------------------------------------------

def schedule_appointment(ctx, scheduled_start="2026-08-10T09:00:00Z",
                         scheduled_end="2026-08-10T11:00:00Z",
                         location_type="INSURED_PREMISES"):
    """The assigned auditor schedules an appointment (OCC-guarded)."""
    payload = create_appointment_payload(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        location_type=location_type,
        expected_work_order_version=wo_version(ctx))
    appt = get_success_data(api_client.create_appointment(
        ctx["work_order"]["id"], payload, ctx["auditor_headers"]))
    refresh_work_order(ctx)
    return appt


def confirm_appointment(ctx, appointment, by_insured=True):
    headers = ctx["insured_headers"] if by_insured else ctx["auditor_headers"]
    return get_success_data(api_client.confirm_appointment(
        appointment["id"], headers))


def complete_appointment(ctx, appointment):
    """The assigned auditor completes the appointment; the work order
    advances to FIELD_WORK_DONE."""
    appt = get_success_data(api_client.complete_appointment(
        appointment["id"], ctx["auditor_headers"]))
    refresh_work_order(ctx)
    return appt


def no_show_appointment(ctx, appointment):
    appt = get_success_data(api_client.no_show_appointment(
        appointment["id"], ctx["auditor_headers"]))
    refresh_work_order(ctx)
    return appt


def setup_field_work_done(ctx, scheduled_start="2026-08-10T09:00:00Z",
                          scheduled_end="2026-08-10T11:00:00Z"):
    """Schedule + complete the field appointment. Returns the appointment."""
    appt = schedule_appointment(ctx, scheduled_start, scheduled_end)
    complete_appointment(ctx, appt)
    return appt


def add_allocation(ctx, gross_payroll_dollars, class_code_id=None,
                   period_start="2026-01-01T00:00:00Z",
                   period_end="2026-06-30T00:00:00Z",
                   overtime_excess_dollars=None, overtime_documented=None,
                   severance_dollars=None, other_exclusions_dollars=None,
                   verify=False):
    """Create a payroll allocation (OCC-guarded); optionally verify it."""
    payload = create_payroll_allocation_payload(
        class_code_id=class_code_id or ctx["cc"]["id"],
        period_start=period_start, period_end=period_end,
        gross_payroll_dollars=gross_payroll_dollars,
        expected_work_order_version=wo_version(ctx))
    if overtime_excess_dollars is not None:
        payload["overtime_excess_dollars"] = overtime_excess_dollars
    if overtime_documented is not None:
        payload["overtime_documented"] = overtime_documented
    if severance_dollars is not None:
        payload["severance_dollars"] = severance_dollars
    if other_exclusions_dollars is not None:
        payload["other_exclusions_dollars"] = other_exclusions_dollars
    allocation = get_success_data(api_client.create_payroll_allocation(
        ctx["work_order"]["id"], payload, ctx["auditor_headers"]))
    refresh_work_order(ctx)
    if verify:
        allocation = get_success_data(api_client.verify_payroll_allocation(
            allocation["id"], ctx["auditor_headers"]))
    return allocation


def add_exposure(ctx, subcontractor_name="SubCo", payments_dollars=10000,
                 governing_class_code_id=None):
    """Register a subcontractor exposure (born INCLUDED at full value)."""
    payload = create_subcontractor_exposure_payload(
        subcontractor_name=subcontractor_name,
        payments_dollars=payments_dollars,
        governing_class_code_id=governing_class_code_id or ctx["cc"]["id"])
    exposure = get_success_data(api_client.create_subcontractor_exposure(
        ctx["work_order"]["id"], payload, ctx["auditor_headers"]))
    refresh_work_order(ctx)
    return exposure


def add_certificate(ctx, exposure, insurer_name="Zenith",
                    wc_coverage_present=True, gl_coverage_present=False,
                    coverage_effective_date=TERM_START,
                    coverage_expiration_date=TERM_END, by_insured=False):
    """Submit a certificate for an exposure (insured or assigned auditor)."""
    payload = create_certificate_payload(
        insurer_name=insurer_name, wc_coverage_present=wc_coverage_present,
        gl_coverage_present=gl_coverage_present,
        coverage_effective_date=coverage_effective_date,
        coverage_expiration_date=coverage_expiration_date)
    headers = ctx["insured_headers"] if by_insured else ctx["auditor_headers"]
    return get_success_data(api_client.submit_certificate(
        exposure["id"], payload, headers))


def verify_certificate(ctx, certificate):
    cert = get_success_data(api_client.verify_certificate(
        certificate["id"], ctx["auditor_headers"]))
    refresh_work_order(ctx)
    return cert


def submit_draft(ctx):
    """The assigned auditor submits the draft result (provisional figures)."""
    ctx["result"] = get_success_data(api_client.submit_draft(
        ctx["work_order"]["id"], ctx["auditor_headers"]))
    refresh_work_order(ctx)
    return ctx["result"]


def issue_result(ctx, clock="2026-08-15T00:00:00Z", issuer="mgr-1"):
    """Set the clock, then an AuditManager issues the final result."""
    set_clock(clock)
    ctx["result"] = get_success_data(api_client.issue_result(
        ctx["work_order"]["id"], make_audit_manager_headers(issuer)))
    refresh_work_order(ctx)
    return ctx["result"]


def result_billings(ctx, result=None):
    """List the billing transactions of the context result."""
    result = result or ctx["result"]
    data, _meta = validate_paginated(
        api_client.list_result_billing_transactions(result["id"], MANAGER))
    return data


def first_billing(ctx):
    """Return the result's first billing transaction (or None)."""
    billings = result_billings(ctx)
    ctx["billing"] = billings[0] if billings else None
    return ctx["billing"]


# ---------------------------------------------------------------------------
# Tier 4: full standard lifecycle to ISSUED
# ---------------------------------------------------------------------------

def setup_issued_standard_result(
        policy_number="WC-ISS-1",
        gross_payroll_dollars=95000,
        estimated_annual_premium_cents=600000,
        minimum_premium_cents=10000,
        payroll_estimate_dollars=100000,
        experience_mod_factor=1.20,
        rate_per_100_cents=40,
        high_hazard=False,
        physical=False,
        issue_clock="2026-08-15T00:00:00Z",
        issuer="mgr-1"):
    """Drive a work order through intake, one verified allocation, draft and
    issuance. Returns the context with ctx["result"] ISSUED."""
    ctx = setup_selected_work_order(
        policy_number=policy_number,
        estimated_annual_premium_cents=estimated_annual_premium_cents,
        minimum_premium_cents=minimum_premium_cents,
        payroll_estimate_dollars=payroll_estimate_dollars,
        experience_mod_factor=experience_mod_factor,
        rate_per_100_cents=rate_per_100_cents,
        high_hazard=high_hazard,
        receive_requests=True)
    if physical:
        setup_field_work_done(ctx)
    add_allocation(ctx, gross_payroll_dollars, verify=True)
    submit_draft(ctx)
    issue_result(ctx, clock=issue_clock, issuer=issuer)
    first_billing(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4b: non-compliance / estimated-billing lifecycle
# ---------------------------------------------------------------------------

def setup_noncompliant_work_order(policy_number="WC-NC-1",
                                  estimated_annual_premium_cents=2000000,
                                  minimum_premium_cents=100000,
                                  payroll_estimate_dollars=100000,
                                  experience_mod_factor=1.20,
                                  marker="mgr-1",
                                  overdue_clock="2026-08-17T00:00:00Z"):
    """A work order whose records request went OVERDUE and which an
    AuditManager has flagged NONCOMPLIANT_PENDING."""
    ctx = setup_selected_work_order(
        policy_number=policy_number,
        estimated_annual_premium_cents=estimated_annual_premium_cents,
        minimum_premium_cents=minimum_premium_cents,
        payroll_estimate_dollars=payroll_estimate_dollars,
        experience_mod_factor=experience_mod_factor,
        with_auditor=False, assign=False)
    set_clock(overdue_clock)
    ctx["work_order"] = get_success_data(api_client.mark_noncompliant(
        ctx["work_order"]["id"], make_audit_manager_headers(marker)))
    return ctx


def approve_estimated(ctx, approver="mgr-2"):
    """A different AuditManager approves the estimated audit."""
    ctx["result"] = get_success_data(api_client.approve_estimated(
        ctx["work_order"]["id"], make_audit_manager_headers(approver)))
    refresh_work_order(ctx)
    first_billing(ctx)
    return ctx["result"]


# ---------------------------------------------------------------------------
# Tier 5: disputes, review, closure
# ---------------------------------------------------------------------------

def file_dispute(ctx, grounds="PAYROLL_ERROR", clock=None):
    """The insured files a dispute against the issued result."""
    if clock is not None:
        set_clock(clock)
    ctx["dispute"] = get_success_data(api_client.file_dispute(
        ctx["result"]["id"], create_dispute_payload(grounds=grounds),
        ctx["insured_headers"]))
    refresh_work_order(ctx)
    return ctx["dispute"]


def start_review(ctx, reviewer="mgr-2"):
    ctx["dispute"] = get_success_data(api_client.start_review_dispute(
        ctx["dispute"]["id"], make_audit_manager_headers(reviewer)))
    return ctx["dispute"]


def setup_dispute_under_review(policy_number="WC-DSP-1",
                               dispute_clock="2026-08-20T00:00:00Z",
                               grounds="PAYROLL_ERROR", reviewer="mgr-2",
                               **issue_kwargs):
    """Full chain: issued standard result + dispute FILED + UNDER_REVIEW."""
    ctx = setup_issued_standard_result(policy_number=policy_number,
                                       **issue_kwargs)
    file_dispute(ctx, grounds=grounds, clock=dispute_clock)
    start_review(ctx, reviewer=reviewer)
    return ctx


def record_payment(ctx, amount_cents, billing=None):
    """The BillingClerk records a payment / credit application."""
    billing = billing or ctx["billing"]
    return get_success_data(api_client.record_payment(
        billing["id"], record_payment_payload(amount_cents=amount_cents),
        ctx["billing_clerk"]))


def close_work_order(ctx):
    ctx["work_order"] = get_success_data(api_client.close_work_order(
        ctx["work_order"]["id"], MANAGER))
    return ctx["work_order"]


def list_policy_mod_revisions(ctx):
    data, _meta = validate_paginated(
        api_client.list_policy_mod_revisions(ctx["policy"]["id"], UNDERWRITER))
    return data
