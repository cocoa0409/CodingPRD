"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints; the harness restarts the server before every test, so nothing is
shared across tests. Setup calls go through get_success_data so a broken
precondition surfaces as a clear "Setup step failed" error.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_activation_payload,
    create_alternate_site_payload,
    create_assessment_payload,
    create_attestation_payload,
    create_bia_payload,
    create_comm_node_payload,
    create_dependency_payload,
    create_exercise_payload,
    create_finding_payload,
    create_gap_payload,
    create_plan_payload,
    create_plan_section_payload,
    create_process_payload,
    create_recovery_capability_payload,
    create_site_reservation_payload,
    create_third_party_payload,
    create_validation_run_payload,
)
from .test_users import (
    TEST_USERS,
    make_attestation_signer_headers,
    make_crisis_officer_headers,
    make_exercise_officer_headers,
    make_plan_approver_headers,
    make_plan_author_headers,
    make_risk_committee_headers,
    make_site_coordinator_headers,
    make_vendor_manager_headers,
)

ADMIN_HEADERS = TEST_USERS["resilience_admin_headers"]
ANALYST_HEADERS = TEST_USERS["bia_analyst_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
REQUIRED_SECTION_TYPES = ("RECOVERY_STRATEGY", "DEPENDENCY_MAP", "COMMS_PLAN")


def _d(response):
    return get_success_data(response)


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tier 0: clock, contacts, processes
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    """Advance the logical program clock (PRD §2.4)."""
    return _d(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN_HEADERS))


def create_contact(full_name: str = "Test Contact", role_title: str = "Staff",
                   email: str = None) -> dict:
    payload = {
        "full_name": full_name,
        "email": email or f"contact-{uuid.uuid4().hex[:10]}@example.com",
        "role_title": role_title,
    }
    return _d(api_client.create_contact(payload, ADMIN_HEADERS))


def create_process(owner_contact_id: str, name: str = None,
                   criticality_tier: str = "TIER_2", business_unit: str = "Ops") -> dict:
    payload = create_process_payload(
        name=name or unique_name("Proc"),
        business_unit=business_unit,
        owner_contact_id=owner_contact_id,
        criticality_tier=criticality_tier,
    )
    return _d(api_client.create_process(payload, ADMIN_HEADERS))


def activate_process(process_id: str) -> dict:
    return _d(api_client.activate_process(process_id, ADMIN_HEADERS))


def create_active_process(owner_contact_id: str, name: str = None,
                          criticality_tier: str = "TIER_2") -> dict:
    """Tier 1: create a process and walk it DRAFT -> ACTIVE."""
    process = create_process(owner_contact_id, name=name, criticality_tier=criticality_tier)
    return activate_process(process["id"])


# ---------------------------------------------------------------------------
# Tier 1: BIA lifecycle
# ---------------------------------------------------------------------------

def create_bia(process_id: str, **overrides) -> dict:
    payload = create_bia_payload(process_id=process_id, **overrides)
    return _d(api_client.create_bia(payload, ANALYST_HEADERS))


def submit_bia(bia_id: str) -> dict:
    return _d(api_client.submit_bia(bia_id, ANALYST_HEADERS))


def decide_bia(bia_id: str, decision: str, committee_contact_id: str) -> dict:
    headers = make_risk_committee_headers(committee_contact_id)
    return _d(api_client.decide_bia(bia_id, {"decision": decision}, headers))


def create_submitted_bia(process_id: str, **overrides) -> dict:
    bia = create_bia(process_id, **overrides)
    return submit_bia(bia["id"])


def create_approved_bia(process_id: str, decider_contact_id: str, **overrides) -> dict:
    """Create + submit + RiskCommittee APPROVE. Returns the APPROVED BIA."""
    bia = create_submitted_bia(process_id, **overrides)
    return decide_bia(bia["id"], "APPROVE", decider_contact_id)


# ---------------------------------------------------------------------------
# Tier 2: plans and sections
# ---------------------------------------------------------------------------

def create_plan(process_id: str, author_contact_id: str, **overrides) -> dict:
    payload = create_plan_payload(process_id=process_id, **overrides)
    return _d(api_client.create_plan(payload, make_plan_author_headers(author_contact_id)))


