"""Composite state builders.

Every ladder here builds its state from scratch through PRD-declared endpoints
only: the harness restarts the server before each test, so nothing is carried
between tests.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .test_users import (
    COMPLIANCE_OFFICER,
    FACILITIES_ENGINEER,
    LEASING_AGENT,
    PORTFOLIO_ADMIN,
    PROPERTY_MANAGER,
    SECOND_COMPLIANCE_OFFICER,
)


def _data(response, expected_status: Optional[int] = None) -> Dict[str, Any]:
    return get_success_data(response, expected_status)


# --- Clock and daily close ------------------------------------------------
def set_clock(api, instant: str) -> Dict[str, Any]:
    """Move the logical clock forward to the supplied instant."""
    return _data(api.set_clock(instant, PORTFOLIO_ADMIN))


def set_clock_date(api, date_str: str) -> Dict[str, Any]:
    """Move the logical clock to midnight UTC on the supplied calendar date."""
    return set_clock(api, "{}T00:00:00Z".format(date_str))


def run_daily_close(api) -> Dict[str, Any]:
    """Run one daily close, executing the six scheduled phases in fixed order."""
    return _data(api.run_daily_close(PORTFOLIO_ADMIN))


# --- Primitive registrations ---------------------------------------------
def register_building(api, **overrides) -> Dict[str, Any]:
    """Register a medical office building as the PortfolioAdmin."""
    return _data(api.create_building(f.create_building_payload(**overrides), PORTFOLIO_ADMIN), 201)


def register_suite(api, building_id: str, **overrides) -> Dict[str, Any]:
    """Add a leasable suite to a building as the PortfolioAdmin."""
    payload = f.create_suite_payload(**overrides)
    return _data(api.create_suite(building_id, payload, PORTFOLIO_ADMIN), 201)


def register_shared_space(api, building_id: str, **overrides) -> Dict[str, Any]:
    """Register a shared clinical space as the PortfolioAdmin."""
    payload = f.create_shared_space_payload(**overrides)
    return _data(api.create_shared_space(building_id, payload, PORTFOLIO_ADMIN), 201)


def register_tenant(api, **overrides) -> Dict[str, Any]:
    """Register a tenant practice as the PortfolioAdmin."""
    return _data(api.create_tenant(f.create_tenant_payload(**overrides), PORTFOLIO_ADMIN), 201)


def draft_lease(api, building_id: str, suite_id: str, tenant_id: str,
                **overrides) -> Dict[str, Any]:
    """Open a lease as a draft; the LeasingAgent's act."""
    payload = f.create_lease_payload(building_id, suite_id, tenant_id, **overrides)
    return _data(api.create_lease(payload, LEASING_AGENT), 201)


# --- Lease paper trail ----------------------------------------------------
def file_attestation(api, lease_id: str, attestation_type: str = "SIGNED_LEASE",
                     on_file: bool = True) -> Dict[str, Any]:
    """File a compliance attestation against the lease; advances the lease version."""
    payload = f.attestation_payload(attestation_type=attestation_type, on_file=on_file)
    return _data(api.record_attestation(lease_id, payload, LEASING_AGENT), 200)


def file_appraisal(api, lease_id: str, expected_lease_version: int,
                   **overrides) -> Dict[str, Any]:
    """File an independent appraisal against the lease under lease-level concurrency."""
    payload = f.create_appraisal_payload(expected_lease_version, **overrides)
    return _data(api.create_appraisal(lease_id, payload, COMPLIANCE_OFFICER), 201)


def qualify_appraisal(api, appraisal_id: str,
                      decision_reason: str = "Independence verified") -> Dict[str, Any]:
    """Move an appraisal SUBMITTED -> QUALIFIED."""
    payload = f.appraisal_decision_payload("QUALIFY", decision_reason)
    return _data(api.decide_appraisal(appraisal_id, payload, COMPLIANCE_OFFICER))


def disqualify_appraisal(api, appraisal_id: str,
                         decision_reason: str = "Opinion withdrawn") -> Dict[str, Any]:
    """Move an appraisal to DISQUALIFIED from SUBMITTED or QUALIFIED."""
    payload = f.appraisal_decision_payload("DISQUALIFY", decision_reason)
    return _data(api.decide_appraisal(appraisal_id, payload, COMPLIANCE_OFFICER))


