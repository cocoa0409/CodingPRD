"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- HospitalReporter / LabTechnician / CDCDispatcher / CDCTracer are
  ENTITY-BACKED: X-User-ID is the id of the acting
  ReportingInstitution. Ownership checks on resources that reference
  a ReportingInstitution — reporting_institution_id on a Case,
  ordering_institution_id on a TestOrder, requesting_institution_id
  on a SupplyRequest, assigned_cdc_id on a TracingTask — compare the
  FK directly to X-User-ID. Fixtures that create those resources
  MUST therefore mint the headers with the actual institution.id of
  the institution that owns the resource. The shared constants below
  are only safe for tests that DO NOT exercise ownership (header-
  missing, role-not-permitted, resource-not-found, etc.).

- CDCSupervisor / RiskExpert / PressOfficer / SupplyManager are
  OPAQUE. The server may record the value as expert_reviewer_id or
  AuditLog.actor_id but does not gate ownership on it. Shared
  constants are canonical.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers (PRD §2.1).
# ---------------------------------------------------------------------------
CDC_SUPERVISOR_ID = "supervisor-001"
CDC_SUPERVISOR_ID_ALT = "supervisor-002"

RISK_EXPERT_ID = "expert-001"
RISK_EXPERT_ID_ALT = "expert-002"

PRESS_OFFICER_ID = "press-001"
PRESS_OFFICER_ID_ALT = "press-002"

SUPPLY_MANAGER_ID = "supply-mgr-001"
SUPPLY_MANAGER_ID_ALT = "supply-mgr-002"

# Fallback identifiers for entity-backed roles when ownership is NOT
# being tested (header-missing, role-mismatch, NotFound paths).
# DO NOT pass these into ownership-gated calls — use the per-instance
# make_*_headers() builder with the real institution id instead.
HOSPITAL_REPORTER_FALLBACK_ID = "fallback-hospital-1"
LAB_TECHNICIAN_FALLBACK_ID = "fallback-lab-1"
CDC_DISPATCHER_FALLBACK_ID = "fallback-cdc-dispatcher-1"
CDC_TRACER_FALLBACK_ID = "fallback-cdc-tracer-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical.
    "cdc_supervisor_headers": build_user_headers(
        CDC_SUPERVISOR_ID, "CDCSupervisor",
    ),
    "cdc_supervisor_headers_alt": build_user_headers(
        CDC_SUPERVISOR_ID_ALT, "CDCSupervisor",
    ),
    "risk_expert_headers": build_user_headers(RISK_EXPERT_ID, "RiskExpert"),
    "risk_expert_headers_alt": build_user_headers(
        RISK_EXPERT_ID_ALT, "RiskExpert",
    ),
    "press_officer_headers": build_user_headers(
        PRESS_OFFICER_ID, "PressOfficer",
    ),
    "press_officer_headers_alt": build_user_headers(
        PRESS_OFFICER_ID_ALT, "PressOfficer",
    ),
    "supply_manager_headers": build_user_headers(
        SUPPLY_MANAGER_ID, "SupplyManager",
    ),
    "supply_manager_headers_alt": build_user_headers(
        SUPPLY_MANAGER_ID_ALT, "SupplyManager",
    ),
    # Entity-backed roles — fallback constants ONLY for tests that
    # don't exercise ownership. Ownership-gated calls MUST use
    # make_<role>_headers(institution["id"]).
    "hospital_reporter_headers": build_user_headers(
        HOSPITAL_REPORTER_FALLBACK_ID, "HospitalReporter",
    ),
    "lab_technician_headers": build_user_headers(
        LAB_TECHNICIAN_FALLBACK_ID, "LabTechnician",
    ),
    "cdc_dispatcher_headers": build_user_headers(
        CDC_DISPATCHER_FALLBACK_ID, "CDCDispatcher",
    ),
    "cdc_tracer_headers": build_user_headers(
        CDC_TRACER_FALLBACK_ID, "CDCTracer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for ownership-gated calls.
# PRD §2.1: "Ownership checks on any resource that references a
# ReportingInstitution ... compare the resource's foreign-key field to
# X-User-ID."
# ---------------------------------------------------------------------------
def make_hospital_reporter_headers(institution_id: str) -> Dict[str, str]:
    """For HospitalReporter (entity_backed:ReportingInstitution). Pass
    the institution.id that will own (or already owns) the resource
    being mutated."""
    return build_user_headers(institution_id, "HospitalReporter")


def make_lab_technician_headers(institution_id: str) -> Dict[str, str]:
    """For LabTechnician (entity_backed:ReportingInstitution). Pass
    the LAB institution.id that ingests the test result."""
    return build_user_headers(institution_id, "LabTechnician")


def make_cdc_dispatcher_headers(institution_id: str) -> Dict[str, str]:
    """For CDCDispatcher (entity_backed:ReportingInstitution). Pass
    the CDC institution.id that files the case or dispatches the
    tracing task."""
    return build_user_headers(institution_id, "CDCDispatcher")


def make_cdc_tracer_headers(institution_id: str) -> Dict[str, str]:
    """For CDCTracer (entity_backed:ReportingInstitution). Pass the
    CDC institution.id assigned to the tracing task or driving the
    isolation."""
    return build_user_headers(institution_id, "CDCTracer")


# Opaque-role per-instance builders — useful when a test wants a
# distinct actor_id for audit-log distinguishability.
def make_cdc_supervisor_headers(supervisor_id: str) -> Dict[str, str]:
    return build_user_headers(supervisor_id, "CDCSupervisor")


def make_risk_expert_headers(expert_id: str) -> Dict[str, str]:
    return build_user_headers(expert_id, "RiskExpert")


def make_press_officer_headers(officer_id: str) -> Dict[str, str]:
    return build_user_headers(officer_id, "PressOfficer")


def make_supply_manager_headers(manager_id: str) -> Dict[str, str]:
    return build_user_headers(manager_id, "SupplyManager")


__all__ = [
    "CDC_SUPERVISOR_ID",
    "CDC_SUPERVISOR_ID_ALT",
    "RISK_EXPERT_ID",
    "RISK_EXPERT_ID_ALT",
    "PRESS_OFFICER_ID",
    "PRESS_OFFICER_ID_ALT",
    "SUPPLY_MANAGER_ID",
    "SUPPLY_MANAGER_ID_ALT",
    "HOSPITAL_REPORTER_FALLBACK_ID",
    "LAB_TECHNICIAN_FALLBACK_ID",
    "CDC_DISPATCHER_FALLBACK_ID",
    "CDC_TRACER_FALLBACK_ID",
    "TEST_USERS",
    "make_hospital_reporter_headers",
    "make_lab_technician_headers",
    "make_cdc_dispatcher_headers",
    "make_cdc_tracer_headers",
    "make_cdc_supervisor_headers",
    "make_risk_expert_headers",
    "make_press_officer_headers",
    "make_supply_manager_headers",
]