def add_required_sections(plan_id: str, author_contact_id: str) -> list:
    """Attach the three submission-gating sections (PRD §3.3)."""
    headers = make_plan_author_headers(author_contact_id)
    sections = []
    for index, section_type in enumerate(REQUIRED_SECTION_TYPES, start=1):
        payload = create_plan_section_payload(
            section_type=section_type, content=f"{section_type} body", order_index=index,
        )
        sections.append(_d(api_client.create_plan_section(plan_id, payload, headers)))
    return sections


def create_plan_with_sections(process_id: str, author_contact_id: str, **overrides) -> dict:
    plan = create_plan(process_id, author_contact_id, **overrides)
    add_required_sections(plan["id"], author_contact_id)
    return plan


def submit_plan(plan_id: str, author_contact_id: str) -> dict:
    return _d(api_client.submit_plan(plan_id, make_plan_author_headers(author_contact_id)))


def approve_plan(plan_id: str, approver_contact_id: str) -> dict:
    return _d(api_client.approve_plan(plan_id, make_plan_approver_headers(approver_contact_id)))


def create_approved_plan(process_id: str, author_contact_id: str,
                         approver_contact_id: str, **overrides) -> dict:
    """Tier 3: create + required sections + submit + approve."""
    plan = create_plan_with_sections(process_id, author_contact_id, **overrides)
    submit_plan(plan["id"], author_contact_id)
    return approve_plan(plan["id"], approver_contact_id)


# ---------------------------------------------------------------------------
# Tier 3: exercises
# ---------------------------------------------------------------------------

