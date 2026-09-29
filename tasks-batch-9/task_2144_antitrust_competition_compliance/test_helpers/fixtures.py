"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints
only, because each test starts against an empty database. Setup calls use the
lenient validator so a broken precondition surfaces as a setup failure rather
than as a confusing assertion inside a test body.

Identity threading matters here: a `BusinessLead` acts with the business unit's
own id as `X-User-ID` and an `Employee` with the employee record's own id, so
every ownership-gated call below builds its headers from the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_START
from .factories import (
    ONE_AFFECTED_YEAR, abort_drill_payload, association_decision_payload,
    audit_findings_payload, business_justification_payload,
    cancel_attendance_payload, complete_drill_payload,
    complete_training_payload, contact_clearance_payload,
    contact_escalation_payload, create_association_payload,
    create_attendance_payload, create_business_unit_payload,
    create_contact_payload, create_curriculum_payload,
    create_document_audit_payload, create_drill_payload,
    create_employee_payload, create_hsr_analysis_payload,
    create_leniency_application_payload, create_meeting_payload,
    create_participation_payload, create_risk_assessment_payload,
    create_site_payload, create_training_assignment_payload,
    create_transaction_payload, disclosure_decision_payload,
    disclosure_submission_payload, exposure_adjustment_payload,
    legal_clearance_payload, marker_decision_payload,
    minutes_review_payload, remediation_order_payload,
    remediation_response_payload, revoke_clearance_payload,
    submit_minutes_payload, termination_payload, waive_training_payload,
    withdrawal_payload,
)
from .test_users import (
    ADMIN, COUNSEL, make_business_lead_headers, make_counsel_headers,
    make_employee_headers,
)


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock(instant: str = CLOCK_START) -> str:
    """Move the logical clock and return the instant the server reports back."""
    return get_success_data(api.set_clock(instant, ADMIN))["current_utc"]


# ─── Reads ────────────────────────────────────────────────────────────────

def read_business_unit(unit_id: str) -> dict:
    return get_success_data(api.get_business_unit(unit_id, COUNSEL))


def unit_version(unit_id: str) -> int:
    return read_business_unit(unit_id)["version"]


def read_employee(employee_id: str) -> dict:
    return get_success_data(api.get_employee(employee_id, COUNSEL))


def read_assignment(assignment_id: str) -> dict:
    return get_success_data(api.get_training_assignment(assignment_id, COUNSEL))


def read_association(association_id: str) -> dict:
    return get_success_data(api.get_association(association_id, COUNSEL))


def read_participation(participation_id: str) -> dict:
    return get_success_data(api.get_participation(participation_id, COUNSEL))


def read_meeting(meeting_id: str) -> dict:
    return get_success_data(api.get_meeting(meeting_id, COUNSEL))


def read_attendance(attendance_id: str) -> dict:
    return get_success_data(api.get_attendance(attendance_id, COUNSEL))


def read_contact(contact_id: str) -> dict:
    return get_success_data(api.get_contact(contact_id, COUNSEL))


def read_transaction(transaction_id: str) -> dict:
    return get_success_data(api.get_transaction(transaction_id, COUNSEL))


def transaction_version(transaction_id: str) -> int:
    return read_transaction(transaction_id)["version"]


def read_hsr_analysis(analysis_id: str) -> dict:
    return get_success_data(api.get_hsr_analysis(analysis_id, COUNSEL))


def read_site(site_id: str) -> dict:
    return get_success_data(api.get_site(site_id, COUNSEL))


def read_drill(drill_id: str) -> dict:
    return get_success_data(api.get_drill(drill_id, COUNSEL))


def read_document_audit(audit_id: str) -> dict:
    return get_success_data(api.get_document_audit(audit_id, COUNSEL))


def read_application(application_id: str) -> dict:
    return get_success_data(api.get_leniency_application(application_id, COUNSEL))


def read_assessment(assessment_id: str) -> dict:
    return get_success_data(api.get_risk_assessment(assessment_id, COUNSEL))


# ─── Tier 1: single-resource creation ─────────────────────────────────────

def register_business_unit(**overrides) -> dict:
    """Register a business unit. Defaults score 27.00 / MODERATE if assessed."""
    return get_success_data(
        api.create_business_unit(create_business_unit_payload(**overrides), ADMIN))


def register_employee(business_unit_id: str, role_category: str = "LEGAL",
                      **overrides) -> dict:
    return get_success_data(api.create_employee(
        create_employee_payload(business_unit_id, role_category=role_category,
                                **overrides),
        ADMIN))


