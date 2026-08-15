"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (DealerAdmin, ProjectCoordinator, Homeowner, GrantOfficer,
Regulator) use a shared constant: their X-User-ID is never compared to a
persisted entity id (except Homeowner, which is compared to
Property.owner_user_id — the shared constant's id matches the canonical
owner id used by the fixtures).

Entity-backed roles (Surveyor, Installer, Inspector -> Technician;
Contractor -> Contractor) MUST use the per-instance builders with the
actual entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "dealer_admin_headers": build_user_headers("test-admin-1", "DealerAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "ProjectCoordinator"),
    "grant_officer_headers": build_user_headers("test-grant-officer-1", "GrantOfficer"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
    # Homeowner is opaque but ownership-gated against Property.owner_user_id;
    # the shared constant carries the canonical owner id used by factories.
    "homeowner_headers": build_user_headers(TEST_DEFAULTS["OWNER_USER_ID"], "Homeowner"),
    "other_homeowner_headers": build_user_headers("u-other", "Homeowner"),
    # Entity-backed roles — shared constants are fallbacks for
    # non-ownership-gated calls only.
    "surveyor_headers": build_user_headers("test-surveyor-1", "Surveyor"),
    "installer_headers": build_user_headers("test-installer-1", "Installer"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_surveyor_headers(technician_id: str) -> dict:
    """Surveyor headers bound to a real Technician.id (ownership-gated calls)."""
    return build_user_headers(technician_id, "Surveyor")


def make_installer_headers(technician_id: str) -> dict:
    """Installer headers bound to a real Technician.id (ownership-gated calls)."""
    return build_user_headers(technician_id, "Installer")


def make_inspector_headers(technician_id: str) -> dict:
    """Inspector headers bound to a real Technician.id (ownership-gated calls)."""
    return build_user_headers(technician_id, "Inspector")


def make_contractor_headers(contractor_id: str) -> dict:
    """Contractor headers bound to a real Contractor.id (ownership-gated calls)."""
    return build_user_headers(contractor_id, "Contractor")


def make_homeowner_headers(user_id: str) -> dict:
    """Homeowner headers; pass Property.owner_user_id for ownership-gated calls."""
    return build_user_headers(user_id, "Homeowner")
