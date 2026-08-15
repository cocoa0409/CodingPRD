"""Role headers for every role in the PRD (§2.1).

All four roles carry an opaque X-User-ID not tied to any persisted entity, so
shared constants are the canonical form. Distinct operator identities matter
for segregation of duties (PRD §2.8): the canonical chain uses cw-1 for
intake, cw-2 for verification, pm-1 for decisions, and fin-1 for payments.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Intake caseworker — opens applications, attaches documents, submits.
    "caseworker_headers": build_user_headers("cw-1", "Caseworker"),
    # Second caseworker — opens and completes verifications (SoD-clean).
    "caseworker2_headers": build_user_headers("cw-2", "Caseworker"),
    # Program manager — policies, sources, decisions, runs, clock.
    "program_manager_headers": build_user_headers("pm-1", "ProgramManager"),
    # Finance officer — payment lifecycle.
    "finance_officer_headers": build_user_headers("fin-1", "FinanceOfficer"),
    # Read-only auditor.
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
}


def make_caseworker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Caseworker")


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_finance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
