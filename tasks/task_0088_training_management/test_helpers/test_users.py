"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- TrainingAdmin, CourseDesigner, DepartmentManager — opaque
  identifiers. X-User-ID is not tied to any persisted entity. Shared
  constants are canonical for these roles.

- Trainee — entity_backed identity. "When `X-User-Role` is `Trainee`,
  `X-User-ID` is the `id` of the acting `Trainee` row. Any
  ownership-scoped operation ... compares the resource's `trainee_id`
  (or, for `Trainee` reads, the resource's own `id`) to `X-User-ID`."
  Therefore ownership-gated calls (self-enrolling, cancelling one's
  own enrollment, checking in, taking exams, submitting evaluations,
  renewing a certificate, listing one's own resources, fetching one's
  own Trainee row) MUST be issued with
  `make_trainee_headers(trainee['id'])` — the shared constant will
  never resolve to a real Trainee.id and so every ownership check
  would reject the request.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers (PRD §2.1).
# ---------------------------------------------------------------------------
TRAINING_ADMIN_ID = "training-admin-001"
TRAINING_ADMIN_ID_ALT = "training-admin-002"

COURSE_DESIGNER_ID = "course-designer-001"
COURSE_DESIGNER_ID_ALT = "course-designer-002"

DEPARTMENT_MANAGER_ID = "department-manager-001"
DEPARTMENT_MANAGER_ID_ALT = "department-manager-002"

# Stable string used only by tests that do NOT exercise Trainee ownership
# (missing-auth, wrong-role, missing-resource). Ownership-gated tests
# MUST use make_trainee_headers(trainee['id']).
TRAINEE_FALLBACK_ID = "trainee-fallback-001"
TRAINEE_FALLBACK_ID_ALT = "trainee-fallback-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # TrainingAdmin (opaque) — canonical shared constants.
    "training_admin_headers": build_user_headers(
        TRAINING_ADMIN_ID, "TrainingAdmin",
    ),
    "training_admin_headers_alt": build_user_headers(
        TRAINING_ADMIN_ID_ALT, "TrainingAdmin",
    ),

    # CourseDesigner (opaque) — canonical shared constants.
    "course_designer_headers": build_user_headers(
        COURSE_DESIGNER_ID, "CourseDesigner",
    ),
    "course_designer_headers_alt": build_user_headers(
        COURSE_DESIGNER_ID_ALT, "CourseDesigner",
    ),

    # DepartmentManager (opaque) — canonical shared constants.
    "department_manager_headers": build_user_headers(
        DEPARTMENT_MANAGER_ID, "DepartmentManager",
    ),
    "department_manager_headers_alt": build_user_headers(
        DEPARTMENT_MANAGER_ID_ALT, "DepartmentManager",
    ),

    # Trainee fallback — for tests that do NOT exercise the
    # entity-backed ownership check (missing-auth, wrong-role,
    # missing-resource on an admin-scoped operation). Ownership-gated
    # tests MUST use make_trainee_headers(trainee['id']).
    "trainee_fallback_headers": build_user_headers(
        TRAINEE_FALLBACK_ID, "Trainee",
    ),
    "trainee_fallback_headers_alt": build_user_headers(
        TRAINEE_FALLBACK_ID_ALT, "Trainee",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for ownership-gated Trainee calls.
# ---------------------------------------------------------------------------
def make_trainee_headers(trainee_id: str) -> Dict[str, str]:
    """PRD §2.1: "When `X-User-Role` is `Trainee`, `X-User-ID` is the
    `id` of the acting `Trainee` row."

    Pass the actual Trainee.id whenever the request is ownership-gated
    (self-enroll, cancel own enrollment, check-in, exam, evaluation,
    certificate renewal, own-resource reads)."""
    return build_user_headers(trainee_id, "Trainee")


def make_training_admin_headers(user_id: str = TRAINING_ADMIN_ID) -> Dict[str, str]:
    """PRD §2.1: TrainingAdmin X-User-ID is opaque."""
    return build_user_headers(user_id, "TrainingAdmin")


def make_course_designer_headers(user_id: str = COURSE_DESIGNER_ID) -> Dict[str, str]:
    """PRD §2.1: CourseDesigner X-User-ID is opaque."""
    return build_user_headers(user_id, "CourseDesigner")


def make_department_manager_headers(user_id: str = DEPARTMENT_MANAGER_ID) -> Dict[str, str]:
    """PRD §2.1: DepartmentManager X-User-ID is opaque."""
    return build_user_headers(user_id, "DepartmentManager")


__all__ = [
    "TRAINING_ADMIN_ID",
    "TRAINING_ADMIN_ID_ALT",
    "COURSE_DESIGNER_ID",
    "COURSE_DESIGNER_ID_ALT",
    "DEPARTMENT_MANAGER_ID",
    "DEPARTMENT_MANAGER_ID_ALT",
    "TRAINEE_FALLBACK_ID",
    "TRAINEE_FALLBACK_ID_ALT",
    "TEST_USERS",
    "make_trainee_headers",
    "make_training_admin_headers",
    "make_course_designer_headers",
    "make_department_manager_headers",
]
