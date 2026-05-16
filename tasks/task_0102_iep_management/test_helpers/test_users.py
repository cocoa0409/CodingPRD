"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- DistrictAdmin is OPAQUE. PRD §2.1: "X-User-ID for a DistrictAdmin is
  an opaque operator identifier not tied to any persisted entity."

- SchoolPsychologist is OPAQUE. PRD §2.1: "X-User-ID for a
  SchoolPsychologist is an opaque operator identifier" — recorded on the
  evaluation as `evaluator_user_id`, but not compared to any persisted
  entity. The segregation-of-duties check on finalize compares
  X-User-ID to Student.parent_user_id (must NOT match) — so the
  psychologist's id must differ from the student's parent id.

- SpecialEducationTeacher is OPAQUE. PRD §2.1: "X-User-ID for a
  SpecialEducationTeacher is an opaque operator identifier".

- RelatedServiceProvider is OPAQUE. PRD §2.1: "X-User-ID for a
  RelatedServiceProvider is an opaque operator identifier and is
  supplied by the teacher as `provider_user_id` when a service is
  proposed".

- Parent is OWNERSHIP-GATED. PRD §2.1: "X-User-ID for a Parent is an
  opaque parent identifier, but every Parent request additionally
  requires that the value of X-User-ID match the parent_user_id
  recorded on the targeted Student. Mismatch is rejected with
  ERR_PARENT_OWNERSHIP_MISMATCH." Therefore every Parent call whose
  success depends on owning the targeted Student MUST mint headers via
  make_parent_headers(parent_user_id) — never via the shared
  PARENT_FALLBACK_ID constant.

The PARENT_FALLBACK_ID shared constant is ONLY safe for tests that DO
NOT exercise Parent ownership (e.g., wrong-role rejections,
header-missing tests). Ownership-gated Parent calls MUST use the
per-instance builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque operator ids — DistrictAdmin / SchoolPsychologist /
# SpecialEducationTeacher / RelatedServiceProvider are all OPAQUE per
# PRD §2.1; shared constants are the canonical form.
# ---------------------------------------------------------------------------
DISTRICT_ADMIN_ID = "admin-001"
DISTRICT_ADMIN_ID_ALT = "admin-002"

SCHOOL_PSYCHOLOGIST_ID = "psych-001"
SCHOOL_PSYCHOLOGIST_ID_ALT = "psych-002"

SPECIAL_ED_TEACHER_ID = "teacher-001"
SPECIAL_ED_TEACHER_ID_ALT = "teacher-002"

RELATED_SERVICE_PROVIDER_ID = "provider-001"
RELATED_SERVICE_PROVIDER_ID_ALT = "provider-002"

# Parent fallback — ONLY safe for tests that do NOT exercise Parent
# ownership. Ownership-gated calls MUST instead mint headers via
# make_parent_headers(student["parent_user_id"]).
PARENT_FALLBACK_ID = "fallback-parent-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": build_user_headers(
        DISTRICT_ADMIN_ID, "DistrictAdmin",
    ),
    "admin_headers_alt": build_user_headers(
        DISTRICT_ADMIN_ID_ALT, "DistrictAdmin",
    ),
    "psychologist_headers": build_user_headers(
        SCHOOL_PSYCHOLOGIST_ID, "SchoolPsychologist",
    ),
    "psychologist_headers_alt": build_user_headers(
        SCHOOL_PSYCHOLOGIST_ID_ALT, "SchoolPsychologist",
    ),
    "teacher_headers": build_user_headers(
        SPECIAL_ED_TEACHER_ID, "SpecialEducationTeacher",
    ),
    "teacher_headers_alt": build_user_headers(
        SPECIAL_ED_TEACHER_ID_ALT, "SpecialEducationTeacher",
    ),
    "provider_headers": build_user_headers(
        RELATED_SERVICE_PROVIDER_ID, "RelatedServiceProvider",
    ),
    "provider_headers_alt": build_user_headers(
        RELATED_SERVICE_PROVIDER_ID_ALT, "RelatedServiceProvider",
    ),
    # Parent fallback — DO NOT use for ownership-gated calls.
    "parent_headers": build_user_headers(PARENT_FALLBACK_ID, "Parent"),
}


# ---------------------------------------------------------------------------
# Per-instance builders. make_parent_headers is REQUIRED for every
# ownership-gated Parent call (consent approve / reject / withdraw on a
# specific Student). The other builders provide convenience for tests
# that need distinct operator ids (e.g., to assert
# `evaluator_user_id == X-User-ID` on a finalized evaluation).
# ---------------------------------------------------------------------------
def make_parent_headers(parent_user_id: str) -> Dict[str, str]:
    """For Parent (ownership-gated). Pass the actual
    Student.parent_user_id of the targeted student.

    PRD §2.1: "every Parent request additionally requires that the
    value of X-User-ID match the parent_user_id recorded on the
    targeted Student. Mismatch is rejected with
    ERR_PARENT_OWNERSHIP_MISMATCH." Every Parent call whose success
    depends on owning the targeted Student (approve / reject /
    withdraw consent; read-only access to the student's records) MUST
    use this builder, not the PARENT_FALLBACK_ID shared constant.
    """
    return build_user_headers(parent_user_id, "Parent")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For DistrictAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(admin_id, "DistrictAdmin")


def make_psychologist_headers(psych_id: str) -> Dict[str, str]:
    """For SchoolPsychologist (opaque). Useful when a test needs a
    distinct psychologist id, e.g., to satisfy PRD §3.2 segregation of
    duties (the acting psychologist must NOT equal the student's
    parent_user_id) by minting an id that is guaranteed different from
    the parent's identifier.
    """
    return build_user_headers(psych_id, "SchoolPsychologist")


def make_teacher_headers(teacher_id: str) -> Dict[str, str]:
    """For SpecialEducationTeacher (opaque). Useful when distinct
    teacher ids are needed for concurrency tests."""
    return build_user_headers(teacher_id, "SpecialEducationTeacher")


def make_provider_headers(provider_id: str) -> Dict[str, str]:
    """For RelatedServiceProvider (opaque). Useful when distinct
    provider ids are needed for concurrency tests."""
    return build_user_headers(provider_id, "RelatedServiceProvider")


__all__ = [
    "DISTRICT_ADMIN_ID",
    "DISTRICT_ADMIN_ID_ALT",
    "SCHOOL_PSYCHOLOGIST_ID",
    "SCHOOL_PSYCHOLOGIST_ID_ALT",
    "SPECIAL_ED_TEACHER_ID",
    "SPECIAL_ED_TEACHER_ID_ALT",
    "RELATED_SERVICE_PROVIDER_ID",
    "RELATED_SERVICE_PROVIDER_ID_ALT",
    "PARENT_FALLBACK_ID",
    "TEST_USERS",
    "make_parent_headers",
    "make_admin_headers",
    "make_psychologist_headers",
    "make_teacher_headers",
    "make_provider_headers",
]
