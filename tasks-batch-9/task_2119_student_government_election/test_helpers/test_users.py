"""Pre-built role headers for every role in the PRD (§2.1).

Three roles carry opaque identities: `ElectionCommissioner`, `FacultyAdvisor`
and `Registrar` supply an operator identifier that is never compared to any
entity `id`, so the shared constants below are the canonical form for them.

The two student-facing roles are entity-backed: a `Candidate`'s `X-User-ID` is
the `id` of the acting `Student`, and so is a `StudentVoter`'s. Every
ownership-gated call MUST therefore be issued with the per-instance builder,
passing the real `Student.id`; the shared constants for those two roles are
only safe on probes that never reach the ownership rung (missing headers,
role-denial and unknown-identifier checks).
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import ADVISOR_ID, COMMISSIONER_ID, REGISTRAR_ID, SECOND_ADVISOR_ID

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "commissioner_headers": build_user_headers(COMMISSIONER_ID, "ElectionCommissioner"),
    "advisor_headers": build_user_headers(ADVISOR_ID, "FacultyAdvisor"),
    "second_advisor_headers": build_user_headers(SECOND_ADVISOR_ID, "FacultyAdvisor"),
    "registrar_headers": build_user_headers(REGISTRAR_ID, "Registrar"),
    # Entity-backed roles — fallback for probes that never reach ownership.
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
    "student_voter_headers": build_user_headers("test-voter-1", "StudentVoter"),
}


def make_candidate_headers(student_id: str) -> dict:
    """Headers for a `Candidate`. Pass the acting `Student.id` — ownership checks
    compare a candidacy's `student_id` to `X-User-ID`."""
    return build_user_headers(student_id, "Candidate")


def make_student_voter_headers(student_id: str) -> dict:
    """Headers for a `StudentVoter`. Pass the acting `Student.id` — ownership
    checks compare a signature's `signer_student_id`, a vote's `student_id` and
    the drafter of a referendum to `X-User-ID`."""
    return build_user_headers(student_id, "StudentVoter")


def make_commissioner_headers(operator_id: str) -> dict:
    """Headers for an `ElectionCommissioner` operator (opaque identity)."""
    return build_user_headers(operator_id, "ElectionCommissioner")


def make_advisor_headers(operator_id: str) -> dict:
    """Headers for a `FacultyAdvisor` operator (opaque identity). Segregation of
    duties compares this identifier against `certified_by_user_id` and against a
    cited case's `adjudicated_by_user_id`."""
    return build_user_headers(operator_id, "FacultyAdvisor")


def make_registrar_headers(operator_id: str) -> dict:
    """Headers for a `Registrar` operator (opaque identity)."""
    return build_user_headers(operator_id, "Registrar")