def create_exercise(process_id: str, plan_id: str, officer_contact_id: str,
                    exercise_type: str = "TABLETOP",
                    scheduled_start: str = "2026-05-10T09:00:00Z",
                    scheduled_end: str = "2026-05-10T11:00:00Z") -> dict:
    payload = create_exercise_payload(
        process_id=process_id, plan_id=plan_id, exercise_type=exercise_type,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    return _d(api_client.create_exercise(payload, make_exercise_officer_headers(officer_contact_id)))


def start_exercise(exercise_id: str, officer_contact_id: str) -> dict:
    return _d(api_client.start_exercise(exercise_id, make_exercise_officer_headers(officer_contact_id)))


def complete_exercise(exercise_id: str, officer_contact_id: str,
                      completion_outcome: str = "MET",
                      achieved_rto_hours: int = 8, achieved_rpo_hours: int = 2) -> dict:
    payload = {
        "completion_outcome": completion_outcome,
        "achieved_rto_hours": achieved_rto_hours,
        "achieved_rpo_hours": achieved_rpo_hours,
    }
    return _d(api_client.complete_exercise(exercise_id, payload,
                                           make_exercise_officer_headers(officer_contact_id)))


def create_completed_exercise(process_id: str, plan_id: str, officer_contact_id: str,
                              exercise_type: str = "TABLETOP", completion_outcome: str = "MET",
                              achieved_rto_hours: int = 8, achieved_rpo_hours: int = 2,
                              scheduled_start: str = "2026-05-10T09:00:00Z",
                              scheduled_end: str = "2026-05-10T11:00:00Z") -> dict:
    """Tier 3: schedule -> start -> complete."""
    exercise = create_exercise(process_id, plan_id, officer_contact_id,
                               exercise_type=exercise_type,
                               scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    start_exercise(exercise["id"], officer_contact_id)
    return complete_exercise(exercise["id"], officer_contact_id,
                             completion_outcome=completion_outcome,
                             achieved_rto_hours=achieved_rto_hours,
                             achieved_rpo_hours=achieved_rpo_hours)


# ---------------------------------------------------------------------------
# Tier 3: vendors, assessments, sites, reservations
# ---------------------------------------------------------------------------

def create_active_vendor(owner_contact_id: str, manager_contact_id: str, **overrides) -> dict:
    headers = make_vendor_manager_headers(manager_contact_id)
    payload = create_third_party_payload(owner_contact_id=owner_contact_id, **overrides)
    vendor = _d(api_client.create_third_party(payload, headers))
    return _d(api_client.activate_third_party(vendor["id"], headers))


def create_assessment(third_party_id: str, process_id: str, manager_contact_id: str,
                      **overrides) -> dict:
    payload = create_assessment_payload(
        third_party_id=third_party_id, process_id=process_id, **overrides)
    return _d(api_client.create_assessment(payload, make_vendor_manager_headers(manager_contact_id)))


def create_site(coordinator_contact_id: str, **overrides) -> dict:
    payload = create_alternate_site_payload(**overrides)
    return _d(api_client.create_alternate_site(payload, make_site_coordinator_headers(coordinator_contact_id)))


def reserve_seats(site_id: str, process_id: str, coordinator_contact_id: str,
                  seats_reserved: int, starts_at: str, ends_at: str,
                  purpose: str = "EXERCISE", creator_contact_id: str = None) -> dict:
    payload = create_site_reservation_payload(
        site_id=site_id, process_id=process_id, purpose=purpose,
        seats_reserved=seats_reserved, starts_at=starts_at, ends_at=ends_at,
        created_by_contact_id=creator_contact_id or coordinator_contact_id,
    )
    return _d(api_client.create_site_reservation(payload, make_site_coordinator_headers(coordinator_contact_id)))


# ---------------------------------------------------------------------------
# Tier 3: capabilities, validation runs, gaps
# ---------------------------------------------------------------------------

def create_capability(process_id: str, author_contact_id: str,
                      capability_type: str = "DATA_RESTORE",
                      capability_ref_id: str = None) -> dict:
    payload = create_recovery_capability_payload(
        process_id=process_id, capability_type=capability_type,
        capability_ref_id=capability_ref_id or unique_name("ref"),
    )
    return _d(api_client.create_recovery_capability(payload, make_plan_author_headers(author_contact_id)))


def record_validation_run(capability_id: str, officer_contact_id: str,
                          measured_rto_hours: int, measured_rpo_hours: int,
                          method: str = "COMPONENT_TEST", evidence_ref: str = "ev-1") -> dict:
    payload = create_validation_run_payload(
        capability_id=capability_id, measured_rto_hours=measured_rto_hours,
        measured_rpo_hours=measured_rpo_hours, method=method, evidence_ref=evidence_ref,
    )
    return _d(api_client.create_validation_run(payload, make_exercise_officer_headers(officer_contact_id)))


def create_validated_capability(process_id: str, author_contact_id: str,
                                officer_contact_id: str, measured_rto_hours: int = 4,
                                measured_rpo_hours: int = 1,
                                capability_type: str = "DATA_RESTORE",
                                capability_ref_id: str = None) -> tuple:
    """Register a capability and validate it with a standalone run."""
    capability = create_capability(process_id, author_contact_id,
                                   capability_type=capability_type,
                                   capability_ref_id=capability_ref_id)
    run = record_validation_run(capability["id"], officer_contact_id,
                                measured_rto_hours, measured_rpo_hours)
    return capability, run


def create_gap(process_id: str, author_contact_id: str, severity: str = "MEDIUM",
               due_date: str = "2026-12-01T00:00:00Z", description: str = "gap",
               finding_id: str = None) -> dict:
    payload = create_gap_payload(process_id=process_id, severity=severity,
                                 description=description, due_date=due_date)
    if finding_id is not None:
        payload["finding_id"] = finding_id
    return _d(api_client.create_gap(payload, make_plan_author_headers(author_contact_id)))


# ---------------------------------------------------------------------------
# Tier 3: comm trees and activations
# ---------------------------------------------------------------------------

def create_comm_node(tree_label: str, officer_contact_id: str, parent_node_id,
                     order_index: int, **overrides) -> dict:
    payload = create_comm_node_payload(
        tree_label=tree_label, parent_node_id=parent_node_id,
        order_index=order_index, **overrides)
    return _d(api_client.create_comm_node(payload, make_crisis_officer_headers(officer_contact_id)))


def create_activation(process_id: str, officer_contact_id: str,
                      declared_severity: str = "SEV2",
                      activation_criterion: str = "CRITERION_A",
                      criterion_justification: str = "drill") -> dict:
    payload = create_activation_payload(
        process_id=process_id, declared_severity=declared_severity,
        activation_criterion=activation_criterion,
        criterion_justification=criterion_justification,
    )
    return _d(api_client.create_activation(payload, make_crisis_officer_headers(officer_contact_id)))


# ---------------------------------------------------------------------------
# Tier 4/5: full-program scenarios
# ---------------------------------------------------------------------------

def setup_approved_program(process_name: str = None, rto: int = 8, rpo: int = 2,
                           criticality_tier: str = "TIER_2", bia_overrides: dict = None):
    """ACTIVE process + APPROVED BIA + APPROVED plan (with required sections).

    Returns dict(contact_author, contact_approver, process, bia, plan).
    """
    author = create_contact("Author Ann", "Plan Author")
    approver = create_contact("Approver Al", "Plan Approver")
    process = create_active_process(author["id"], name=process_name,
                                    criticality_tier=criticality_tier)
    bia = create_approved_bia(process["id"], approver["id"],
                              rto_target_hours=rto, rpo_target_hours=rpo,
                              **(bia_overrides or {}))
    plan = create_approved_plan(process["id"], author["id"], approver["id"],
                                rto_committed_hours=rto, rpo_committed_hours=rpo)
    return {
        "author": author, "approver": approver, "process": process,
        "bia": bia, "plan": plan,
    }


def setup_attestation_scenario(process_name: str = None, rto: int = 4, rpo: int = 1,
                               overdue_gap_severities=(), fresh_gap_severities=(),
                               exercise_outcome: str = "MET",
                               exercise_end: str = "2026-05-10T11:00:00Z",
                               clock: str = DEFAULT_CLOCK):
    """Full readiness scenario (PRD §3.9):

    clock set; ACTIVE process; APPROVED BIA (rto/rpo); APPROVED plan (rto/rpo);
    one VALIDATED DATA_RESTORE capability (measured exactly at target);
    one COMPLETED exercise with the given outcome (achieved at target);
    then the requested gaps — overdue ones due 2026-05-20 (before the clock),
    fresh ones due 2026-12-01 (after the clock).
    """
    set_clock(clock)
    signer = create_contact("Signer Sue", "Attestation Signer")
    committee = create_contact("Committee Kim", "Risk Committee")
    process = create_active_process(signer["id"], name=process_name)
    bia = create_approved_bia(process["id"], committee["id"],
                              rto_target_hours=rto, rpo_target_hours=rpo,
                              mtpd_hours=12)
    plan = create_approved_plan(process["id"], signer["id"], committee["id"],
                                rto_committed_hours=rto, rpo_committed_hours=rpo)
    capability, run = create_validated_capability(
        process["id"], signer["id"], committee["id"],
        measured_rto_hours=rto, measured_rpo_hours=rpo)
    exercise = create_completed_exercise(
        process["id"], plan["id"], committee["id"],
        completion_outcome=exercise_outcome,
        achieved_rto_hours=rto, achieved_rpo_hours=rpo,
        scheduled_start="2026-05-10T09:00:00Z", scheduled_end=exercise_end)
    gaps = []
    for severity in overdue_gap_severities:
        gaps.append(create_gap(process["id"], signer["id"], severity=severity,
                               due_date="2026-05-20T00:00:00Z",
                               description=f"overdue {severity}"))
    for severity in fresh_gap_severities:
        gaps.append(create_gap(process["id"], signer["id"], severity=severity,
                               due_date="2026-12-01T00:00:00Z",
                               description=f"fresh {severity}"))
    return {
        "signer": signer, "committee": committee, "process": process,
        "bia": bia, "plan": plan, "capability": capability, "run": run,
        "exercise": exercise, "gaps": gaps,
    }


def create_attestation(process_id: str, signer_contact_id: str,
                       attestation_type: str = "REGULATORY") -> dict:
    payload = create_attestation_payload(process_id=process_id,
                                         attestation_type=attestation_type)
    return _d(api_client.create_attestation(payload,
                                            make_attestation_signer_headers(signer_contact_id)))


def setup_activation_ready(process_name: str, rto: int = 8, rpo: int = 2,
                           clock: str = DEFAULT_CLOCK):
    """Clock set; crisis officer + approver contacts; ACTIVE process with the
    given name; APPROVED BIA and APPROVED plan. The process's crisis tree is
    labelled TREE_<process_name> (PRD §3.8).
    """
    set_clock(clock)
    crisis = create_contact("Crisis Chris", "Crisis Officer")
    approver = create_contact("Approver Al", "Plan Approver")
    process = create_active_process(crisis["id"], name=process_name)
    bia = create_approved_bia(process["id"], approver["id"],
                              rto_target_hours=rto, rpo_target_hours=rpo)
    plan = create_approved_plan(process["id"], approver["id"], approver["id"],
                                rto_committed_hours=rto, rpo_committed_hours=rpo)
    return {
        "crisis": crisis, "approver": approver, "process": process,
        "bia": bia, "plan": plan,
        "tree_label": f"TREE_{process_name}",
    }
