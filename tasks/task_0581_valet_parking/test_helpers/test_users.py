"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   - Supervisor and Cashier identities are OPAQUE operator ids (§2.1): a shared
#     constant is the canonical form.
#   - Attendant is entity_backed:Attendant. The shared constant below is a fallback
#     for Attendant calls that do NOT hit an ownership check (the only ownership-gated
#     Attendant endpoint is POST /valet/shifts/{id}/tips, §2.1/§3.4). For that call,
#     use make_attendant_headers(<the shift's attendant_id>).
TEST_USERS = {
    "supervisor_headers": build_user_headers("op-supervisor-1", "Supervisor"),
    "cashier_headers": build_user_headers("op-cashier-1", "Cashier"),
    # Fallback Attendant header for non-ownership calls only.
    "attendant_headers": build_user_headers("op-attendant-fallback", "Attendant"),
    # Unknown role — triggers ERR_UNAUTHENTICATED (§2.1: role not one of the recognized roles).
    "unknown_role_headers": build_user_headers("op-ghost-1", "Ghost"),
}


def make_attendant_headers(attendant_id: str) -> dict:
    """For the Attendant role (entity_backed:Attendant). Pass the acting Attendant.id
    as X-User-ID whenever the call is ownership-gated — recording tips into a shift
    requires X-User-ID == shift.attendant_id (§2.1/§3.4). Falling back to the shared
    constant for an ownership-gated call reproduces the canonical bug: X-User-ID would
    never equal any real Attendant.id and every ownership check would reject."""
    return build_user_headers(attendant_id, "Attendant")
