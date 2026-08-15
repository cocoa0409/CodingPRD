"""
Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so the database
starts empty). Setup calls use get_success_data() so failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assignment_payload,
    create_certificate_payload,
    create_employee_payload,
    create_engagement_payload,
    create_extension_payload,
    create_package_payload,
    create_policy_payload,
    create_projection_payload,
    create_program_payload,
    create_record_payload,
    create_settlement_payload,
    create_split_payload,
    mark_filed_payload,
    mark_issued_payload,
)
from .test_users import TEST_USERS, make_assignee_headers

ADMIN = TEST_USERS["admin_headers"]
BU = TEST_USERS["bu_approver_headers"]
MOBILITY_APPROVER = TEST_USERS["mobility_approver_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
FINANCE = TEST_USERS["finance_headers"]
COORDINATOR = TEST_USERS["vendor_coordinator_headers"]
VENDOR = TEST_USERS["tax_vendor_headers"]


# ─── Tier 1: single-resource creation ─────────────────

def create_program(**overrides):
    return get_success_data(api_client.create_program(create_program_payload(**overrides), ADMIN))


def create_employee(**overrides):
    return get_success_data(api_client.create_employee(create_employee_payload(**overrides), ADMIN))


def create_policy(**overrides):
    return get_success_data(api_client.create_policy(create_policy_payload(**overrides), ADMIN))


def create_draft_assignment(program_id, employee_id, policy_id, **overrides):
    """Create an assignment; it starts in DRAFT (PRD §3.2)."""
    return get_success_data(api_client.create_assignment(
        create_assignment_payload(program_id, employee_id, policy_id, **overrides), ADMIN))


def create_draft_record(assignment_id, **overrides):
    return get_success_data(api_client.create_record(create_record_payload(assignment_id, **overrides), PAYROLL))


def create_and_post_record(assignment_id, **overrides):
    record = create_draft_record(assignment_id, **overrides)
    return get_success_data(api_client.post_record(record["id"], PAYROLL))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN))


def get_assignment_version(assignment_id):
    return get_assignment(assignment_id)["version"]


def list_chargebacks(assignment_id, **extra_params):
    params = {"assignment_id": assignment_id}
    params.update(extra_params)
    return get_success_data(api_client.list_chargebacks(ADMIN, params=params))


# ─── Tier 2: package / split / certificate builders ───

def add_package(assignment_id, state="approved", **overrides):
    """Create the compensation package and walk it to `state`
    ('draft' | 'submitted' | 'approved'). Approval is by a MobilityApprover
    whose id differs from the creator's (segregation of duties, PRD §2.8)."""
    package = get_success_data(api_client.create_package(
        create_package_payload(assignment_id, **overrides), PAYROLL))
    if state in ("submitted", "approved"):
        package = get_success_data(api_client.submit_package(package["id"], PAYROLL))
    if state == "approved":
        package = get_success_data(api_client.approve_package(package["id"], MOBILITY_APPROVER))
    return package


def add_split(assignment_id, state="active", home_pct=60, host_pct=40):
    """Create the payroll split and optionally activate it (PRD §3.2)."""
    split = get_success_data(api_client.create_split(
        create_split_payload(assignment_id, home_payroll_pct=home_pct, host_payroll_pct=host_pct),
        PAYROLL))
    if state == "active":
        split = get_success_data(api_client.activate_split(split["id"], PAYROLL))
    return split


def add_certificate(assignment_id, state="issued",
                    valid_from="2026-09-01", valid_until="2027-08-31",
                    application_ref="COC-1"):
    """Create a certificate of coverage and walk it to `state`
    ('requested' | 'submitted' | 'issued'). Issuance flips the split's
    coc_exempt flag to true (PRD §3.5)."""
    cert = get_success_data(api_client.create_certificate(
        create_certificate_payload(assignment_id, application_ref=application_ref), COORDINATOR))
    if state in ("submitted", "issued"):
        cert = get_success_data(api_client.submit_certificate(cert["id"], COORDINATOR))
    if state == "issued":
        cert = get_success_data(api_client.mark_issued(
            cert["id"], mark_issued_payload(valid_from, valid_until), COORDINATOR))
    return cert


# ─── Tier 3: full assignment activation ───────────────

def activate_assignment(assignment_id):
    """Walk the dual approval DRAFT -> PENDING_BU_APPROVAL ->
    PENDING_MOBILITY_APPROVAL -> ACTIVE (PRD §3.2)."""
    get_success_data(api_client.submit_assignment(assignment_id, ADMIN))
    get_success_data(api_client.approve_bu(assignment_id, BU))
    return get_success_data(api_client.approve_mobility(assignment_id, MOBILITY_APPROVER))


