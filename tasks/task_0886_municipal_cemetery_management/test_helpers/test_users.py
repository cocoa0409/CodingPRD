"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Five roles carry an OPAQUE identity: X-User-ID is an operator id not tied to
# any entity. The RightHolder role is ENTITY-BACKED: X-User-ID must equal the
# acting RightHolder.id, so ownership-gated calls must use make_right_holder_headers().
TEST_USERS = {
    "registrar_headers": build_user_headers("reg-1", "Registrar"),
    "grounds_foreman_headers": build_user_headers("gf-1", "GroundsForeman"),
    "finance_officer_headers": build_user_headers("fin-1", "FinanceOfficer"),
    "health_officer_headers": build_user_headers("health-1", "HealthOfficer"),
    "cemetery_director_headers": build_user_headers("dir-1", "CemeteryDirector"),
    # Fallback for non-ownership tests only (e.g. 403/404 shapes). Ownership-gated
    # calls MUST use make_right_holder_headers(holder_id).
    "right_holder_headers": build_user_headers("holder-fallback", "RightHolder"),
}


def make_right_holder_headers(user_id: str) -> dict:
    """For RightHolder (entity_backed:RightHolder). Pass the acting RightHolder.id
    whenever the call is ownership-gated (accept-transfer, record-consent,
    marker application on an owned deed)."""
    return build_user_headers(user_id, "RightHolder")


def make_registrar_headers(user_id: str) -> dict:
    """Registrar with a specific opaque X-User-ID (for segregation-of-duties tests)."""
    return build_user_headers(user_id, "Registrar")


def make_finance_officer_headers(user_id: str) -> dict:
    """FinanceOfficer with a specific opaque X-User-ID (for maker-checker void tests)."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_cemetery_director_headers(user_id: str) -> dict:
    """CemeteryDirector with a specific opaque X-User-ID (for approve/execute SoD tests)."""
    return build_user_headers(user_id, "CemeteryDirector")
