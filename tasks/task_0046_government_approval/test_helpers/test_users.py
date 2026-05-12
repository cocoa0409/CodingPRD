"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes two role identity shapes:

- PlatformAdmin, CertificateOfficer, Applicant carry an opaque
  identifier in X-User-ID. PRD §2.1: 'When X-User-Role is PlatformAdmin,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity'; same wording recurs for CertificateOfficer and Applicant.
  The shared TEST_USERS constants are canonical for these roles.

- CatalogManager, Reviewer, LeadReviewer are entity-backed by
  Department. PRD §2.1: 'When X-User-Role is CatalogManager, X-User-ID
  is the id of the acting Department; ownership checks ... compare the
  matter's owning_department_id to X-User-ID.' PRD §2.1: 'a reviewer
  may only act on a ReviewTask whose department_id equals X-User-ID.'
  Fixtures that create real Department rows MUST use
  make_catalog_manager_headers(department_id) /
  make_reviewer_headers(department_id) /
  make_lead_reviewer_headers(department_id) when the downstream call
  exercises an ownership comparison.

PRD §2.1 also enforces segregation of duties at decide / correction-
issue / escalate time: 'A single physical user acting as a Reviewer or
LeadReviewer on an application may not also be that application's
applicant -- the server compares X-User-ID against the application's
applicant_user_id.' Tests that exercise the joint Applicant + Reviewer
constraint must pass distinct ids accordingly.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants. Canonical for opaque roles (PlatformAdmin /
# CertificateOfficer / Applicant); fallback for the entity-backed
# CatalogManager / Reviewer / LeadReviewer roles only on tests that do
# NOT exercise an ownership comparison (e.g. ERR_AUTH_MISSING,
# ERR_FORBIDDEN, ERR_NOT_FOUND on a missing path-parameter resource).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles -- canonical shared constants.
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "platform_admin_headers_alt": build_user_headers("admin-002", "PlatformAdmin"),
    "certificate_officer_headers": build_user_headers(
        "cert-officer-001", "CertificateOfficer"
    ),
    "certificate_officer_headers_alt": build_user_headers(
        "cert-officer-002", "CertificateOfficer"
    ),
    "applicant_headers": build_user_headers("applicant-001", "Applicant"),
    "applicant_headers_alt": build_user_headers("applicant-002", "Applicant"),

    # Fallback constants for entity-backed roles. NOT canonical: any
    # ownership-gated test path MUST use the make_* builders below with
    # the actual Department.id.
    "catalog_manager_headers": build_user_headers(
        "catalog-manager-fallback", "CatalogManager"
    ),
    "reviewer_headers": build_user_headers("reviewer-fallback", "Reviewer"),
    "lead_reviewer_headers": build_user_headers(
        "lead-reviewer-fallback", "LeadReviewer"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders for the entity-backed CatalogManager / Reviewer /
# LeadReviewer roles. Pass the actual Department.id minted by
# POST /departments so X-User-ID resolves to a real entity.
# ---------------------------------------------------------------------------
def make_catalog_manager_headers(department_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is CatalogManager, X-User-ID is the id
    of the acting Department; ownership checks (for example, may this
    manager edit this matter?) compare the matter's owning_department_id
    to X-User-ID.' Pass the Department.id of the matter's owner."""
    return build_user_headers(department_id, "CatalogManager")


def make_reviewer_headers(department_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Reviewer, X-User-ID is the id of
    the acting Department; a reviewer may only act on a ReviewTask whose
    department_id equals X-User-ID.' Pass the Department.id whose stage
    holds the ReviewTask."""
    return build_user_headers(department_id, "Reviewer")


def make_lead_reviewer_headers(department_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is LeadReviewer, X-User-ID is the id
    of the acting Department; the same department_id ownership check
    applies, with the additional constraint that the department must be
    the routing's lead department to escalate.' Pass the lead
    Department.id named in the version's review_routing.lead_department_id."""
    return build_user_headers(department_id, "LeadReviewer")


def make_platform_admin_headers(admin_id: str = "admin-001") -> Dict[str, str]:
    """PRD §2.1: 'PlatformAdmin X-User-ID is an opaque operator
    identifier not tied to any persisted entity.'"""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_certificate_officer_headers(
    officer_id: str = "cert-officer-001",
) -> Dict[str, str]:
    """PRD §2.1: 'CertificateOfficer X-User-ID is an opaque operator
    identifier not tied to any persisted entity.'"""
    return build_user_headers(officer_id, "CertificateOfficer")


def make_applicant_headers(applicant_id: str = "applicant-001") -> Dict[str, str]:
    """PRD §2.1: 'Applicant X-User-ID is an opaque applicant identifier
    not tied to any persisted entity; the server records it on each
    submitted Application as applicant_user_id.' To act as the owner of
    a previously submitted Application, pass the SAME applicant_id used
    when the Application was POSTed."""
    return build_user_headers(applicant_id, "Applicant")


__all__ = [
    "TEST_USERS",
    "make_catalog_manager_headers",
    "make_reviewer_headers",
    "make_lead_reviewer_headers",
    "make_platform_admin_headers",
    "make_certificate_officer_headers",
    "make_applicant_headers",
]
