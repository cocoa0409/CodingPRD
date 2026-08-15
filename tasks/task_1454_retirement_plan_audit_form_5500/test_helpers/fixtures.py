"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh server
(the harness restarts the API before every test) using only PRD-declared
endpoints. Setup calls use get_success_data() so a broken precondition fails
loudly with the server's error id instead of a confusing assert.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    bulk_import_payload,
    create_contribution_payload,
    create_corrective_action_payload,
    create_engagement_payload,
    create_filing_extension_payload,
    create_filing_payload,
    create_finding_payload,
    create_participant_payload,
    create_schedule_entry_payload,
    create_service_provider_fee_payload,
    create_trust_statement_payload,
)
from .test_users import AUDITOR, MANAGER, SPONSOR, SYSTEM, TPA


# ---------------------------------------------------------------------------
# Tier 1: engagement creation and state progression
# ---------------------------------------------------------------------------

def create_engagement(**overrides) -> dict:
    """Create an engagement (DRAFT, posture ON_TRACK). Returns the engagement."""
    return get_success_data(api_client.create_engagement(
        create_engagement_payload(**overrides), SPONSOR))


def add_participant(engagement_id: str, external_ref: str = "P-001", **overrides) -> dict:
    return get_success_data(api_client.create_participant(
        create_participant_payload(engagement_id, external_ref, **overrides), SPONSOR))


def bulk_import(engagement_id: str, count: int, prefix: str, **template_overrides) -> list:
    return get_success_data(api_client.bulk_import_participants(
        bulk_import_payload(engagement_id, count, prefix, **template_overrides), SPONSOR))


def recompute_count(engagement_id: str) -> dict:
    """Run the participant-count recomputation; returns the engagement."""
    return get_success_data(api_client.recompute_participant_count(engagement_id, TPA))


def create_small_plan_engagement(plan_number=None, participant_opening_balance=0,
                                 **engagement_overrides) -> tuple:
    """Engagement + one ACTIVE eligible participant + count recomputed.

    A single counted participant keeps the plan small (Schedule I, 7-business-day
    remittance standard). Returns (engagement, participant).
    """
    if plan_number is not None:
        engagement_overrides["plan_number"] = plan_number
    eng = create_engagement(**engagement_overrides)
    participant = add_participant(
        eng["id"], "P-001", opening_balance_cents=participant_opening_balance)
    eng = recompute_count(eng["id"])
    return eng, participant


def walk_to_report_issued(engagement_id: str) -> dict:
    """DRAFT -> DATA_COLLECTION -> TESTING -> FIELDWORK -> REPORT_ISSUED.

    Requires the participant count to have been computed first.
    """
    get_success_data(api_client.activate_engagement(engagement_id, SPONSOR))
    get_success_data(api_client.begin_testing(engagement_id, TPA))
    get_success_data(api_client.begin_fieldwork(engagement_id, AUDITOR))
    return get_success_data(api_client.issue_report(engagement_id, AUDITOR))


def create_engagement_in_report_issued(plan_number=None, **overrides) -> tuple:
    """Small-plan engagement walked all the way to REPORT_ISSUED.

    Returns (engagement, participant).
    """
    eng, participant = create_small_plan_engagement(plan_number, **overrides)
    eng = walk_to_report_issued(eng["id"])
    return eng, participant


# ---------------------------------------------------------------------------
# Tier 2: filing assembly
# ---------------------------------------------------------------------------

def create_filing(engagement_id: str) -> dict:
    """Create the engagement's Form 5500 filing (DRAFT)."""
    return get_success_data(api_client.create_filing(
        create_filing_payload(engagement_id), TPA))


def add_verified_schedule_entry(filing_id: str, schedule_type: str = "I",
                                line_item: str = "I-1 total assets",
                                amount_cents: int = 0, **overrides) -> dict:
    """Add a schedule line and have the auditor verify it."""
    entry = get_success_data(api_client.create_schedule_entry(
        create_schedule_entry_payload(
            filing_id, schedule_type=schedule_type, line_item=line_item,
            amount_cents=amount_cents, **overrides),
        TPA))
    return get_success_data(api_client.verify_schedule_entry(entry["id"], AUDITOR))


def create_filing_ready_to_file(engagement_id: str, schedule_type: str = "I") -> dict:
    """Filing with one verified entry of the engagement's required schedule type,
    moved DRAFT -> SCHEDULES_COMPLETE -> READY_TO_FILE.

    The filing creator is the TPA lane operator and the readiness marker is the
    manager lane operator, so the segregation-of-duties check passes.
    Returns the READY_TO_FILE filing.
    """
    filing = create_filing(engagement_id)
    add_verified_schedule_entry(filing["id"], schedule_type=schedule_type)
    get_success_data(api_client.mark_schedules_complete(filing["id"], TPA))
    return get_success_data(api_client.mark_ready(filing["id"], MANAGER))


