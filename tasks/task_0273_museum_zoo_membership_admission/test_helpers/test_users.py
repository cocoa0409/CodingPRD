"""Pre-built role headers for every role in the PRD (§2.1).

Patron is entity-backed: a Patron caller's X-User-ID is the id of the acting
Patron, and ownership checks compare it to the resource's owning patron. Every
ownership-gated Patron call MUST therefore use make_patron_headers(patron_id)
with the real Patron.id. The shared TEST_USERS["patron_headers"] constant is a
fallback only for tests that do NOT exercise ownership (e.g. role-denial probes).

BoxOffice, GateScanner, and MembershipAdmin are opaque operator identifiers not
tied to any persisted entity, so their shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed:Patron — shared constant for non-ownership tests only.
    "patron_headers": build_user_headers("test-patron-shared", "Patron"),
    # opaque operational roles — shared constant is canonical.
    "box_office_headers": build_user_headers("test-box-office", "BoxOffice"),
    "gate_scanner_headers": build_user_headers("test-gate-scanner", "GateScanner"),
    "membership_admin_headers": build_user_headers("test-membership-admin", "MembershipAdmin"),
}


def make_patron_headers(patron_id: str) -> dict:
    """Headers for a Patron acting on their own resource. Pass the actual
    Patron.id as patron_id whenever the call is ownership-gated."""
    return build_user_headers(patron_id, "Patron")


def make_box_office_headers(user_id: str = "test-box-office") -> dict:
    return build_user_headers(user_id, "BoxOffice")


def make_gate_scanner_headers(user_id: str = "test-gate-scanner") -> dict:
    return build_user_headers(user_id, "GateScanner")


def make_membership_admin_headers(user_id: str = "test-membership-admin") -> dict:
    return build_user_headers(user_id, "MembershipAdmin")
