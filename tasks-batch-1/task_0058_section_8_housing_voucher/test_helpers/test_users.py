"""Pre-built role headers for every role the PRD recognises (PRD Section 2.1).

The PRD recognises five roles. Four of them — ``ProgramAdmin``, ``Caseworker``,
``Inspector``, ``PortabilityCoordinator`` — treat ``X-User-ID`` as an opaque
operator identifier that is not compared against any entity id; the shared
constants below are the canonical form for those roles.

The ``Landlord`` role is entity-backed: PRD Section 2.1 requires ``X-User-ID``
to be the ``id`` of the acting ``Landlord`` entity, and any ownership check on
a resource that references a landlord compares that id. Any landlord-role call
that must pass an ownership check MUST use ``make_landlord_headers(landlord_id)``
with the actual landlord's id; falling back to the shared constant reproduces
the canonical bug where every ownership check rejects every request.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque-identity roles — shared constants are the canonical form.
    "program_admin_headers": build_user_headers("program-admin-test-1", "ProgramAdmin"),
    "caseworker_headers": build_user_headers("caseworker-test-1", "Caseworker"),
    "inspector_headers": build_user_headers("inspector-test-1", "Inspector"),
    "portability_coordinator_headers": build_user_headers(
        "portability-coordinator-test-1", "PortabilityCoordinator",
    ),
    # Landlord fallback — used only for non-ownership tests (e.g. forbidden-role
    # rejections) where the literal X-User-ID need not match a real landlord id.
    "landlord_headers": build_user_headers("landlord-test-fallback", "Landlord"),
}


def make_landlord_headers(landlord_id: str) -> dict:
    """For Landlord-role calls whose success depends on the caller owning the
    resource (PRD Section 2.1: ``X-User-ID`` is the acting Landlord's id). Pass
    the landlord's id so the ownership check passes."""
    return build_user_headers(landlord_id, "Landlord")