def qualified_appraisal_for(api, lease_id: str, expected_lease_version: int,
                            **overrides) -> Dict[str, Any]:
    """File and then qualify one appraisal, the physician-owned prerequisite."""
    appraisal = file_appraisal(api, lease_id, expected_lease_version, **overrides)
    return qualify_appraisal(api, appraisal["id"])


# --- Lease review and certification --------------------------------------
def submit_for_review(api, lease_id: str,
                      submission_note: str = "Ready for review") -> Dict[str, Any]:
    """Move a lease DRAFT -> PENDING_FMV_REVIEW as the submitting LeasingAgent."""
    return _data(api.submit_fmv_review(lease_id, {"submission_note": submission_note},
                                       LEASING_AGENT))


def certify(api, lease_id: str, certification_note: str = "Band verified") -> Dict[str, Any]:
    """Certify fair market value as a ComplianceOfficer other than the submitter."""
    return _data(api.certify_fmv(lease_id, {"certification_note": certification_note},
                                 COMPLIANCE_OFFICER))


def return_for_revision(api, lease_id: str,
                        decision_note: str = "Rework the term") -> Dict[str, Any]:
    """Send a lease in review back to the agent, PENDING_FMV_REVIEW -> DRAFT."""
    payload = f.lease_compliance_decision_payload("RETURN_FOR_REVISION", decision_note)
    return _data(api.lease_compliance_decision(lease_id, payload, COMPLIANCE_OFFICER))


def reinstate(api, lease_id: str, decision_note: str = "Mix reviewed") -> Dict[str, Any]:
    """Move a lease SUSPENDED_MIX_REVIEW -> DRAFT."""
    payload = f.lease_compliance_decision_payload("REINSTATE", decision_note)
    return _data(api.lease_compliance_decision(lease_id, payload, COMPLIANCE_OFFICER))


def execute(api, lease_id: str, execution_note: str = "Signed and executed") -> Dict[str, Any]:
    """Move a certified lease FMV_CERTIFIED -> EXECUTED, reserving the suite."""
    return _data(api.execute_lease(lease_id, {"execution_note": execution_note}, LEASING_AGENT))


def commence(api, lease_id: str, commencement_note: str = "Possession taken") -> Dict[str, Any]:
    """Move a lease EXECUTED -> ACTIVE, occupying the suite."""
    return _data(api.commence_lease(lease_id, {"commencement_note": commencement_note},
                                    PROPERTY_MANAGER))


def terminate(api, lease_id: str, termination_reason: str = "MUTUAL",
              **overrides) -> Dict[str, Any]:
    """Terminate occupancy and run the release cascade."""
    payload = f.terminate_payload(termination_reason, **overrides)
    return _data(api.terminate_lease(lease_id, payload, PROPERTY_MANAGER))


def authorize_after_hours(api, lease_id: str, authorized: bool = True) -> Dict[str, Any]:
    """Grant or revoke after-hours building access on the lease."""
    return _data(api.set_after_hours_authorization(lease_id, f.after_hours_payload(authorized),
                                                   PROPERTY_MANAGER))


# --- Composite leasing ladders -------------------------------------------
def leasing_baseline(api, building_overrides: Optional[Dict] = None,
                     suite_overrides: Optional[Dict] = None,
                     tenant_overrides: Optional[Dict] = None) -> Dict[str, Any]:
    """A building with one suite and one tenant practice: the common starting point."""
    building = register_building(api, **(building_overrides or {}))
    suite = register_suite(api, building["id"], **(suite_overrides or {}))
    tenant = register_tenant(api, **(tenant_overrides or {}))
    return {"building": building, "suite": suite, "tenant": tenant}


def drafted_lease(api, building_overrides: Optional[Dict] = None,
                  suite_overrides: Optional[Dict] = None,
                  tenant_overrides: Optional[Dict] = None,
                  lease_overrides: Optional[Dict] = None) -> Dict[str, Any]:
    """A DRAFT lease on a fresh building/suite/tenant triple."""
    ctx = leasing_baseline(api, building_overrides, suite_overrides, tenant_overrides)
    ctx["lease"] = draft_lease(api, ctx["building"]["id"], ctx["suite"]["id"],
                               ctx["tenant"]["id"], **(lease_overrides or {}))
    return ctx


