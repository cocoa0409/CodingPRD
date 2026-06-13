"""Pre-built role headers for every role in the PRD (§2.1).

The three roles are Owner (entity_backed), LicensingClerk (opaque), and
AnimalControlOfficer (opaque). For an Owner, X-User-ID is the acting Owner's id,
and ownership checks compare a resource's owning-owner FK to it; for the two
opaque roles, X-User-ID is an arbitrary operator identifier never matched to any
entity id (PRD §2.1).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque clerk/officer roles, and for tests that
# do not exercise Owner ownership (e.g. 401/403/404 on missing or wrong-role
# calls). The entity_backed Owner role below ALSO exposes a per-instance builder
# that MUST be used whenever an Owner call is ownership-gated.
TEST_USERS = {
    # LicensingClerk: opaque identity — shared constant is the canonical form.
    "clerk_headers": build_user_headers("clerk-operator-1", "LicensingClerk"),
    # AnimalControlOfficer: opaque identity — shared constant is canonical.
    "officer_headers": build_user_headers("officer-operator-1", "AnimalControlOfficer"),
    # Owner: entity_backed — this shared constant is a fallback for non-ownership
    # tests only. Ownership-gated calls MUST use make_owner_headers(owner_id).
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_owner_headers(owner_id: str) -> dict:
    """For Owner (entity_backed:Owner). Pass the real Owner.id as user_id for any
    ownership-gated call (submit/attach/renew/pay-penalty/mark-deceased/appeal),
    so the ownership check compares X-User-ID against a live Owner.id (PRD §2.1)."""
    return build_user_headers(owner_id, "Owner")


def make_clerk_headers(user_id: str = "clerk-operator-1") -> dict:
    """For LicensingClerk (opaque). Any non-empty operator id is accepted."""
    return build_user_headers(user_id, "LicensingClerk")


def make_officer_headers(user_id: str = "officer-operator-1") -> dict:
    """For AnimalControlOfficer (opaque). Any non-empty operator id is accepted."""
    return build_user_headers(user_id, "AnimalControlOfficer")


def make_unknown_role_headers() -> dict:
    """An authenticated-looking request whose X-User-Role is not a known role —
    drives ERR_UNAUTHENTICATED (PRD §2.1)."""
    return build_user_headers("intruder-1", "Intruder")