def create_accepted_filing(engagement_id: str, schedule_type: str = "I",
                           submit_clock: str = "2026-07-15T00:00:00Z") -> dict:
    """READY_TO_FILE filing submitted before its due date and recorded ACCEPTED."""
    filing = create_filing_ready_to_file(engagement_id, schedule_type)
    get_success_data(api_client.set_clock(submit_clock, SYSTEM))
    get_success_data(api_client.submit_filing(filing["id"], {}, MANAGER))
    return get_success_data(api_client.record_disposition(
        filing["id"], {"outcome": "ACCEPTED"}, SYSTEM))


# ---------------------------------------------------------------------------
# Tier 3: late-deposit assessments and findings
# ---------------------------------------------------------------------------

def create_late_assessment(engagement_id: str, participant_id: str,
                           payroll_date: str = "2025-06-16",
                           deposit_date: str = "2025-06-30",
                           amount_cents: int = 100_000,
                           contribution_type: str = "ELECTIVE_DEFERRAL",
                           scan_as=None) -> tuple:
    """Record a contribution and run the late-deposit scan.

    Returns (contribution, assessment) where assessment is the freshly created
    LateContributionAssessment (ASSESSED) for a late contribution, or None when
    the deposit was timely.
    """
    contribution = get_success_data(api_client.create_contribution(
        create_contribution_payload(
            engagement_id, participant_id, type=contribution_type,
            payroll_date=payroll_date, deposit_date=deposit_date,
            amount_cents=amount_cents),
        SPONSOR))
    get_success_data(api_client.late_deposit_scan(engagement_id, scan_as or TPA))
    assessments, _meta = _list_assessments(engagement_id)
    assessment = next(
        (a for a in assessments if a["contribution_id"] == contribution["id"]), None)
    return contribution, assessment


def _list_assessments(engagement_id: str) -> tuple:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_late_contribution_assessments(
        SPONSOR, params={"engagement_id": engagement_id})
    return validate_paginated(resp)


def get_single_assessment(engagement_id: str) -> dict:
    assessments, meta = _list_assessments(engagement_id)
    assert len(assessments) == 1, f"expected exactly 1 assessment, got {len(assessments)}"
    return assessments[0]


def confirm_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.confirm_late_contribution_assessment(
        assessment_id, AUDITOR))


def get_single_finding(engagement_id: str, category: str = None) -> dict:
    """Fetch the single finding of the engagement (fresh-DB tests only)."""
    from prd_bench_local_runner.testing import validate_paginated
    params = {"engagement_id": engagement_id}
    if category:
        params["category"] = category
    findings, _meta = validate_paginated(api_client.list_findings(SPONSOR, params=params))
    assert len(findings) == 1, f"expected exactly 1 finding, got {len(findings)}"
    return findings[0]


def create_manual_finding(engagement_id: str, **overrides) -> dict:
    """PlanAuditor-created manual finding (starts OPEN)."""
    return get_success_data(api_client.create_finding(
        create_finding_payload(engagement_id, **overrides), AUDITOR))


def acknowledge_finding(finding_id: str) -> dict:
    return get_success_data(api_client.acknowledge_finding(finding_id, SPONSOR))


def setup_confirmed_late_deposit(plan_number=None, payroll_date="2025-06-16",
                                 deposit_date="2025-06-30", amount_cents=100_000,
                                 participant_opening_balance=0) -> dict:
    """Full late-deposit chain up to an acknowledged auto-created finding.

    Returns dict with keys: engagement, participant, contribution, assessment,
    finding. The assessment is CONFIRMED; the finding (LATE_REMITTANCE, source
    LATE_DEPOSIT_AUTO) is ACKNOWLEDGED.
    """
    eng, participant = create_small_plan_engagement(
        plan_number, participant_opening_balance=participant_opening_balance)
    contribution, assessment = create_late_assessment(
        eng["id"], participant["id"], payroll_date=payroll_date,
        deposit_date=deposit_date, amount_cents=amount_cents)
    assert assessment is not None, "expected the contribution to be classified LATE"
    confirm_assessment(assessment["id"])
    finding = get_single_finding(eng["id"], category="LATE_REMITTANCE")
    acknowledge_finding(finding["id"])
    return {
        "engagement": get_success_data(api_client.get_engagement(eng["id"], SPONSOR)),
        "participant": participant,
        "contribution": contribution,
        "assessment": assessment,
        "finding": finding,
    }


# ---------------------------------------------------------------------------
# Tier 4: corrective actions
# ---------------------------------------------------------------------------

