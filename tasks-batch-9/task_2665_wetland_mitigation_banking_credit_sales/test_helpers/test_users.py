"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are backed by persisted entities: for Sponsor, Permittee and
IRTMember the X-User-ID header is the id of the acting row, so ownership-gated
calls MUST use the per-instance builders below with the real entity id. The
remaining two roles, IRTChair and ProgramAdmin, are opaque operator identifiers
and the shared constants are their canonical form.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the opaque roles; for the entity-backed
# roles these are a fallback used only by tests that never reach an ownership
# check (unauthenticated / role-authorisation / not-found probes).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "sponsor_headers": build_user_headers("test-sponsor-1", "Sponsor"),
    "permittee_headers": build_user_headers("test-permittee-1", "Permittee"),
    "irt_member_headers": build_user_headers("test-irt-member-1", "IRTMember"),
    "irt_chair_headers": build_user_headers("test-irt-chair-1", "IRTChair"),
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
}


def make_sponsor_headers(sponsor_id: str) -> Dict[str, str]:
    """Headers for a Sponsor. Pass the actual Sponsor id: ownership checks
    compare the targeted bank's sponsor_id to X-User-ID."""
    return build_user_headers(sponsor_id, "Sponsor")


def make_permittee_headers(permittee_id: str) -> Dict[str, str]:
    """Headers for a Permittee. Pass the actual Permittee id: ownership checks
    compare X-User-ID to the sale's permittee_id."""
    return build_user_headers(permittee_id, "Permittee")


def make_irt_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for an IRTMember. Pass the actual IRTMember id: an identifier
    that does not resolve to a seated member record is rejected."""
    return build_user_headers(member_id, "IRTMember")


def make_irt_chair_headers(operator_id: str = "test-irt-chair-1") -> Dict[str, str]:
    """Headers for the IRTChair. The identifier is opaque and is recorded as
    decision_recorded_by on a finalized prospectus."""
    return build_user_headers(operator_id, "IRTChair")


def make_program_admin_headers(operator_id: str = "test-program-admin-1") -> Dict[str, str]:
    """Headers for a ProgramAdmin. The identifier is opaque."""
    return build_user_headers(operator_id, "ProgramAdmin")


PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
IRT_CHAIR = TEST_USERS["irt_chair_headers"]
