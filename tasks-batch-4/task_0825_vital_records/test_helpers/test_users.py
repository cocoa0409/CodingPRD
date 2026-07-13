"""Pre-built role headers for every role in the Vital Records PRD (§2.1).

Two roles carry opaque identities (StateRegistrar, Applicant): the shared
constant is the canonical form. Two roles are entity_backed and their
X-User-ID is an entity id used for ownership checks:
  - FacilityFiler   — X-User-ID is a Facility.id
  - MedicalCertifier — X-User-ID is a Certifier.id

For any ownership-gated call by an entity_backed role, mint per-instance
headers by passing the actual entity id to the corresponding make_* builder.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles, plus fallbacks for entity_backed calls that
# do NOT exercise ownership (e.g. a 404 lookup, a 400 on bad payload).
TEST_USERS = {
    "registrar_headers": build_user_headers("test-registrar-1", "StateRegistrar"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    # Fallbacks only — the make_* builders below are the correct choice when
    # the entity_backed role must own the resource under test.
    "facility_filer_headers": build_user_headers("test-facility-fallback", "FacilityFiler"),
    "medical_certifier_headers": build_user_headers("test-certifier-fallback", "MedicalCertifier"),
}


def make_registrar_headers(user_id: str = "test-registrar-1") -> dict:
    return build_user_headers(user_id, "StateRegistrar")


def make_applicant_headers(user_id: str = "test-applicant-1") -> dict:
    return build_user_headers(user_id, "Applicant")


def make_facility_filer_headers(user_id: str) -> dict:
    """For FacilityFiler (entity_backed:Facility). Pass the actual Facility.id
    as user_id whenever the call is ownership-gated (create/file a vital event)."""
    return build_user_headers(user_id, "FacilityFiler")


def make_medical_certifier_headers(user_id: str) -> dict:
    """For MedicalCertifier (entity_backed:Certifier). Pass the actual
    Certifier.id as user_id whenever the call is ownership-gated (sign a
    certification)."""
    return build_user_headers(user_id, "MedicalCertifier")
