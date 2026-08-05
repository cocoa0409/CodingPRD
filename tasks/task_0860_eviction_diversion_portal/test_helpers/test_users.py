"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity ownership (e.g. 400/404/401 checks). Landlord and Tenant are entity_backed:
# their shared entries are fallbacks for NON-ownership tests only; ownership-gated
# calls MUST use the per-instance builders below with the real entity id.
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "Clerk"),
    "landlord_headers": build_user_headers("landlord-1", "Landlord"),
    "tenant_headers": build_user_headers("tenant-1", "Tenant"),
    "mediator_headers": build_user_headers("mediator-1", "Mediator"),
    "judge_headers": build_user_headers("judge-1", "Judge"),
    "program_admin_headers": build_user_headers("program-admin-1", "ProgramAdmin"),
    "sheriff_headers": build_user_headers("sheriff-1", "Sheriff"),
}


# --- Per-instance builders --- #
def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "Clerk")


def make_landlord_headers(user_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the acting Landlord.id whenever
    the call is ownership-gated (filing / plan / lockout on own case)."""
    return build_user_headers(user_id, "Landlord")


def make_tenant_headers(user_id: str) -> dict:
    """For Tenant (entity_backed:Tenant). Pass the acting Tenant.id whenever the
    call is ownership-gated (answer / referral / plan / pay / seal on own case)."""
    return build_user_headers(user_id, "Tenant")


def make_mediator_headers(user_id: str = "mediator-1") -> dict:
    """Opaque, but X-User-ID is recorded as mediator_user_id for SoD enforcement."""
    return build_user_headers(user_id, "Mediator")


def make_judge_headers(user_id: str = "judge-1") -> dict:
    """Opaque, but X-User-ID is recorded as entered_by_user_id / decided_by_user_id
    and read back for segregation-of-duties enforcement."""
    return build_user_headers(user_id, "Judge")


def make_program_admin_headers(user_id: str = "program-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_sheriff_headers(user_id: str = "sheriff-1") -> dict:
    return build_user_headers(user_id, "Sheriff")