def certified_lease(api, building_overrides: Optional[Dict] = None,
                    suite_overrides: Optional[Dict] = None,
                    tenant_overrides: Optional[Dict] = None,
                    lease_overrides: Optional[Dict] = None,
                    file_signed_lease: bool = True) -> Dict[str, Any]:
    """A lease driven to FMV_CERTIFIED: attestation, review submission, certification.

    A physician-owned tenant additionally receives one qualified appraisal, which
    review submission and certification both require.
    """
    ctx = drafted_lease(api, building_overrides, suite_overrides, tenant_overrides,
                        lease_overrides)
    lease_id = ctx["lease"]["id"]
    if file_signed_lease:
        ctx["lease"] = file_attestation(api, lease_id, "SIGNED_LEASE")
    if ctx["tenant"].get("is_physician_owned"):
        ctx["appraisal"] = qualified_appraisal_for(api, lease_id, ctx["lease"]["version"])
        ctx["lease"] = _data(api.get_lease(lease_id, LEASING_AGENT))
    ctx["lease"] = submit_for_review(api, lease_id)
    ctx["lease"] = certify(api, lease_id)
    return ctx


def executed_lease(api, **kwargs) -> Dict[str, Any]:
    """A lease driven to EXECUTED, with its suite RESERVED."""
    ctx = certified_lease(api, **kwargs)
    ctx["lease"] = execute(api, ctx["lease"]["id"])
    ctx["building"] = _data(api.get_building(ctx["building"]["id"], PORTFOLIO_ADMIN))
    ctx["suite"] = _data(api.get_suite(ctx["suite"]["id"], PORTFOLIO_ADMIN))
    return ctx


def active_lease(api, **kwargs) -> Dict[str, Any]:
    """A lease driven to ACTIVE: the clock is advanced to term_start first."""
    ctx = executed_lease(api, **kwargs)
    set_clock_date(api, ctx["lease"]["term_start"])
    ctx["lease"] = commence(api, ctx["lease"]["id"])
    ctx["building"] = _data(api.get_building(ctx["building"]["id"], PORTFOLIO_ADMIN))
    ctx["suite"] = _data(api.get_suite(ctx["suite"]["id"], PORTFOLIO_ADMIN))
    return ctx


def add_lease_on_new_suite(api, ctx: Dict[str, Any], tenant_overrides: Optional[Dict] = None,
                           suite_overrides: Optional[Dict] = None,
                           lease_overrides: Optional[Dict] = None) -> Dict[str, Any]:
    """Add a second tenant on its own suite inside an existing building."""
    overrides = dict(suite_overrides or {})
    overrides.setdefault("suite_number", f.next_suite_number())
    suite = register_suite(api, ctx["building"]["id"], **overrides)
    tenant = register_tenant(api, **(tenant_overrides or {}))
    lease = draft_lease(api, ctx["building"]["id"], suite["id"], tenant["id"],
                        **(lease_overrides or {}))
    return {"suite": suite, "tenant": tenant, "lease": lease}


def drive_to_active(api, lease: Dict[str, Any], tenant: Dict[str, Any],
                    advance_clock: bool = True) -> Dict[str, Any]:
    """Take an existing DRAFT lease all the way to ACTIVE."""
    lease_id = lease["id"]
    current = file_attestation(api, lease_id, "SIGNED_LEASE")
    if tenant.get("is_physician_owned"):
        qualified_appraisal_for(api, lease_id, current["version"])
    submit_for_review(api, lease_id)
    certify(api, lease_id)
    current = execute(api, lease_id)
    if advance_clock:
        set_clock_date(api, current["term_start"])
        current = commence(api, lease_id)
    return current


def master_and_sublease(api) -> Dict[str, Any]:
    """A MASTER lease driven to ACTIVE with a SUBLEASE drafted beneath it."""
    ctx = leasing_baseline(api, tenant_overrides={
        "legal_name": "Cedar Health System",
        "affiliation": "HEALTH_SYSTEM_ANCHOR",
        "primary_specialty": "ORTHOPEDICS",
    })
    master = draft_lease(api, ctx["building"]["id"], ctx["suite"]["id"], ctx["tenant"]["id"],
                        lease_type="MASTER")
    ctx["master"] = drive_to_active(api, master, ctx["tenant"])
    ctx["sub_tenant"] = register_tenant(api, legal_name="Cedar Orthopaedic Partners PC",
                                       primary_specialty="ORTHOPEDICS")
    ctx["sublease"] = draft_lease(api, ctx["building"]["id"], ctx["suite"]["id"],
                                  ctx["sub_tenant"]["id"], lease_type="SUBLEASE",
                                  master_lease_id=ctx["master"]["id"])
    return ctx