def setup_active_assignment(
    *,
    totalization=False,
    coc_valid_from="2026-09-01",
    coc_valid_until="2027-08-31",
    program_overrides=None,
    policy_overrides=None,
    employee_overrides=None,
    assignment_overrides=None,
    package_state="approved",
    split_state="active",
    home_pct=60,
    host_pct=40,
):
    """Program + employee + policy + assignment walked to ACTIVE, with the
    compensation package and payroll split in the requested states and (when
    totalization applies) an ISSUED certificate of coverage.

    Returns a ctx dict with all created resources.
    """
    program = create_program(**(program_overrides or {}))
    employee = create_employee(**(employee_overrides or {}))
    policy = create_policy(**(policy_overrides or {}))
    asg_overrides = {"totalization_applies": totalization}
    asg_overrides.update(assignment_overrides or {})
    assignment = create_draft_assignment(program["id"], employee["id"], policy["id"], **asg_overrides)

    package = split = certificate = None
    if package_state is not None:
        package = add_package(assignment["id"], state=package_state)
    if split_state is not None:
        split = add_split(assignment["id"], state=split_state, home_pct=home_pct, host_pct=host_pct)
    if totalization:
        certificate = add_certificate(
            assignment["id"], state="issued",
            valid_from=coc_valid_from, valid_until=coc_valid_until)

    assignment = activate_assignment(assignment["id"])
    return {
        "program": program,
        "employee": employee,
        "policy": policy,
        "assignment": assignment,
        "package": package,
        "split": split,
        "certificate": certificate,
    }


# ─── Tier 4: vendor engagement / settlement lifecycles ─

def create_engagement(assignment_id, **overrides):
    """Create a vendor engagement; it starts ENGAGED (PRD §3.4)."""
    return get_success_data(api_client.create_engagement(
        create_engagement_payload(assignment_id, **overrides), COORDINATOR))


def advance_engagement_to_under_review(engagement_id):
    """ENGAGED -> DATA_SENT -> DRAFT_RETURNED -> UNDER_REVIEW (PRD §3.4)."""
    get_success_data(api_client.send_data(engagement_id, COORDINATOR))
    get_success_data(api_client.return_draft(engagement_id, VENDOR))
    return get_success_data(api_client.start_review(engagement_id, COORDINATOR))


def setup_filed_engagement(assignment_id, tax_year=2026,
                           filed_total_gross_cents=1500000,
                           filed_home_tax_cents=130000):
    """Engage a vendor and drive the engagement to FILED, recording the filed
    totals; filing unlocks settlement creation (PRD §3.4)."""
    engagement = create_engagement(assignment_id, tax_year=tax_year)
    advance_engagement_to_under_review(engagement["id"])
    get_success_data(api_client.accept_engagement(engagement["id"], COORDINATOR))
    return get_success_data(api_client.mark_filed(
        engagement["id"],
        mark_filed_payload(filed_total_gross_cents, filed_home_tax_cents),
        COORDINATOR))


def create_calculated_settlement(assignment_id, tax_year=2026, creator=PAYROLL):
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(assignment_id, tax_year=tax_year), creator))


def setup_calculated_settlement(
    *,
    filed_total_gross_cents=1500000,
    filed_home_tax_cents=130000,
    record_overrides=None,
    num_posted_records=1,
    totalization=True,
    coc_valid_from="2026-09-01",
    coc_valid_until="2027-08-31",
    program_overrides=None,
):
    """Activated assignment + POSTED September record(s) + FILED vendor
    engagement + settlement computed into CALCULATED (PRD §3.8).

    Returns ctx dict including 'records', 'engagement', 'settlement'.
    """
    ctx = setup_active_assignment(
        totalization=totalization,
        coc_valid_from=coc_valid_from,
        coc_valid_until=coc_valid_until,
        program_overrides=program_overrides,
    )
    asg_id = ctx["assignment"]["id"]
    records = []
    base = {"tax_year": 2026, "period_month": 9, "total_gross_cents": 900000,
            "per_diem_days": 20, "housing_receipts_cents": 310000}
    for i in range(num_posted_records):
        ov = dict(base)
        ov.update(record_overrides or {})
        ov["period_month"] = 9 + i
        records.append(create_and_post_record(asg_id, **ov))
    engagement = setup_filed_engagement(
        asg_id, filed_total_gross_cents=filed_total_gross_cents,
        filed_home_tax_cents=filed_home_tax_cents)
    settlement = create_calculated_settlement(asg_id)
    ctx.update({"records": records, "engagement": engagement, "settlement": settlement})
    return ctx


def setup_pending_review_settlement(**kwargs):
    """setup_calculated_settlement + submit -> PENDING_REVIEW (PRD §3.8)."""
    ctx = setup_calculated_settlement(**kwargs)
    settlement = get_success_data(api_client.submit_settlement(ctx["settlement"]["id"], PAYROLL))
    ctx["settlement"] = settlement
    return ctx


def create_pending_extension(assignment_id, requested_new_end_date):
    """Create an extension request (PENDING) with a freshly captured OCC
    version (PRD §3.7). Returns the extension request."""
    version = get_assignment_version(assignment_id)
    return get_success_data(api_client.create_extension(
        create_extension_payload(assignment_id, requested_new_end_date, version), ADMIN))


def create_current_projection(assignment_id, creator=FINANCE):
    """Create a cost projection (CURRENT) with a freshly captured OCC version
    (PRD §3.6)."""
    version = get_assignment_version(assignment_id)
    return get_success_data(api_client.create_projection(
        create_projection_payload(assignment_id, version), creator))
