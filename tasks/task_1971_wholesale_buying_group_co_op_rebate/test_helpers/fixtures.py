"""Composite setup helpers for the co-op rebate domain.

The test harness restarts the API server before every test, so every helper
builds its preconditions from scratch against an empty database, using only
PRD-declared endpoints. Setup calls are unwrapped with the lenient
get_success_data() validator so a setup failure surfaces as a clear
"Setup step failed" error.

Quarter cadence note (PRD §3.6): a QuarterlyDistribution "arrives in `DRAFT`
status with `quarter_index` set to the co-op's current quarter", and
calculation "aggregates every `RebateAccrual` in `FINALIZED` status whose
`quarter_index` equals the distribution's quarter". The distribution for a
quarter must therefore be created while that quarter is still current —
i.e. BEFORE close_quarter finalizes the quarter's accruals.

Identity threading (PRD §2.1): MemberRep calls pass the owning Member's id
as X-User-ID; SupplierRep calls pass the owning Supplier's id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_coop_payload,
    create_member_payload,
    create_supplier_payload,
    create_supplier_program_payload,
    create_enrollment_payload,
    create_purchase_report_payload,
    create_volume_audit_payload,
    resolve_audit_payload,
    calculate_distribution_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_rep_headers,
    make_supplier_rep_headers,
)

ADMIN = TEST_USERS["coop_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
AUDITOR = TEST_USERS["program_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — basic creators and state progression
# ---------------------------------------------------------------------------

def bootstrap_coop(name="TestCoop"):
    """One-time bootstrap; returns the Coop singleton with zeroed counters."""
    resp = api_client.bootstrap(create_coop_payload(name=name), ADMIN)
    return get_success_data(resp)


def get_coop():
    return get_success_data(api_client.get_coop(ADMIN))


def current_quarter() -> int:
    return get_coop()["current_quarter_index"]


def close_quarter():
    """Close the current quarter (PRD §3.6); returns the updated Coop."""
    return get_success_data(api_client.close_quarter(ADMIN))


def create_pending_member(legal_name="Member Co", commitment_level="STANDARD"):
    """Create a member; it begins life in PENDING status (PRD §3.2)."""
    resp = api_client.create_member(
        create_member_payload(legal_name=legal_name, commitment_level=commitment_level),
        ADMIN,
    )
    return get_success_data(resp)


def create_active_member(legal_name="Member Co", commitment_level="STANDARD"):
    """Create a member and activate it (PENDING -> ACTIVE, PRD §3.2)."""
    member = create_pending_member(legal_name, commitment_level)
    return get_success_data(api_client.activate_member(member["id"], ADMIN))


def create_supplier(legal_name="Supplier Co", **overrides):
    """Create a supplier; it starts as PROSPECT (PRD §3.3)."""
    resp = api_client.create_supplier(
        create_supplier_payload(legal_name=legal_name, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_onboarded_supplier(legal_name="Supplier Co", **overrides):
    """Create a supplier and onboard it (PROSPECT -> ONBOARDED, PRD §3.3)."""
    supplier = create_supplier(legal_name, **overrides)
    return get_success_data(api_client.onboard_supplier(supplier["id"], ADMIN))


def create_draft_program(supplier, **overrides):
    """Create a program beneath its supplier as that supplier's SupplierRep;
    the program is born in DRAFT with negotiation_round 0 (PRD §3.3)."""
    resp = api_client.create_supplier_program(
        supplier["id"],
        create_supplier_program_payload(**overrides),
        make_supplier_rep_headers(supplier["id"]),
    )
    return get_success_data(resp)


def create_open_program(supplier, **overrides):
    """Create a program and open it (DRAFT -> OPEN, PRD §3.3). Requires the
    supplier to be ONBOARDED at open time."""
    program = create_draft_program(supplier, **overrides)
    return open_program(supplier, program)


def open_program(supplier, program):
    return get_success_data(
        api_client.open_program(program["id"], make_supplier_rep_headers(supplier["id"]))
    )


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def enroll_member(member, program):
    """Enroll an ACTIVE member in an OPEN/REOPENED program (PRD §3.4)."""
    resp = api_client.create_enrollment(
        create_enrollment_payload(member["id"], program["id"]), ADMIN
    )
    return get_success_data(resp)


def setup_member_with_open_program(
    commitment_level="STANDARD",
    holdback_policy="FLAT",
    tier_schedule=None,
    exclusivity_required=False,
    exclusivity_threshold_pct=0,
    program_code="PROG-1",
):
    """Bootstrap + ACTIVE member + ONBOARDED supplier + OPEN program +
    ACTIVE enrollment. Returns dict with member, supplier, program,
    enrollment. Quarter is 0 at return."""
    bootstrap_coop()
    member = create_active_member(commitment_level=commitment_level)
    supplier = create_onboarded_supplier()
    program_kwargs = {
        "program_code": program_code,
        "exclusivity_required": exclusivity_required,
        "exclusivity_threshold_pct": exclusivity_threshold_pct,
        "holdback_policy": holdback_policy,
    }
    if tier_schedule is not None:
        program_kwargs["tier_schedule"] = tier_schedule
    program = create_open_program(supplier, **program_kwargs)
    enrollment = enroll_member(member, program)
    return {
        "member": member,
        "supplier": supplier,
        "program": program,
        "enrollment": enrollment,
    }


def submit_report(enrollment, member, quarter_index, qty, cents):
    """Submit a purchase report as the member's own MemberRep (PRD §3.4);
    the accrual for (enrollment, quarter) is found-or-created and the
    provisional rebate recomputed from the self-reported figures."""
    resp = api_client.submit_purchase_report(
        enrollment["id"],
        create_purchase_report_payload(
            quarter_index=quarter_index, self_report_qty=qty, self_report_cents=cents
        ),
        make_member_rep_headers(member["id"]),
    )
    return get_success_data(resp)


def get_accrual_for_enrollment(enrollment_id):
    """Fetch the (single) RebateAccrual for an enrollment via the list
    endpoint filtered by enrollment_id (PRD §3.6)."""
    resp = api_client.list_rebate_accruals(ADMIN, params={"enrollment_id": enrollment_id})
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1, f"Expected an accrual for enrollment {enrollment_id}"
    return data[0]


def list_clawbacks_for_member(member_id):
    resp = api_client.list_clawback_cases(ADMIN, params={"member_id": member_id})
    data, _meta = validate_paginated(resp)
    return data


def list_holdback_releases_for_member(member_id):
    resp = api_client.list_holdback_releases(ADMIN, params={"member_id": member_id})
    data, _meta = validate_paginated(resp)
    return data


# ---------------------------------------------------------------------------
# Tier 3 — distribution lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_distribution_for_current_quarter():
    """Create the DRAFT QuarterlyDistribution for the current quarter
    (PRD §3.6). Must be called while the target quarter is still current
    (before close_quarter)."""
    return get_success_data(api_client.create_distribution(FINANCE))


def calculate_distribution(distribution):
    """OCC-guarded calculation (PRD §2.8): expected_distribution_version must
    equal the distribution's current version."""
    resp = api_client.calculate_distribution(
        distribution["id"],
        calculate_distribution_payload(distribution["version"]),
        FINANCE,
    )
    return get_success_data(resp)