# --- Tenant-improvement ladders ------------------------------------------
def open_ti_project(api, lease_id: str, suite_id: str, **overrides) -> Dict[str, Any]:
    """Open a tenant-improvement project against the lease; starts in DESIGN."""
    payload = f.create_ti_project_payload(suite_id, **overrides)
    return _data(api.create_ti_project(lease_id, payload, LEASING_AGENT), 201)


def add_line_item(api, project_id: str, expected_ti_project_version: int,
                  **overrides) -> Dict[str, Any]:
    """Append one costed line item under project-level optimistic concurrency."""
    payload = f.create_ti_line_item_payload(expected_ti_project_version, **overrides)
    return _data(api.create_ti_line_item(project_id, payload, LEASING_AGENT), 201)


def ti_transition(api, project_id: str, action: str,
                  note: str = "Disposition") -> Dict[str, Any]:
    """Drive a project's leasing-side transition."""
    return _data(api.transition_ti_project(project_id, f.ti_transition_payload(action, note),
                                           LEASING_AGENT))


def ti_review(api, project_id: str, review_type: str, decision: str,
              **overrides) -> Dict[str, Any]:
    """Record one of the two independent engineering reviews."""
    payload = f.ti_review_payload(review_type, decision, **overrides)
    return _data(api.review_ti_project(project_id, payload, FACILITIES_ENGINEER))


def complete_ti(api, project_id: str,
                completion_note: str = "Close-out accepted") -> Dict[str, Any]:
    """Close out construction, CONSTRUCTION -> COMPLETE."""
    return _data(api.complete_ti_project(project_id, f.complete_ti_payload(completion_note),
                                         FACILITIES_ENGINEER))


def ti_project_in_review(api, lease_id: str, suite_id: str,
                         line_items: Optional[List[Dict]] = None,
                         **project_overrides) -> Dict[str, Any]:
    """A project with its scope appended and both review dimensions PENDING."""
    project = open_ti_project(api, lease_id, suite_id, **project_overrides)
    for line in (line_items or [{}]):
        project_read = _data(api.get_ti_project(project["id"], LEASING_AGENT))
        add_line_item(api, project["id"], project_read["version"], **line)
    return ti_transition(api, project["id"], "SUBMIT_REVIEWS")


def ti_project_permitted(api, lease_id: str, suite_id: str,
                         line_items: Optional[List[Dict]] = None,
                         lead_thickness_verified_mm: Optional[float] = None,
                         **project_overrides) -> Dict[str, Any]:
    """A project with both dimensions APPROVED, joined to PERMITTED."""
    project = ti_project_in_review(api, lease_id, suite_id, line_items, **project_overrides)
    shielding_extras: Dict[str, Any] = {}
    if lead_thickness_verified_mm is not None:
        shielding_extras["lead_thickness_verified_mm"] = lead_thickness_verified_mm
    ti_review(api, project["id"], "SHIELDING", "APPROVE", **shielding_extras)
    return ti_review(api, project["id"], "UTILITY", "APPROVE")


def ti_project_in_construction(api, lease_id: str, suite_id: str,
                               line_items: Optional[List[Dict]] = None,
                               lead_thickness_verified_mm: Optional[float] = None,
                               **project_overrides) -> Dict[str, Any]:
    """A permitted project moved PERMITTED -> CONSTRUCTION."""
    project = ti_project_permitted(api, lease_id, suite_id, line_items,
                                   lead_thickness_verified_mm, **project_overrides)
    return ti_transition(api, project["id"], "START_CONSTRUCTION")


# --- Billing and arrears ladders -----------------------------------------
def issue_invoice(api, lease_id: str, period_start: str, period_end: str,
                  due_date: str) -> Dict[str, Any]:
    """Issue one monthly occupancy invoice against the lease."""
    payload = f.create_rent_invoice_payload(period_start, period_end, due_date)
    return _data(api.create_rent_invoice(lease_id, payload, PROPERTY_MANAGER), 201)


def pay_invoice(api, invoice_id: str, payment_amount: float) -> Dict[str, Any]:
    """Record a payment that settles the invoice balance exactly."""
    return _data(api.pay_rent_invoice(invoice_id, f.payment_payload(payment_amount),
                                      PROPERTY_MANAGER))