def propose_action(engagement_id: str, finding_id: str, **overrides) -> dict:
    """SponsorAdmin proposes a corrective action (PROPOSED).

    The proposer is always the canonical sponsor-lane operator so the manager
    lane can approve without tripping the segregation-of-duties check.
    """
    return get_success_data(api_client.create_corrective_action(
        create_corrective_action_payload(engagement_id, finding_id, **overrides), SPONSOR))


def approve_action(action_id: str) -> dict:
    return get_success_data(api_client.approve_corrective_action(action_id, MANAGER))


def execute_action(action_id: str) -> dict:
    return get_success_data(api_client.execute_corrective_action(action_id, SPONSOR))


def propose_approved_action(engagement_id: str, finding_id: str, **overrides) -> dict:
    """Propose + approve. Returns the APPROVED action."""
    action = propose_action(engagement_id, finding_id, **overrides)
    return approve_action(action["id"])


def setup_acknowledged_finding(plan_number=None, severity="MEDIUM",
                               category="NONDISCRIMINATION_FAILURE",
                               description="manual finding",
                               participant_opening_balance=0) -> dict:
    """Engagement with a participant and an ACKNOWLEDGED manual finding.

    Returns dict with keys: engagement, participant, finding.
    """
    eng, participant = create_small_plan_engagement(
        plan_number, participant_opening_balance=participant_opening_balance)
    finding = create_manual_finding(
        eng["id"], category=category, severity=severity, description=description)
    acknowledge_finding(finding["id"])
    return {
        "engagement": get_success_data(api_client.get_engagement(eng["id"], SPONSOR)),
        "participant": participant,
        "finding": finding,
    }


def setup_executed_action(plan_number=None, action_type="CORRECTIVE_DISTRIBUTION",
                          principal_cents=5_000, participant_opening_balance=100_000,
                          execute_clock="2026-03-01T00:00:00Z",
                          planned_execution_date="2026-03-01",
                          finding_severity="MEDIUM", **action_overrides) -> dict:
    """Finding acknowledged, action proposed/approved/executed at the given clock.

    Returns dict with keys: engagement, participant, finding, action.
    """
    ctx = setup_acknowledged_finding(
        plan_number, severity=finding_severity,
        participant_opening_balance=participant_opening_balance)
    payload = {
        "action_type": action_type,
        "principal_cents": principal_cents,
        "planned_execution_date": planned_execution_date,
    }
    if action_type in ("CORRECTIVE_DISTRIBUTION", "QNEC_CONTRIBUTION", "QMAC_CONTRIBUTION"):
        payload["participant_id"] = ctx["participant"]["id"]
    payload.update(action_overrides)
    action = propose_approved_action(ctx["engagement"]["id"], ctx["finding"]["id"], **payload)
    get_success_data(api_client.set_clock(execute_clock, SYSTEM))
    action = execute_action(action["id"])
    ctx["action"] = action
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: ADP/coverage census construction
# ---------------------------------------------------------------------------

def add_census_group(engagement_id: str, deferral_amount_cy_cents: int, is_hce: bool,
                     count: int, ref_prefix: str,
                     compensation_cy_cents: int = 10_000_000,
                     opening_balance_cents: int = 0,
                     is_eligible: bool = True) -> list:
    """Create `count` identical participants for ratio tests (one POST each so
    external refs stay readable)."""
    created = []
    for i in range(1, count + 1):
        created.append(add_participant(
            engagement_id, f"{ref_prefix}-{i:03d}",
            is_hce=is_hce, is_eligible=is_eligible,
            compensation_cy_cents=compensation_cy_cents,
            deferral_amount_cy_cents=deferral_amount_cy_cents,
            opening_balance_cents=opening_balance_cents))
    return created


def current_engagement_version(engagement_id: str) -> int:
    """Freshly observed engagement version for OCC-guarded test-result creates."""
    return get_success_data(api_client.get_engagement(engagement_id, SPONSOR))["version"]


def run_test(engagement_id: str, test_type: str = "ADP", **overrides) -> dict:
    """Create a nondiscrimination/coverage test result with the current OCC
    version. Returns the COMPUTED result."""
    payload = {
        "engagement_id": engagement_id,
        "test_type": test_type,
        "expected_engagement_version": current_engagement_version(engagement_id),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_test_result(payload, TPA))


# ---------------------------------------------------------------------------
# Tier 6: filings with deadlines / extensions
# ---------------------------------------------------------------------------

def create_filing_extension(filing_id: str, filed_date: str = "2026-07-20") -> dict:
    return get_success_data(api_client.create_filing_extension(
        create_filing_extension_payload(filing_id, filed_date=filed_date), TPA))


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, SYSTEM))
