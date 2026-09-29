"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque operator identifier that the server never compares
to any entity id — for those the shared constant below is the canonical form.
Three roles are entity-backed (`Exhibitor` is a `Rider`, `Judge` and `Steward`
are an `Official`) and their `X-User-ID` must resolve to a real stored row, so
callers MUST build their headers with the per-instance builders and pass the
actual entity's `id`.
"""
from prd_bench_local_runner.testing import build_user_headers

SHOW_SECRETARY_USER_ID = "sec-office-1"
FEDERATION_OFFICER_USER_ID = "fed-officer-1"
RING_MASTER_USER_ID = "ring-master-1"
GROUNDS_MANAGER_USER_ID = "grounds-manager-1"

TEST_USERS = {
    # opaque roles — the shared constant is the canonical form
    "show_secretary_headers": build_user_headers(SHOW_SECRETARY_USER_ID, "ShowSecretary"),
    "federation_officer_headers": build_user_headers(FEDERATION_OFFICER_USER_ID, "FederationOfficer"),
    "ring_master_headers": build_user_headers(RING_MASTER_USER_ID, "RingMaster"),
    "grounds_manager_headers": build_user_headers(GROUNDS_MANAGER_USER_ID, "GroundsManager"),
    # entity-backed roles — fallbacks for tests that never reach an ownership or
    # identity-resolution check (they resolve to no row on purpose).
    "exhibitor_headers": build_user_headers("unresolvable-exhibitor", "Exhibitor"),
    "judge_headers": build_user_headers("unresolvable-judge", "Judge"),
    "steward_headers": build_user_headers("unresolvable-steward", "Steward"),
}

NO_AUTH_HEADERS: dict = {}


def make_exhibitor_headers(rider_id: str) -> dict:
    """For `Exhibitor`; pass the acting `Rider`'s `id` (PRD §2.1)."""
    return build_user_headers(rider_id, "Exhibitor")


def make_judge_headers(official_id: str) -> dict:
    """For `Judge`; pass the acting `Official`'s `id` (PRD §2.1)."""
    return build_user_headers(official_id, "Judge")


def make_steward_headers(official_id: str) -> dict:
    """For `Steward`; pass the acting `Official`'s `id` (PRD §2.1)."""
    return build_user_headers(official_id, "Steward")


def make_headers(role: str, user_id: str) -> dict:
    """Arbitrary role/id pair — used by the role-authorisation sweeps."""
    return build_user_headers(user_id, role)


#: Canonical opaque identifier for each non-entity-backed role.
OPAQUE_USER_IDS = {
    "ShowSecretary": SHOW_SECRETARY_USER_ID,
    "FederationOfficer": FEDERATION_OFFICER_USER_ID,
    "RingMaster": RING_MASTER_USER_ID,
    "GroundsManager": GROUNDS_MANAGER_USER_ID,
}
