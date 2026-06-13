"""Pre-built role headers for every role in the PRD (§2.1).

- LicensingOfficer and InspectionOfficer are OPAQUE roles: X-User-ID is an
  operator identifier not tied to any persisted entity, so a shared constant is
  the canonical form. The officer id IS recorded (reviewed_by_user_id on an
  Application, inspector_user_id on an Inspection) and consulted by the
  issuance-time segregation-of-duties check, but it is never compared to any
  entity's id.
- Applicant is ENTITY-BACKED:Business. X-User-ID must equal the acting
  Business's id for ownership-gated calls (submit/withdraw own application,
  renew/surrender own license, request/cancel/settle on own resources). Use
  make_applicant_headers(business_id) with the real Business.id in those cases.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque officer roles; fallback only for
# non-ownership Applicant calls (e.g. business registration, 400/404 paths).
TEST_USERS = {
    "licensing_officer_headers": build_user_headers("officer-1", "LicensingOfficer"),
    "inspection_officer_headers": build_user_headers("inspector-1", "InspectionOfficer"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}

# Anonymous: no auth headers at all (for ERR_UNAUTHENTICATED tests).
ANONYMOUS_HEADERS: dict = {}


def make_applicant_headers(business_id: str) -> dict:
    """For the entity-backed Applicant role. Pass the acting Business.id as
    business_id whenever the call is ownership-gated."""
    return build_user_headers(business_id, "Applicant")


def make_licensing_officer_headers(user_id: str = "officer-1") -> dict:
    """LicensingOfficer is opaque; identity is a free-form operator id. Pass a
    distinct id when a test needs a specific recorded reviewer/issuer."""
    return build_user_headers(user_id, "LicensingOfficer")


def make_inspection_officer_headers(user_id: str = "inspector-1") -> dict:
    """InspectionOfficer is opaque; identity is a free-form operator id."""
    return build_user_headers(user_id, "InspectionOfficer")
