"""Pre-built role headers for every role in the PRD (§2.1).

FrontDesk and Biller are opaque operator identities — X-User-ID is not tied to any
persisted entity, so the shared constant is the canonical form. Optometrist and
Optician are entity_backed:Provider — ownership checks compare X-User-ID to the
resource's provider foreign key (an encounter's provider_id, a lab order's
dispensing optician), so use the per-instance builders with the real Provider.id
whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — canonical shared constants.
    "front_desk_headers": build_user_headers("front-desk-1", "FrontDesk"),
    "biller_headers": build_user_headers("biller-1", "Biller"),
    # entity_backed roles — shared constants are fallbacks for non-ownership tests
    # (e.g. 404-on-missing, role-denial). For ownership-gated calls, use the
    # per-instance builders below with the real Provider.id.
    "optometrist_headers": build_user_headers("optometrist-fallback-1", "Optometrist"),
    "optician_headers": build_user_headers("optician-fallback-1", "Optician"),
}


def make_front_desk_headers(user_id: str = "front-desk-1") -> dict:
    """FrontDesk is opaque; user_id is an operator identifier, not an entity id."""
    return build_user_headers(user_id, "FrontDesk")


def make_biller_headers(user_id: str = "biller-1") -> dict:
    """Biller is opaque; user_id is an operator identifier, not an entity id."""
    return build_user_headers(user_id, "Biller")


def make_optometrist_headers(provider_id: str) -> dict:
    """For Optometrist (entity_backed:Provider). Pass the acting Provider.id as
    user_id whenever the call is ownership-gated (e.g. finalize an encounter the
    optometrist conducts)."""
    return build_user_headers(provider_id, "Optometrist")


def make_optician_headers(provider_id: str) -> dict:
    """For Optician (entity_backed:Provider). Pass the acting Provider.id as
    user_id; this identity is recorded as the dispensing optician on a lab order."""
    return build_user_headers(provider_id, "Optician")


def make_unknown_role_headers(user_id: str = "nobody-1") -> dict:
    """An unrecognized role — drives ERR_UNAUTHENTICATED (PRD §2.1)."""
    return build_user_headers(user_id, "NoSuchRole")
