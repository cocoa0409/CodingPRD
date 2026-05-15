"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Donor is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Donor, X-User-ID
  is the id of the acting Donor; ownership checks on any resource that
  references a Donor (an Account via its primary_donor_id, a
  Contribution or RecurringPlan via its donor_id) compare the resource's
  foreign-key field to X-User-ID." Therefore every Donor call whose
  success depends on owning the targeted Account / RecurringPlan /
  Withdrawal / BeneficiaryChangeRequest MUST mint headers via
  make_donor_headers(donor["id"]) — never via the DONOR_FALLBACK_ID
  shared constant.

- Beneficiary is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Beneficiary, X-User-ID is the id of the acting Beneficiary; the
  read-only views available to a beneficiary are restricted to accounts
  whose beneficiary_id equals X-User-ID." Every Beneficiary read whose
  success depends on being the beneficiary of the targeted Account MUST
  mint headers via make_beneficiary_headers(beneficiary["id"]).

- PlanAdministrator is OPAQUE. PRD §2.1: "X-User-ID is an opaque
  operator identifier not tied to any persisted entity." The shared
  constant is canonical for all PlanAdministrator calls.

The DONOR_FALLBACK_ID and BENEFICIARY_FALLBACK_ID shared constants are
ONLY safe for tests that DO NOT exercise ownership (header-missing,
role-mismatch, NotFound paths). Ownership-gated calls MUST use the
per-instance builders.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PlanAdministrator is opaque per
# PRD §2.1, so shared constants are the canonical form.
# ---------------------------------------------------------------------------
PLAN_ADMINISTRATOR_ID = "admin-001"
PLAN_ADMINISTRATOR_ID_ALT = "admin-002"

# Donor / Beneficiary fallback IDs — ONLY safe for tests that do NOT
# exercise ownership. Ownership-gated calls MUST instead mint headers
# via make_donor_headers(donor["id"]) or
# make_beneficiary_headers(beneficiary["id"]).
DONOR_FALLBACK_ID = "fallback-donor-1"
BENEFICIARY_FALLBACK_ID = "fallback-beneficiary-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlanAdministrator — shared constant is canonical.
    "admin_headers": build_user_headers(
        PLAN_ADMINISTRATOR_ID, "PlanAdministrator",
    ),
    "admin_headers_alt": build_user_headers(
        PLAN_ADMINISTRATOR_ID_ALT, "PlanAdministrator",
    ),
    # Entity-backed Donor fallback — DO NOT use for ownership-gated calls.
    "donor_headers": build_user_headers(DONOR_FALLBACK_ID, "Donor"),
    # Entity-backed Beneficiary fallback — DO NOT use for ownership-gated
    # calls.
    "beneficiary_headers": build_user_headers(
        BENEFICIARY_FALLBACK_ID, "Beneficiary",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Donor and
# Beneficiary roles. The runtime Donor.id / Beneficiary.id minted by
# POST /donors and POST /beneficiaries is the value the implementation
# will compare against.
# ---------------------------------------------------------------------------
def make_donor_headers(donor_id: str) -> Dict[str, str]:
    """For Donor (entity_backed:Donor). Pass the actual Donor.id of the
    acting donor.

    PRD §2.1: "ownership checks on any resource that references a Donor
    ... compare the resource's foreign-key field to X-User-ID." Every
    Donor call whose success depends on owning the targeted Account,
    Contribution, RecurringPlan, Withdrawal, or BeneficiaryChangeRequest
    (e.g., POST /accounts/{id}/close, POST /accounts/{id}/contributions,
    POST /withdrawals/{id}/disburse, POST /recurring-plans/{id}/pause,
    POST /accounts/{id}/beneficiary-change-requests) MUST use this
    builder, not the DONOR_FALLBACK_ID shared constant.
    """
    return build_user_headers(donor_id, "Donor")


def make_beneficiary_headers(beneficiary_id: str) -> Dict[str, str]:
    """For Beneficiary (entity_backed:Beneficiary). Pass the actual
    Beneficiary.id of the acting beneficiary.

    PRD §2.1: "the read-only views available to a beneficiary are
    restricted to accounts whose beneficiary_id equals X-User-ID."
    Every Beneficiary read whose success depends on being the
    beneficiary of the targeted Account MUST use this builder, not the
    BENEFICIARY_FALLBACK_ID shared constant.
    """
    return build_user_headers(beneficiary_id, "Beneficiary")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlanAdministrator (opaque). Any non-empty operator id is
    fine; this builder is provided for tests that want a distinct
    operator id (e.g., distinguishing two simultaneous administrator
    actions in audit-style assertions).
    """
    return build_user_headers(admin_id, "PlanAdministrator")


__all__ = [
    "PLAN_ADMINISTRATOR_ID",
    "PLAN_ADMINISTRATOR_ID_ALT",
    "DONOR_FALLBACK_ID",
    "BENEFICIARY_FALLBACK_ID",
    "TEST_USERS",
    "make_donor_headers",
    "make_beneficiary_headers",
    "make_admin_headers",
]
