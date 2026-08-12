"""Pre-built role headers for every role in PRD §2.1.

Identity semantics are contractual: EscrowOfficer / EscrowManager / Auditor are
opaque identifiers; LenderRep is entity-backed — its X-User-ID must equal the
acting lender Party's id whenever the call is identity-gated (quote /
receive-release on a lien whose lienor_party_id is that party).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "officer_headers": build_user_headers("officer-1", "EscrowOfficer"),
    "manager_headers": build_user_headers("mgr-1", "EscrowManager"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # Entity-backed fallback for non-ownership LenderRep calls only. Never use
    # this for quote / receive-release: pass make_lender_headers(party["id"]).
    "lender_headers": build_user_headers("lender-fallback", "LenderRep"),
}


def make_officer_headers(user_id: str) -> dict:
    """EscrowOfficer (opaque identity)."""
    return build_user_headers(user_id, "EscrowOfficer")


def make_manager_headers(user_id: str) -> dict:
    """EscrowManager (opaque identity); distinct ids enable segregation-of-duties setups."""
    return build_user_headers(user_id, "EscrowManager")


def make_lender_headers(party_id: str) -> dict:
    """LenderRep is entity-backed by Party: pass the actual lender Party.id as
    user_id whenever the call is identity-gated (quote / receive-release)."""
    return build_user_headers(party_id, "LenderRep")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor (opaque identity, read-only)."""
    return build_user_headers(user_id, "Auditor")
