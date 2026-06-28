"""Pre-built role headers for every role in the PRD.

FrontDesk and FinanceManager are opaque operator identities (X-User-ID not tied to any
entity), so a shared constant is the canonical form for them. Stylist and Member are
entity-backed: ownership checks compare X-User-ID to the appointment's stylist_id /
member_id, so callers that exercise ownership MUST use the per-instance builders below
with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "front_desk_headers": build_user_headers("front-desk-1", "FrontDesk"),
    "finance_manager_headers": build_user_headers("finance-manager-1", "FinanceManager"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only
    # (e.g. RBAC role-denial checks where no ownership comparison is reached).
    "stylist_headers": build_user_headers("stylist-shared-1", "Stylist"),
    "member_headers": build_user_headers("member-shared-1", "Member"),
}


def make_stylist_headers(stylist_id: str) -> dict:
    """For the Stylist role (entity_backed:Stylist). Pass the actual Stylist.id as
    user_id whenever the call is ownership-gated (start / complete an assigned
    appointment)."""
    return build_user_headers(stylist_id, "Stylist")


def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (book / cancel own appointment,
    read own records)."""
    return build_user_headers(member_id, "Member")
