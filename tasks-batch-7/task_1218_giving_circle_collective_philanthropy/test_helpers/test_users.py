"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque roles (PRD §2.1): CircleAdmin and FinanceOfficer identifiers are not
# tied to any persisted entity. The shared admin id "admin-1" is recorded as
# requested_by_user_id on payouts created by an award advance (PRD §3.7).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "CircleAdmin"),
    "finance_headers": build_user_headers("fin-1", "FinanceOfficer"),
    # Fallbacks for non-ownership calls only (e.g. 400/404 probes). Member and
    # GranteeContact are entity-backed; ownership-gated calls MUST use the
    # per-instance builders below with the real Member.id / Nonprofit.id.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "grantee_headers": build_user_headers("test-grantee-1", "GranteeContact"),
}

# No X-User-ID / X-User-Role at all (PRD §2.1 authentication failure probe).
EMPTY_HEADERS = {}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """CircleAdmin is opaque; a distinct id only matters for segregation of
    duties on payouts (PRD §3.7)."""
    return build_user_headers(user_id, "CircleAdmin")


def make_finance_headers(user_id: str = "fin-1") -> dict:
    """FinanceOfficer is opaque; the id participates in the
    segregation-of-duties comparison on payout approval (PRD §3.7)."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_member_headers(user_id: str) -> dict:
    """Member is entity-backed: X-User-ID must equal the acting Member.id
    (PRD §2.1)."""
    return build_user_headers(user_id, "Member")


def make_grantee_headers(user_id: str) -> dict:
    """GranteeContact is entity-backed: X-User-ID must equal the acting
    Nonprofit.id (PRD §2.1)."""
    return build_user_headers(user_id, "GranteeContact")
