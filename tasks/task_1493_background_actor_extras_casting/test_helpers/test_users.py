"""Pre-built role headers for every role in the PRD (§2.1).

`BackgroundActor` is entity-backed: its X-User-ID must be the acting
BackgroundActor record's `id` whenever the call is ownership-gated
(booking accept/decline, voucher dispute, standby withdraw). Use
make_actor_headers(actor_id) for those calls; the shared "actor_headers"
constant is only a fallback for non-ownership reads.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: X-User-ID is never compared to an entity id (PRD §2.1).
    "admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    "director_headers": build_user_headers("dir-1", "CastingDirector"),
    "associate_headers": build_user_headers("assoc-1", "CastingAssociate"),
    "payroll_headers": build_user_headers("pc-1", "PayrollCoordinator"),
    "union_rep_headers": build_user_headers("union-1", "UnionRepresentative"),
    # Entity-backed role: fallback for non-ownership reads ONLY.
    "actor_headers": build_user_headers("actor-unowned-1", "BackgroundActor"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """AgencyAdmin (opaque identity)."""
    return build_user_headers(user_id, "AgencyAdmin")


def make_director_headers(user_id: str = "dir-1") -> dict:
    """CastingDirector (opaque identity; SoD anchor for bump decisions)."""
    return build_user_headers(user_id, "CastingDirector")


def make_associate_headers(user_id: str = "assoc-1") -> dict:
    """CastingAssociate (opaque identity; recorded as requester/issuer)."""
    return build_user_headers(user_id, "CastingAssociate")


def make_payroll_headers(user_id: str = "pc-1") -> dict:
    """PayrollCoordinator (opaque identity; SoD anchor for submit/acknowledge)."""
    return build_user_headers(user_id, "PayrollCoordinator")


def make_union_rep_headers(user_id: str = "union-1") -> dict:
    """UnionRepresentative (opaque identity)."""
    return build_user_headers(user_id, "UnionRepresentative")


def make_actor_headers(user_id: str) -> dict:
    """BackgroundActor (entity_backed:BackgroundActor). Pass the actual
    BackgroundActor.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "BackgroundActor")
