"""Pre-built role headers for every role in the PRD (§2.1).

Roles: Anonymous, Guardian, ProgramDirector, BillingAdmin.
- Guardian is entity_backed: its X-User-ID must equal the acting Guardian.id for
  ownership checks to pass. Use make_guardian_headers(guardian_id) for ownership-gated
  calls; the shared constant below is only valid for non-ownership tests.
- Anonymous, ProgramDirector, and BillingAdmin are opaque: X-User-ID is not compared
  to any entity id, so the shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "program_director_headers": build_user_headers("director-1", "ProgramDirector"),
    "billing_admin_headers": build_user_headers("billing-1", "BillingAdmin"),
    # entity_backed Guardian — shared constant is a fallback for non-ownership tests only.
    "guardian_headers": build_user_headers("guardian-fallback-1", "Guardian"),
}


def make_guardian_headers(guardian_id: str) -> dict:
    """For Guardian (entity_backed:Guardian). Pass the actual Guardian.id as user_id
    whenever the call is ownership-gated (enroll, withdraw, create child / form / contact,
    revoke form, request scholarship, and reads of owned resources)."""
    return build_user_headers(guardian_id, "Guardian")
