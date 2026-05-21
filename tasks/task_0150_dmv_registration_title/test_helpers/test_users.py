"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "When X-User-Role is Applicant, X-User-ID is the id of the acting
    Owner row; ownership checks on any resource that references an Owner
    (for example, a TransferApplication via its applicant_owner_id, or a
    RealIDApplication via its owner_id) compare the resource's
    foreign-key field to X-User-ID. When X-User-Role is any of
    VinVerifier, TaxAssessor, PlateIssuer, SalvageOfficer,
    EmissionsInspector, LienClerk, RealIDReviewer, or PlatformAdmin,
    X-User-ID is an opaque operator identifier not tied to any
    persisted entity."

Only Applicant is entity_backed (entity_backed:Owner). The eight clerk
roles are opaque — a shared deterministic id is the canonical form for
them.

Per PRD §3.8, TaxAssessor and PlateIssuer also enforce
segregation-of-duties: "the X-User-ID of this PlateIssuer call differs
from the X-User-ID that originally ran fee assessment on this same
application". Tests of the SoD rule must use DIFFERENT opaque operator
ids; the helper make_clerk_headers(role, suffix) below mints unique
per-test operator ids when SoD is load-bearing.

The shared *_headers constants are appropriate for tests that don't
exercise ownership or SoD identity — auth probes, role-forbidden probes,
404 probes — and for tests where the caller is an opaque clerk and the
two clerks involved are different (which the defaults already guarantee
because TAX_ASSESSOR_SHARED_ID != PLATE_ISSUER_SHARED_ID).

The mandatory builder is make_applicant_headers(owner_id). Fixtures
that create an Owner and then act as that Owner MUST mint headers with
that Owner.id rather than reusing the shared constant — otherwise the
server's ownership check (TransferApplication.applicant_owner_id ==
X-User-ID, RealIDApplication.owner_id == X-User-ID) would reject the
call.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Bootstrap / shared operator ids for the eight opaque clerk roles.
# ---------------------------------------------------------------------------
VIN_VERIFIER_SHARED_ID: str = "vin-verifier-op-0001"
TAX_ASSESSOR_SHARED_ID: str = "tax-assessor-op-0001"
PLATE_ISSUER_SHARED_ID: str = "plate-issuer-op-0001"
SALVAGE_OFFICER_SHARED_ID: str = "salvage-officer-op-0001"
EMISSIONS_INSPECTOR_SHARED_ID: str = "emissions-inspector-op-0001"
LIEN_CLERK_SHARED_ID: str = "lien-clerk-op-0001"
REAL_ID_REVIEWER_SHARED_ID: str = "real-id-reviewer-op-0001"
PLATFORM_ADMIN_SHARED_ID: str = "platform-admin-op-0001"

# Applicant is entity_backed — this shared id is a placeholder that
# resolves to no real Owner. It is appropriate for auth / role-forbidden /
# 404 probes only; any test whose success depends on the applicant owning
# the resource MUST use make_applicant_headers(owner_id) with a real
# Owner.id.
APPLICANT_SHARED_ID: str = "applicant-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed:Owner — shared constant for non-ownership tests only.
    "applicant_headers": build_user_headers(APPLICANT_SHARED_ID, "Applicant"),
    # opaque operator roles — shared constants are canonical.
    "vin_verifier_headers": build_user_headers(
        VIN_VERIFIER_SHARED_ID, "VinVerifier",
    ),
    "tax_assessor_headers": build_user_headers(
        TAX_ASSESSOR_SHARED_ID, "TaxAssessor",
    ),
    "plate_issuer_headers": build_user_headers(
        PLATE_ISSUER_SHARED_ID, "PlateIssuer",
    ),
    "salvage_officer_headers": build_user_headers(
        SALVAGE_OFFICER_SHARED_ID, "SalvageOfficer",
    ),
    "emissions_inspector_headers": build_user_headers(
        EMISSIONS_INSPECTOR_SHARED_ID, "EmissionsInspector",
    ),
    "lien_clerk_headers": build_user_headers(
        LIEN_CLERK_SHARED_ID, "LienClerk",
    ),
    "real_id_reviewer_headers": build_user_headers(
        REAL_ID_REVIEWER_SHARED_ID, "RealIDReviewer",
    ),
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_SHARED_ID, "PlatformAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — MANDATORY for entity_backed:Owner role.
#
# PRD §2.1: "ownership checks on any resource that references an Owner ...
# compare the resource's foreign-key field to X-User-ID."
# ---------------------------------------------------------------------------
def make_applicant_headers(owner_id: str) -> Dict[str, str]:
    """Headers for a specific Owner acting as Applicant. Use this whenever
    the call is gated on TransferApplication.applicant_owner_id == X-User-ID
    or RealIDApplication.owner_id == X-User-ID, or for any DELETE/PATCH
    whose owner is compared to X-User-ID.
    """
    return build_user_headers(owner_id, "Applicant")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque clerk roles. Use these when a test
# needs two distinct operators of the same role (most notably for
# segregation-of-duties tests where TaxAssessor and PlateIssuer must
# carry different X-User-IDs even though both are opaque operators of
# the same kind, OR when a single test needs two TaxAssessors etc.).
# ---------------------------------------------------------------------------
def make_vin_verifier_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "VinVerifier")


def make_tax_assessor_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "TaxAssessor")


def make_plate_issuer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "PlateIssuer")


def make_salvage_officer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "SalvageOfficer")


def make_emissions_inspector_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "EmissionsInspector")


def make_lien_clerk_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "LienClerk")


def make_real_id_reviewer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "RealIDReviewer")


def make_platform_admin_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "PlatformAdmin")


__all__ = [
    "VIN_VERIFIER_SHARED_ID",
    "TAX_ASSESSOR_SHARED_ID",
    "PLATE_ISSUER_SHARED_ID",
    "SALVAGE_OFFICER_SHARED_ID",
    "EMISSIONS_INSPECTOR_SHARED_ID",
    "LIEN_CLERK_SHARED_ID",
    "REAL_ID_REVIEWER_SHARED_ID",
    "PLATFORM_ADMIN_SHARED_ID",
    "APPLICANT_SHARED_ID",
    "TEST_USERS",
    "make_applicant_headers",
    "make_vin_verifier_headers",
    "make_tax_assessor_headers",
    "make_plate_issuer_headers",
    "make_salvage_officer_headers",
    "make_emissions_inspector_headers",
    "make_lien_clerk_headers",
    "make_real_id_reviewer_headers",
    "make_platform_admin_headers",
]
