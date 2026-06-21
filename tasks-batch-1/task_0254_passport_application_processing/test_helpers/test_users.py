"""Pre-built role headers for every role in the PRD.

All three roles are entity-backed: X-User-ID must be the id of a persisted
Applicant / AcceptanceAgent / Adjudicator record for ownership and SoD checks
to pass. The shared TEST_USERS constants are safe ONLY for tests that do not
exercise ownership (e.g., 403-forbidden-by-role, 401-missing-auth). Any call
that is ownership- or SoD-gated MUST use the per-instance builder with the real
entity id (see make_*_headers below).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — for role-denial / auth-missing tests where the X-User-ID
# never needs to match a real owning entity.
TEST_USERS = {
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "acceptance_agent_headers": build_user_headers("test-agent-1", "AcceptanceAgent"),
    "adjudicator_headers": build_user_headers("test-adjudicator-1", "Adjudicator"),
}


def make_applicant_headers(applicant_id: str) -> dict:
    """For the Applicant role (entity_backed:Applicant). Pass the real Applicant.id
    so ownership checks on the applicant's applications/documents/photos/fees pass."""
    return build_user_headers(applicant_id, "Applicant")


def make_agent_headers(agent_id: str) -> dict:
    """For the AcceptanceAgent role (entity_backed:AcceptanceAgent). Pass the real
    AcceptanceAgent.id so verify/begin-verification SoD checks resolve correctly."""
    return build_user_headers(agent_id, "AcceptanceAgent")


def make_adjudicator_headers(adjudicator_id: str) -> dict:
    """For the Adjudicator role (entity_backed:Adjudicator). Pass the real
    Adjudicator.id so the adjudicate SoD check compares against the right person."""
    return build_user_headers(adjudicator_id, "Adjudicator")
