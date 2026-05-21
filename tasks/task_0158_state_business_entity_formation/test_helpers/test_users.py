"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "Two roles are entity-backed, meaning their X-User-ID is the id of a
    row in a persisted entity. When X-User-Role is Filer, X-User-ID is
    the id of the acting BusinessEntity; ownership checks on any
    resource that references a BusinessEntity compare the resource's
    business_entity_id to X-User-ID. When X-User-Role is
    RegisteredAgentService, X-User-ID is the id of the acting
    RegisteredAgent row; that identifier is the agent the caller may
    resign or update."

    "The remaining three roles — StateRegistrar, TaxOfficer, and
    ComplianceOfficer — and the test-only TestHarness are opaque:
    X-User-ID is an operator identifier not tied to any persisted
    entity."

Two roles are entity_backed:
    - Filer (entity_backed:BusinessEntity) — X-User-ID must be the
      acting BusinessEntity.id for ownership-gated calls.
    - RegisteredAgentService (entity_backed:RegisteredAgent) —
      X-User-ID must be the acting RegisteredAgent.id for resign-agent
      calls.

The remaining roles (StateRegistrar, TaxOfficer, ComplianceOfficer,
TestHarness) are opaque — a shared deterministic id is the canonical
form.

Per PRD §3.5 / §3.6 / §3.4, segregation of duties additionally compares
the Filer X-User-ID (which IS entity_backed) against the row being
acted upon for /accept on AnnualReport, /approve on EINApplication,
and /pay on FranchiseTaxAssessment. Tests of the SoD rule mint
opposing identities by composing make_filer_headers(business_entity_id)
versus the opaque-officer shared id, or by passing the entity_id back
as the TaxOfficer X-User-ID to provoke the violation explicitly.

The mandatory builders are:
    - make_filer_headers(business_entity_id)
    - make_registered_agent_headers(registered_agent_id)

The shared *_headers constants are appropriate only for tests that
don't exercise ownership or SoD identity — auth probes, role-forbidden
probes, 404 probes — and for opaque-role calls outside identity-gated
paths.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared operator ids for the opaque roles (StateRegistrar, TaxOfficer,
# ComplianceOfficer, TestHarness).
# ---------------------------------------------------------------------------
STATE_REGISTRAR_SHARED_ID: str = "state-registrar-op-0001"
STATE_REGISTRAR_SECONDARY_ID: str = "state-registrar-op-0002"
TAX_OFFICER_SHARED_ID: str = "tax-officer-op-0001"
TAX_OFFICER_SECONDARY_ID: str = "tax-officer-op-0002"
COMPLIANCE_OFFICER_SHARED_ID: str = "compliance-officer-op-0001"
COMPLIANCE_OFFICER_SECONDARY_ID: str = "compliance-officer-op-0002"
TEST_HARNESS_SHARED_ID: str = "test-harness-op-0001"

# Filer is entity_backed:BusinessEntity — this placeholder resolves to no
# real BusinessEntity. Appropriate for auth/role-forbidden/404 probes only;
# any test whose success depends on the entity owning the resource MUST
# use make_filer_headers(business_entity_id) with a real BusinessEntity.id.
FILER_SHARED_ID: str = "filer-placeholder-0001"

# RegisteredAgentService is entity_backed:RegisteredAgent — same caveat.
REGISTERED_AGENT_SERVICE_SHARED_ID: str = "registered-agent-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed roles — shared constants for non-ownership tests only.
    "filer_headers": build_user_headers(FILER_SHARED_ID, "Filer"),
    "registered_agent_service_headers": build_user_headers(
        REGISTERED_AGENT_SERVICE_SHARED_ID, "RegisteredAgentService",
    ),
    # opaque-role canonical headers.
    "state_registrar_headers": build_user_headers(
        STATE_REGISTRAR_SHARED_ID, "StateRegistrar",
    ),
    "state_registrar_secondary_headers": build_user_headers(
        STATE_REGISTRAR_SECONDARY_ID, "StateRegistrar",
    ),
    "tax_officer_headers": build_user_headers(
        TAX_OFFICER_SHARED_ID, "TaxOfficer",
    ),
    "tax_officer_secondary_headers": build_user_headers(
        TAX_OFFICER_SECONDARY_ID, "TaxOfficer",
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_SHARED_ID, "ComplianceOfficer",
    ),
    "compliance_officer_secondary_headers": build_user_headers(
        COMPLIANCE_OFFICER_SECONDARY_ID, "ComplianceOfficer",
    ),
    "test_harness_headers": build_user_headers(
        TEST_HARNESS_SHARED_ID, "TestHarness",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed roles.
#
# PRD §2.1: "ownership checks on any resource that references a
# BusinessEntity compare the resource's business_entity_id to X-User-ID."
# ---------------------------------------------------------------------------
def make_filer_headers(business_entity_id: str) -> Dict[str, str]:
    """Headers for a Filer acting on behalf of business_entity_id.

    Required whenever the call is gated on
    resource.business_entity_id == X-User-ID — e.g., POST /dissolve,
    POST /operating-agreements, POST /ein-applications and /submit,
    POST /annual-reports and /submit, PATCH /annual-reports/{id},
    POST /tax-assessments/{id}/pay, POST /foreign-qualifications and
    /withdraw, PATCH /foreign-qualifications/{id}, POST /boi-reports
    and /file, POST/DELETE /entities/{id}/boi-ownership.
    """
    return build_user_headers(business_entity_id, "Filer")


def make_registered_agent_headers(registered_agent_id: str) -> Dict[str, str]:
    """Headers for a RegisteredAgentService acting on behalf of a
    specific RegisteredAgent row (resign-agent path).
    """
    return build_user_headers(
        registered_agent_id, "RegisteredAgentService",
    )


# ---------------------------------------------------------------------------
# Per-operator builders for opaque officer roles.
# Use when a test needs two distinct operators for SoD-like checks.
# ---------------------------------------------------------------------------
def make_state_registrar_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "StateRegistrar")


def make_tax_officer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "TaxOfficer")


def make_compliance_officer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "ComplianceOfficer")


def make_test_harness_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "TestHarness")


__all__ = [
    "STATE_REGISTRAR_SHARED_ID",
    "STATE_REGISTRAR_SECONDARY_ID",
    "TAX_OFFICER_SHARED_ID",
    "TAX_OFFICER_SECONDARY_ID",
    "COMPLIANCE_OFFICER_SHARED_ID",
    "COMPLIANCE_OFFICER_SECONDARY_ID",
    "TEST_HARNESS_SHARED_ID",
    "FILER_SHARED_ID",
    "REGISTERED_AGENT_SERVICE_SHARED_ID",
    "TEST_USERS",
    "make_filer_headers",
    "make_registered_agent_headers",
    "make_state_registrar_headers",
    "make_tax_officer_headers",
    "make_compliance_officer_headers",
    "make_test_harness_headers",
]