def approve_distribution(distribution_id):
    return get_success_data(api_client.approve_distribution(distribution_id, FINANCE))


def disburse_distribution(distribution_id):
    return get_success_data(api_client.disburse_distribution(distribution_id, FINANCE))


def setup_report_with_distribution(
    qty=120,
    cents=200000,
    commitment_level="STANDARD",
    holdback_policy="FLAT",
    tier_schedule=None,
    program_code="PROG-1",
):
    """Full in-quarter setup: ACTIVE member + OPEN program + ACTIVE
    enrollment + one purchase report for the current quarter (0) + a DRAFT
    distribution created for quarter 0 (before the close, per the quarter
    cadence note above). Returns the scenario dict."""
    scenario = setup_member_with_open_program(
        commitment_level=commitment_level,
        holdback_policy=holdback_policy,
        tier_schedule=tier_schedule,
        program_code=program_code,
    )
    report = submit_report(scenario["enrollment"], scenario["member"], 0, qty, cents)
    distribution = create_distribution_for_current_quarter()
    scenario["report"] = report
    scenario["distribution"] = distribution
    return scenario


def setup_finalized_accrual_scenario(**kwargs):
    """setup_report_with_distribution + close_quarter: the quarter-0 accrual
    is FINALIZED and the distribution (quarter_index 0) is ready to
    calculate. Returns the scenario dict."""
    scenario = setup_report_with_distribution(**kwargs)
    close_quarter()
    return scenario