def define_curriculum(**overrides) -> dict:
    return get_success_data(
        api.create_curriculum(create_curriculum_payload(**overrides), ADMIN))


def assign_training(employee_id: str, curriculum_id: str,
                    due_at: str = "2026-08-31T00:00:00Z") -> dict:
    return get_success_data(api.create_training_assignment(
        create_training_assignment_payload(employee_id, curriculum_id, due_at),
        ADMIN))


def complete_assignment(assignment_id: str, employee_id: str, score: int = 91) -> dict:
    headers = make_employee_headers(employee_id)
    get_success_data(api.start_training(assignment_id, headers))
    return get_success_data(api.complete_training(
        assignment_id, complete_training_payload(score), headers))


def waive_assignment(assignment_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.waive_training(
        assignment_id, waive_training_payload(), make_counsel_headers(counsel_id)))


def grant_clearance(employee_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(
        api.grant_clearance(employee_id, make_counsel_headers(counsel_id)))


def revoke_clearance(employee_id: str, counsel_id: str = "counsel-1",
                     reason: str = "Delegate moved to a competitor-facing commercial role") -> dict:
    return get_success_data(api.revoke_clearance(
        employee_id, revoke_clearance_payload(reason),
        make_counsel_headers(counsel_id)))


def propose_association(**overrides) -> dict:
    return get_success_data(
        api.create_association(create_association_payload(**overrides), ADMIN))


def decide_association(association_id: str, decision: str = "APPROVED",
                       counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.decide_association(
        association_id, association_decision_payload(decision),
        make_counsel_headers(counsel_id)))


def create_approved_association(**overrides) -> dict:
    association = propose_association(**overrides)
    return decide_association(association["id"], "APPROVED")


def register_site(**overrides) -> dict:
    return get_success_data(api.create_site(create_site_payload(**overrides), ADMIN))


def schedule_drill(site_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_drill(create_drill_payload(site_id, **overrides), ADMIN))


def start_drill(drill_id: str) -> dict:
    return get_success_data(api.start_drill(drill_id, ADMIN))


def complete_drill(drill_id: str, score: int = 80, gaps_found: int = 3,
                   counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.complete_drill(
        drill_id, complete_drill_payload(score, gaps_found),
        make_counsel_headers(counsel_id)))


def abort_drill(drill_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.abort_drill(
        drill_id, abort_drill_payload(), make_counsel_headers(counsel_id)))


def open_document_audit(business_unit_id: str, sample_size: int = 20,
                        counsel_id: str = "counsel-1", **overrides) -> dict:
    return get_success_data(api.create_document_audit(
        create_document_audit_payload(business_unit_id, sample_size, **overrides),
        make_counsel_headers(counsel_id)))


def record_audit_findings(audit_id: str, violation_count: int,
                          high_risk_phrase_count: int,
                          counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.record_audit_findings(
        audit_id, audit_findings_payload(violation_count, high_risk_phrase_count),
        make_counsel_headers(counsel_id)))


# ─── Tier 2: training currency ────────────────────────────────────────────

def create_trained_employee(business_unit_id: str, role_category: str = "SALES",
                            score: int = 91, curriculum=None,
                            due_at: str = "2026-08-31T00:00:00Z",
                            **curriculum_overrides) -> dict:
    """A person whose mandatory targeting curriculum has been completed.

    Returns {"employee", "curriculum", "assignment"} with the assignment in
    COMPLETED, so `training_status` reads CURRENT while the clock stands before
    the completion's expiry instant.
    """
    employee = register_employee(business_unit_id, role_category=role_category)
    if curriculum is None:
        curriculum = define_curriculum(**curriculum_overrides)
    assignment = assign_training(employee["id"], curriculum["id"], due_at)
    assignment = complete_assignment(assignment["id"], employee["id"], score)
    return {"employee": employee, "curriculum": curriculum, "assignment": assignment}


# ─── Tier 3: participation lifecycle ──────────────────────────────────────

def nominate_participation(business_unit_id: str, association_id: str,
                           employee_id: str, purpose: str = "Standards drafting delegate") -> dict:
    return get_success_data(api.create_participation(
        create_participation_payload(business_unit_id, association_id,
                                     employee_id, purpose),
        make_business_lead_headers(business_unit_id)))


def submit_participation(participation_id: str, business_unit_id: str) -> dict:
    return get_success_data(api.submit_participation(
        participation_id, make_business_lead_headers(business_unit_id)))


def clear_legally(participation_id: str, counsel_id: str = "counsel-1",
                  decision: str = "CLEARED", notes: str = "Standards only") -> dict:
    return get_success_data(api.decide_legal_clearance(
        participation_id, legal_clearance_payload(decision, notes),
        make_counsel_headers(counsel_id)))


def justify_business(participation_id: str, business_unit_id: str,
                     justification: str = "Standard governs 60 percent of our EMEA line") -> dict:
    return get_success_data(api.record_business_justification(
        participation_id, business_justification_payload(justification),
        make_business_lead_headers(business_unit_id)))


def reinstate_participation(participation_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.reinstate_participation(
        participation_id, make_counsel_headers(counsel_id)))


def terminate_participation(participation_id: str, business_unit_id: str,
                            reason: str = "Forum merged into the European council") -> dict:
    return get_success_data(api.terminate_participation(
        participation_id, termination_payload(reason),
        make_business_lead_headers(business_unit_id)))


def setup_active_participation(bu_overrides=None, approval_tier: str = "TIER_1_LOW",
                               competitor_density_pct=0, role_category: str = "SALES",
                               clearance: bool = True,
                               legal_counsel_id: str = "counsel-1",
                               purpose: str = "Standards drafting delegate") -> dict:
    """Unit + trained delegate + approved association + ACTIVE participation.

    Returns {"unit", "employee", "curriculum", "assignment", "association",
    "participation"}. The legal branch lands first and the business branch
    completes the join, so `review_minutes_reserved` is the association's
    computed review load.
    """
    unit = register_business_unit(**(bu_overrides or {}))
    trained = create_trained_employee(unit["id"], role_category=role_category)
    if clearance:
        grant_clearance(trained["employee"]["id"])
    association = create_approved_association(
        approval_tier=approval_tier, competitor_density_pct=competitor_density_pct)
    participation = nominate_participation(
        unit["id"], association["id"], trained["employee"]["id"], purpose)
    submit_participation(participation["id"], unit["id"])
    clear_legally(participation["id"], counsel_id=legal_counsel_id)
    participation = justify_business(participation["id"], unit["id"])
    return {
        "unit": unit,
        "employee": trained["employee"],
        "curriculum": trained["curriculum"],
        "assignment": trained["assignment"],
        "association": association,
        "participation": participation,
    }


# ─── Tier 3: meetings and attendances ─────────────────────────────────────

def schedule_meeting(association_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_meeting(create_meeting_payload(association_id, **overrides), ADMIN))


def book_attendance(meeting_id: str, participation_id: str,
                    business_unit_id: str) -> dict:
    return get_success_data(api.create_attendance(
        create_attendance_payload(meeting_id, participation_id),
        make_business_lead_headers(business_unit_id)))


def cancel_attendance(attendance_id: str, business_unit_id: str,
                      reason: str = "Delegate reassigned") -> dict:
    return get_success_data(api.cancel_attendance(
        attendance_id, cancel_attendance_payload(reason),
        make_business_lead_headers(business_unit_id)))


def confirm_attendance(attendance_id: str, employee_id: str) -> dict:
    return get_success_data(
        api.confirm_attendance(attendance_id, make_employee_headers(employee_id)))


def submit_minutes(attendance_id: str, employee_id: str,
                   summary: str = "Technical agenda only",
                   topics_discussed=None) -> dict:
    return get_success_data(api.submit_minutes(
        attendance_id, submit_minutes_payload(summary, topics_discussed),
        make_employee_headers(employee_id)))


def review_minutes(attendance_id: str, verdict: str = "CLEAN", findings=None,
                   counsel_id: str = "counsel-9") -> dict:
    return get_success_data(api.review_minutes(
        attendance_id, minutes_review_payload(verdict, findings),
        make_counsel_headers(counsel_id)))


def setup_attendance_in_minutes_submitted(
        bu_overrides=None, approval_tier: str = "TIER_1_LOW",
        competitor_density_pct=0, role_category: str = "SALES",
        legal_counsel_id: str = "counsel-1",
        scheduled_start: str = "2026-09-10T09:00:00Z",
        scheduled_end: str = "2026-09-10T11:00:00Z",
        clock_after: str = "2026-09-10T12:00:00Z",
        summary: str = "Technical agenda only",
        topics_discussed=None) -> dict:
    """Full chain through to one attendance sitting in MINUTES_SUBMITTED.

    The clock is advanced past the meeting's end so attendance confirmation and
    minutes submission are both legal. Returns the
    `setup_active_participation` bundle plus "meeting" and "attendance".
    """
    bundle = setup_active_participation(
        bu_overrides=bu_overrides, approval_tier=approval_tier,
        competitor_density_pct=competitor_density_pct,
        role_category=role_category, clearance=True,
        legal_counsel_id=legal_counsel_id)
    meeting = schedule_meeting(bundle["association"]["id"],
                               scheduled_start=scheduled_start,
                               scheduled_end=scheduled_end,
                               agenda_received=True)
    attendance = book_attendance(meeting["id"], bundle["participation"]["id"],
                                 bundle["unit"]["id"])
    set_clock(clock_after)
    confirm_attendance(attendance["id"], bundle["employee"]["id"])
    attendance = submit_minutes(attendance["id"], bundle["employee"]["id"],
                                summary, topics_discussed)
    bundle["meeting"] = meeting
    bundle["attendance"] = attendance
    return bundle


# ─── Tier 4: contact log and the exposure ledger ──────────────────────────

def log_contact(business_unit_id: str, employee_id: str, **overrides) -> dict:
    return get_success_data(api.create_contact(
        create_contact_payload(business_unit_id, employee_id, **overrides),
        make_employee_headers(employee_id)))


def open_contact_review(contact_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(
        api.open_contact_review(contact_id, make_counsel_headers(counsel_id)))


def order_remediation(contact_id: str, instructions=None,
                      counsel_id: str = "counsel-1") -> dict:
    payload = (remediation_order_payload(instructions) if instructions
               else remediation_order_payload())
    return get_success_data(api.order_contact_remediation(
        contact_id, payload, make_counsel_headers(counsel_id)))


def respond_remediation(contact_id: str, employee_id: str, response=None) -> dict:
    payload = (remediation_response_payload(response) if response
               else remediation_response_payload())
    return get_success_data(api.respond_contact_remediation(
        contact_id, payload, make_employee_headers(employee_id)))


def clear_contact(contact_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.clear_contact(
        contact_id, contact_clearance_payload(), make_counsel_headers(counsel_id)))


def escalate_contact(contact_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.escalate_contact(
        contact_id, contact_escalation_payload(), make_counsel_headers(counsel_id)))


def log_and_escalate_contact(business_unit_id: str, employee_id: str,
                             counsel_id: str = "counsel-1", **overrides) -> dict:
    contact = log_contact(business_unit_id, employee_id, **overrides)
    open_contact_review(contact["id"], counsel_id)
    return escalate_contact(contact["id"], counsel_id)


def adjust_exposure(business_unit_id: str, points_delta,
                    reason: str = "Carry-over findings from the 2025 EC sector inquiry",
                    counsel_id: str = "counsel-1", expected_version=None) -> dict:
    """Move the unit's ledger by `points_delta`, reading its current version."""
    version = (expected_version if expected_version is not None
               else unit_version(business_unit_id))
    return get_success_data(api.create_exposure_adjustment(
        business_unit_id,
        exposure_adjustment_payload(points_delta, version, reason),
        make_counsel_headers(counsel_id)))


# ─── Tier 4: risk assessment ──────────────────────────────────────────────

def run_assessment(business_unit_id: str, variant: str = "BASELINE",
                   counsel_id: str = "counsel-1", expected_version=None) -> dict:
    version = (expected_version if expected_version is not None
               else unit_version(business_unit_id))
    return get_success_data(api.create_risk_assessment(
        create_risk_assessment_payload(business_unit_id, version, variant),
        make_counsel_headers(counsel_id)))


HIGH_BAND_UNIT = {
    "market_share_bps": 5000,
    "interaction_point_count": 0,
    "competitor_overlap_pct": 0,
}
SEVERE_BAND_UNIT = {
    "market_share_bps": 5000,
    "interaction_point_count": 2,
    "competitor_overlap_pct": 10,
}


def setup_high_band_unit(**overrides) -> dict:
    """A unit whose ACTIVE BASELINE assessment scores 70.00 and bands HIGH."""
    payload = dict(HIGH_BAND_UNIT)
    payload.update(overrides)
    unit = register_business_unit(**payload)
    assessment = run_assessment(unit["id"], "BASELINE")
    return {"unit": read_business_unit(unit["id"]), "assessment": assessment}


# ─── Tier 4: merger control ───────────────────────────────────────────────

def register_transaction(business_unit_id: str, **overrides) -> dict:
    return get_success_data(api.create_transaction(
        create_transaction_payload(business_unit_id, **overrides),
        make_business_lead_headers(business_unit_id)))


def run_hsr_analysis(transaction_id: str, valuation_variant: str = "SIGNED_DEAL",
                     counsel_id: str = "counsel-1", expected_version=None) -> dict:
    version = (expected_version if expected_version is not None
               else transaction_version(transaction_id))
    return get_success_data(api.create_hsr_analysis(
        create_hsr_analysis_payload(transaction_id, version, valuation_variant),
        make_counsel_headers(counsel_id)))


def file_transaction(transaction_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(
        api.file_transaction(transaction_id, make_counsel_headers(counsel_id)))


def clear_transaction(transaction_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(
        api.clear_transaction(transaction_id, make_counsel_headers(counsel_id)))


def setup_filed_transaction(business_unit_id=None, **tx_overrides) -> dict:
    """A transaction analysed above threshold and filed at the current clock."""
    unit_id = business_unit_id or register_business_unit()["id"]
    payload = {
        "target_name": "Big Target BV",
        "deal_value_cents": 60_000_000_000,
        "assumed_liabilities_cents": 0,
        "market_valuation_cents": 60_000_000_000,
        "acquirer_total_assets_cents": 50_000_000_000,
        "target_total_assets_cents": 5_000_000_000,
        "exemption_code": "NONE",
    }
    payload.update(tx_overrides)
    transaction = register_transaction(unit_id, **payload)
    analysis = run_hsr_analysis(transaction["id"], "SIGNED_DEAL",
                                expected_version=transaction["version"])
    transaction = file_transaction(transaction["id"])
    return {"unit_id": unit_id, "transaction": transaction, "analysis": analysis}


# ─── Tier 5: leniency ─────────────────────────────────────────────────────

def open_leniency_application(business_unit_id: str, cartel_code: str = "EU-RESIN-2021",
                              affected_years=None, counsel_id: str = "counsel-1",
                              **overrides) -> dict:
    return get_success_data(api.create_leniency_application(
        create_leniency_application_payload(
            business_unit_id, cartel_code,
            affected_years if affected_years is not None else ONE_AFFECTED_YEAR,
            **overrides),
        make_counsel_headers(counsel_id)))


def request_marker(application_id: str, counsel_id: str = "counsel-1") -> dict:
    return get_success_data(
        api.request_marker(application_id, make_counsel_headers(counsel_id)))


def decide_marker(application_id: str, decision: str = "GRANTED") -> dict:
    return get_success_data(api.decide_marker(
        application_id, marker_decision_payload(decision), ADMIN))


def submit_disclosure(application_id: str, gravity_pct=15,
                      counsel_id: str = "counsel-1") -> dict:
    return get_success_data(api.submit_disclosure(
        application_id, disclosure_submission_payload(gravity_pct),
        make_counsel_headers(counsel_id)))


def decide_disclosure(application_id: str, decision: str = "ACCEPTED") -> dict:
    return get_success_data(api.decide_disclosure(
        application_id, disclosure_decision_payload(decision), ADMIN))


def withdraw_application(application_id: str, counsel_id: str = "counsel-1",
                         reason: str = "Second-look review found no cartel conduct") -> dict:
    return get_success_data(api.withdraw_application(
        application_id, withdrawal_payload(reason), make_counsel_headers(counsel_id)))


def setup_granted_marker(cartel_code: str = "EU-RESIN-2021", affected_years=None,
                         granted_at=None, unit_overrides=None) -> dict:
    """A HIGH-band unit whose application holds a granted marker.

    When `granted_at` is supplied the clock is moved there before the request,
    so the grant instant — the leniency queue's primary ranking key — is
    controlled by the caller.
    """
    banded = setup_high_band_unit(**(unit_overrides or {}))
    application = open_leniency_application(
        banded["unit"]["id"], cartel_code, affected_years)
    if granted_at is not None:
        set_clock(granted_at)
    request_marker(application["id"])
    application = decide_marker(application["id"], "GRANTED")
    return {"unit": read_business_unit(banded["unit"]["id"]),
            "assessment": banded["assessment"],
            "application": application}


# ─── Listing helpers ──────────────────────────────────────────────────────

def list_ids(response_data) -> list:
    return [row["id"] for row in response_data]
