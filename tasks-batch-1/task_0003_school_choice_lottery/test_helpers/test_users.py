"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
- `Guardian` is the only entity_backed role: X-User-ID must equal the acting
  Family.id. For any ownership-gated call (application create/submit/withdraw,
  offer accept/decline, student create on own family) tests MUST call
  `make_guardian_headers(family_id)` with the actual Family.id captured at
  fixture time, otherwise PRD §2.1's ownership comparison fails and the call
  is rejected with ERR_FORBIDDEN_OWNERSHIP. The shared `guardian_headers`
  fallback is only safe for negative tests that do NOT exercise ownership.
- `DistrictAdmin` is an opaque operator identity (the server records the
  X-User-ID for audit but does not compare it against any persisted entity);
  the shared constant is canonical.
- `Anonymous` is permitted only on POST /lottery/families/register; X-User-ID
  may be absent but X-User-Role is still required per PRD §2.1.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # opaque role — shared constant is canonical.
    "district_admin_headers": build_user_headers("test-district-admin", "DistrictAdmin"),

    # Anonymous role used for public family registration. X-User-ID is opaque
    # and permitted to be absent, but X-User-Role is still required.
    "anonymous_headers": {
        "Content-Type": "application/json",
        "X-User-Role": "Anonymous",
        "X-User-ID": "test-anonymous",
    },

    # entity_backed Guardian — fallback for non-ownership tests only.
    "guardian_headers": build_user_headers("test-guardian-fallback", "Guardian"),
}


def make_district_admin_headers(user_id: str = "test-district-admin") -> dict:
    """Opaque DistrictAdmin headers; user_id is recorded for audit but not
    compared against any entity."""
    return build_user_headers(user_id, "DistrictAdmin")


def make_guardian_headers(family_id: str) -> dict:
    """Per PRD §2.1, X-User-ID for a Guardian MUST equal the acting Family.id.
    Pass the Family.id captured at registration time for every ownership-gated
    Guardian call."""
    return build_user_headers(family_id, "Guardian")


def make_unauthenticated_headers() -> dict:
    """Headers that deliberately omit X-User-Role and X-User-ID to trigger
    ERR_UNAUTHENTICATED (PRD §2.1)."""
    return {"Content-Type": "application/json"}


def make_anonymous_headers() -> dict:
    """Headers for the public family-registration endpoint (PRD §2.1)."""
    return {
        "Content-Type": "application/json",
        "X-User-Role": "Anonymous",
        "X-User-ID": "test-anonymous",
    }