def write_off_invoice(api, invoice_id: str,
                      justification: str = "Uncollectable arrears",
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Write off a delinquent invoice as a ComplianceOfficer."""
    return _data(api.write_off_rent_invoice(invoice_id, f.write_off_payload(justification),
                                            headers or SECOND_COMPLIANCE_OFFICER))


def flag_delinquent(api, lease_id: str, flag_date: str) -> Dict[str, Any]:
    """Advance the clock to flag_date and run one close so arrears are flagged."""
    set_clock_date(api, flag_date)
    run_daily_close(api)
    rows, _meta = _paginated(api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    return rows[-1]


def _paginated(response):
    return validate_paginated(response)


# --- Compliance cases -----------------------------------------------------
def open_case(api, tenant_id: str, headers: Optional[Dict[str, str]] = None,
              **overrides) -> Dict[str, Any]:
    """Open a compliance case by hand, choosing the scoring variant."""
    payload = f.create_compliance_case_payload(tenant_id, **overrides)
    return _data(api.create_compliance_case(payload, headers or COMPLIANCE_OFFICER), 201)


def transition_case(api, case_id: str, action: str,
                    headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    """Drive a case disposition: plan remediation, cure, or report."""
    payload = f.case_transition_payload(action, **overrides)
    return _data(api.transition_compliance_case(case_id, payload,
                                                headers or COMPLIANCE_OFFICER))


# --- Shared space bookings -----------------------------------------------
def book(api, shared_space_id: str, lease_id: str, window_start: str, window_end: str,
         occupant_count: int, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Book a window in a shared clinical space."""
    payload = f.create_booking_payload(shared_space_id, lease_id, window_start, window_end,
                                       occupant_count)
    return _data(api.create_booking(payload, headers or LEASING_AGENT), 201)


def cancel_booking(api, booking_id: str, headers: Optional[Dict[str, str]] = None,
                   note: str = "Cancelled by request") -> Dict[str, Any]:
    """Cancel a future booking, freeing its seats."""
    return _data(api.cancel_booking(booking_id, f.cancel_booking_payload(note),
                                    headers or LEASING_AGENT))


def bookable_lease(api, space_overrides: Optional[Dict] = None,
                   **lease_kwargs) -> Dict[str, Any]:
    """An ACTIVE lease with a shared space and its space-sharing schedule on file."""
    ctx = active_lease(api, **lease_kwargs)
    ctx["shared_space"] = register_shared_space(api, ctx["building"]["id"],
                                               **(space_overrides or {}))
    ctx["lease"] = file_attestation(api, ctx["lease"]["id"], "SPACE_SHARING_SCHEDULE")
    return ctx


# --- Parking pool --------------------------------------------------------
def allocate_stalls(api, building_id: str, lease_id: str, category: str, stall_count: int,
                    expected_building_version: Optional[int] = None) -> Dict[str, Any]:
    """Allocate stalls from the building pool under building-level concurrency."""
    if expected_building_version is None:
        expected_building_version = _data(
            api.get_building(building_id, PROPERTY_MANAGER))["version"]
    payload = f.create_parking_allocation_payload(expected_building_version, building_id,
                                                  lease_id, category, stall_count)
    return _data(api.create_parking_allocation(payload, PROPERTY_MANAGER), 201)


def revoke_allocation(api, allocation_id: str,
                      note: str = "Stalls returned") -> Dict[str, Any]:
    """Return an allocation's stalls to the pool."""
    return _data(api.revoke_parking_allocation(allocation_id,
                                               f.revoke_allocation_payload(note),
                                               PROPERTY_MANAGER))


# --- Convenience readers -------------------------------------------------
def read_lease(api, lease_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return _data(api.get_lease(lease_id, headers or LEASING_AGENT))


def read_building(api, building_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return _data(api.get_building(building_id, headers or PORTFOLIO_ADMIN))


def read_suite(api, suite_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return _data(api.get_suite(suite_id, headers or PORTFOLIO_ADMIN))


def read_tenant(api, tenant_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return _data(api.get_tenant(tenant_id, headers or PORTFOLIO_ADMIN))


def read_project(api, project_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return _data(api.get_ti_project(project_id, headers or LEASING_AGENT))