def setup_calculated_distribution(**kwargs):
    """Finalized accrual + calculated distribution (DRAFT -> CALCULATED)."""
    scenario = setup_finalized_accrual_scenario(**kwargs)
    scenario["distribution"] = calculate_distribution(scenario["distribution"])
    return scenario


def setup_disbursed_scenario(**kwargs):
    """Full lifecycle through DISBURSED: calculate -> approve -> disburse.
    Included accruals are DISTRIBUTED, a HoldbackRelease is SCHEDULED for the
    withheld amount, and member lifetime_pass_through_cents is credited
    (PRD §3.6). Returns the scenario dict with refreshed entities."""
    scenario = setup_calculated_distribution(**kwargs)
    approve_distribution(scenario["distribution"]["id"])
    scenario["distribution"] = disburse_distribution(scenario["distribution"]["id"])
    scenario["accrual"] = get_accrual_for_enrollment(scenario["enrollment"]["id"])
    scenario["member"] = get_success_data(
        api_client.get_member(scenario["member"]["id"], ADMIN)
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — audits and findings
# ---------------------------------------------------------------------------

def open_audit_on_report(report):
    """Open a VolumeAudit against a SUBMITTED report (PRD §3.5); born OPEN."""
    resp = api_client.create_volume_audit(
        create_volume_audit_payload(report["id"]), AUDITOR
    )
    return get_success_data(resp)


def drive_audit_to_accepted(audit, member):
    """OPEN -> FIELDWORK -> FINDINGS_ISSUED -> ACCEPTED (PRD §3.5). The
    accept step is performed by the member's own MemberRep."""
    audit = get_success_data(api_client.begin_fieldwork(audit["id"], AUDITOR))
    audit = get_success_data(api_client.issue_findings(audit["id"], AUDITOR))
    audit = get_success_data(
        api_client.accept_findings(audit["id"], make_member_rep_headers(member["id"]))
    )
    return audit


def resolve_audit(audit, audited_qty, audited_cents):
    """Resolve an ACCEPTED audit with attested figures (PRD §3.5)."""
    resp = api_client.resolve_audit(
        audit["id"], resolve_audit_payload(audited_qty, audited_cents), AUDITOR
    )
    return get_success_data(resp)


def open_accepted_audit(report, member):
    """Open an audit on the report and drive it to ACCEPTED."""
    return drive_audit_to_accepted(open_audit_on_report(report), member)


def drive_member_to_material_findings(member, program, enrollment, target_count=2):
    """Drive a member's prior_audit_findings_count to `target_count` by
    running one MATERIAL audit per quarter (PRD §3.5: "when the finding is
    `MATERIAL`, the member's `prior_audit_findings_count` increments by one").

    Each round: submit a report for the current quarter, audit it, resolve
    with audited_cents far enough below self_report_cents that the
    discrepancy ratio exceeds five percent (MATERIAL), then close the
    quarter. The accruals are never distributed, so no AUDIT_SHORTFALL
    clawback is created. Returns the refreshed member.
    """
    for _ in range(target_count):
        quarter = current_quarter()
        report = submit_report(enrollment, member, quarter, 120, 200000)
        audit = open_accepted_audit(report, member)
        # |100000 - 200000| / 200000 = 0.5 > 0.05 -> MATERIAL (PRD §3.5)
        resolve_audit(audit, audited_qty=60, audited_cents=100000)
        close_quarter()
    return get_success_data(api_client.get_member(member["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 5 — terminal states: churn and clawback resolution
# ---------------------------------------------------------------------------

def churn_member(member_id):
    """Churn an ACTIVE or SUSPENDED member (PRD §3.2): enrollments EXIT,
    scheduled holdbacks FORFEIT, and a CHURN clawback case is auto-created."""
    return get_success_data(api_client.churn_member(member_id, ADMIN))


def get_single_clawback_for_member(member_id):
    cases = list_clawbacks_for_member(member_id)
    assert len(cases) == 1, f"Expected exactly one clawback case, got {len(cases)}"
    return cases[0]


def notify_and_resolve_clawback(case_id):
    """OPEN -> NOTIFIED -> RESOLVED (PRD §3.7); recovered_cents is set to
    net_clawback_cents and added back into the pool."""
    get_success_data(api_client.notify_clawback(case_id, ADMIN))
    return get_success_data(api_client.resolve_clawback(case_id, ADMIN))
