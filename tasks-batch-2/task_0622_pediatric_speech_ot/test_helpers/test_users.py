"""Pre-built role headers for every role in the PRD (§2.1).

The four roles, spelled exactly: ClinicAdmin, SchedulingCoordinator, Evaluator,
Therapist.

- ClinicAdmin and SchedulingCoordinator have OPAQUE identities — X-User-ID is an
  operator identifier never compared to any entity id; the shared constant is the
  canonical form for these roles.
- Evaluator and Therapist are entity_backed:Therapist — X-User-ID is the id of the
  acting Therapist record. Ownership checks compare a resource's therapist
  foreign-key to X-User-ID, so any ownership/authorship-sensitive call MUST use the
  per-instance builder make_evaluator_headers / make_therapist_headers with the
  real Therapist.id. The shared TEST_USERS constants for these two roles are a
  fallback for tests that do not exercise ownership (e.g. 401/403/404 checks).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "clinic_admin_headers": build_user_headers("test-clinic-admin-1", "ClinicAdmin"),
    "scheduling_coordinator_headers": build_user_headers(
        "test-scheduling-coordinator-1", "SchedulingCoordinator"),
    # entity_backed roles — shared constant is a fallback for non-ownership tests.
    "evaluator_headers": build_user_headers("test-evaluator-1", "Evaluator"),
    "therapist_headers": build_user_headers("test-therapist-1", "Therapist"),
}


def make_evaluator_headers(user_id: str) -> dict:
    """For Evaluator (entity_backed:Therapist). Pass the acting Therapist.id as
    user_id; the evaluation's evaluator_id is written from this X-User-ID."""
    return build_user_headers(user_id, "Evaluator")


def make_therapist_headers(user_id: str) -> dict:
    """For Therapist (entity_backed:Therapist). Pass the acting Therapist.id as
    user_id; a home program's assigned_by_therapist_id is written from this
    X-User-ID, and ownership checks compare against it."""
    return build_user_headers(user_id, "Therapist")
