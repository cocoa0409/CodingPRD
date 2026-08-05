"""Pre-built role headers for every role in the PRD.

ProgramOfficer, Panelist, and GrantsManager are opaque operator identities: their
X-User-ID is an arbitrary string never compared to any entity id, so the shared
constants below are the canonical form.

Subrecipient is entity_backed:Nonprofit — its X-User-ID must be the acting
Nonprofit's id. Ownership-gated calls MUST use make_subrecipient_headers(nonprofit_id);
the shared constant is a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_officer_headers": build_user_headers("po-1", "ProgramOfficer"),
    "grants_manager_headers": build_user_headers("gm-1", "GrantsManager"),
    "panelist_headers": build_user_headers("pan-1", "Panelist"),
    # Fallback only: a string that equals no real Nonprofit id (use for non-ownership tests).
    "subrecipient_headers": build_user_headers("np-fallback", "Subrecipient"),
}


def make_program_officer_headers(user_id: str = "po-1") -> dict:
    """ProgramOfficer (opaque)."""
    return build_user_headers(user_id, "ProgramOfficer")


def make_grants_manager_headers(user_id: str) -> dict:
    """GrantsManager (opaque). user_id drives the drawdown four-eyes SoD rule."""
    return build_user_headers(user_id, "GrantsManager")


def make_panelist_headers(user_id: str) -> dict:
    """Panelist (opaque). user_id drives one-review-per-application uniqueness."""
    return build_user_headers(user_id, "Panelist")


def make_subrecipient_headers(user_id: str) -> dict:
    """Subrecipient (entity_backed:Nonprofit). Pass the acting Nonprofit.id as user_id."""
    return build_user_headers(user_id, "Subrecipient")
