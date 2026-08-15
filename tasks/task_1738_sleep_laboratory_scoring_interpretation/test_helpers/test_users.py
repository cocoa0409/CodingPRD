"""Pre-built role headers for every role in the PRD.

Shared constants are safe for opaque roles (Scheduler, DmeCoordinator,
LabDirector) and for tests that do not exercise ownership. For the
entity-backed roles (SleepTechnologist -> Technologist, Scorer -> Scorer,
InterpretingPhysician -> Physician), ownership-gated calls MUST use the
per-instance builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "dme_coordinator_headers": build_user_headers("test-dme-1", "DmeCoordinator"),
    "lab_director_headers": build_user_headers("test-director-1", "LabDirector"),
    # Entity-backed roles: shared fallback for non-ownership tests only.
    "sleep_technologist_headers": build_user_headers(
        "test-tech-1", "SleepTechnologist"),
    "scorer_headers": build_user_headers("test-scorer-1", "Scorer"),
    "physician_headers": build_user_headers(
        "test-physician-1", "InterpretingPhysician"),
}


def make_sleep_technologist_headers(user_id: str) -> dict:
    """For SleepTechnologist (backed by Technologist). Pass the actual
    Technologist.id whenever the call is ownership-gated (e.g. confirming
    that technologist's own staffing assignment)."""
    return build_user_headers(user_id, "SleepTechnologist")


def make_scorer_headers(user_id: str) -> dict:
    """For Scorer (backed by Scorer). Pass the actual Scorer.id whenever
    the call is ownership-gated (starting/submitting that scorer's task)."""
    return build_user_headers(user_id, "Scorer")


def make_physician_headers(user_id: str) -> dict:
    """For InterpretingPhysician (backed by Physician). Pass the actual
    Physician.id whenever the call is ownership-gated (sign/finalize/
    addenda and prescription actions on that physician's reports)."""
    return build_user_headers(user_id, "InterpretingPhysician")
