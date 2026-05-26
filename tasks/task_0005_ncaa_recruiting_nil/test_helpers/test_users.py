"""Pre-built role headers for every role the PRD recognises (PRD §2.1).

PRD §2.1 recognises five roles. Four of them — `ComplianceOfficer`, `Coach`,
`NILReviewer`, `EligibilityCenter` — treat `X-User-ID` as an opaque operator
identifier; the shared constants below are safe for tests on those roles when
the request does NOT exercise an identity-pinned check.

The `StudentAthlete` role is entity-backed: PRD §2.1 requires `X-User-ID` to
equal the `id` of the acting `StudentAthlete` row. Any StudentAthlete-role
call against a resource owned by that athlete (NIL deal proposal, scholarship
offer accept/decline, transfer portal entry/withdraw) MUST use
``make_student_athlete_headers(athlete_id)`` so the ownership check passes;
falling back to the shared constant reproduces the canonical bug where every
ownership check rejects every request.

For `Coach`, opaque-id binding matters too: a coach's withdraw or send on an
offer requires the acting `X-User-ID` to match the `X-User-ID` that stamped
the offer (PRD §2.1). Tests that need a specific coach identity use
``make_coach_headers(coach_user_id)``.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque-identity roles — shared constants are the canonical form for
    # tests that don't exercise identity pinning.
    "compliance_officer_headers": build_user_headers(
        "compliance-officer-test-1", "ComplianceOfficer",
    ),
    "coach_headers": build_user_headers("coach-test-1", "Coach"),
    "nil_reviewer_headers": build_user_headers(
        "nil-reviewer-test-1", "NILReviewer",
    ),
    "eligibility_center_headers": build_user_headers(
        "eligibility-center-test-1", "EligibilityCenter",
    ),
    # StudentAthlete fallback — used only for tests where the rejection IS
    # "not the owner" (so the literal X-User-ID need not match any real id).
    "student_athlete_headers": build_user_headers(
        "student-athlete-test-fallback", "StudentAthlete",
    ),
}


# ─── Per-instance builders ──────────────────────────────


def make_student_athlete_headers(athlete_id: str) -> dict:
    """For StudentAthlete-role calls whose success depends on the caller
    owning the resource (PRD §2.1: ``X-User-ID`` is the `id` of the acting
    `StudentAthlete` row). Pass the athlete's id so the ownership check
    passes."""
    return build_user_headers(athlete_id, "StudentAthlete")


def make_coach_headers(coach_user_id: str) -> dict:
    """For Coach-role calls where the offer's coach affiliation matters
    (PRD §2.1, §3.4): the coach's `X-User-ID` must match the one stamped
    on the offer at create time, otherwise ``ERR_COACH_PROGRAM_MISMATCH``."""
    return build_user_headers(coach_user_id, "Coach")


def make_nil_reviewer_headers(reviewer_user_id: str) -> dict:
    """For NILReviewer-role calls where the approver's identity matters
    for segregation-of-duties (PRD §3.5): the approver's `X-User-ID` must
    differ from every prior submitter / revision-requester of the deal."""
    return build_user_headers(reviewer_user_id, "NILReviewer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Per-instance builder for the opaque ComplianceOfficer role."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_eligibility_center_headers(user_id: str) -> dict:
    """Per-instance builder for the opaque EligibilityCenter role."""
    return build_user_headers(user_id, "EligibilityCenter")
