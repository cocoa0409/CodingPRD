"""Pre-built role headers for every role in the registry PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - Anonymous, CodeOfficer, ProgramAdmin are `opaque` identities: X-User-ID is
#   never compared to any entity id, so a shared constant is the canonical form.
# - registrant_headers is a fallback ONLY for tests that do not exercise
#   ownership (e.g. 401/403/404 on missing resources). Ownership-gated calls
#   must use make_registrant_headers(<registrant_id>).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "registrant_headers": build_user_headers("test-registrant-1", "Registrant"),
    "code_officer_headers": build_user_headers("test-codeofficer-1", "CodeOfficer"),
    "program_admin_headers": build_user_headers("test-programadmin-1", "ProgramAdmin"),
}


def make_registrant_headers(user_id: str) -> dict:
    """For the Registrant role (entity_backed:Registrant). Pass the actual
    Registrant.id as user_id whenever the call is ownership-gated (property
    create/renew/foreclosure, fine pay/dispute, lien pay)."""
    return build_user_headers(user_id, "Registrant")
