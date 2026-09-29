"""Pre-built role headers for every role named in PRD §2.1.

Three roles are entity-backed: for ``PlantDispatcher`` the ``X-User-ID`` is the
acting ``Plant`` id, for ``TransportManager`` it is the acting ``Hauler`` id,
and for ``SetCrewLead`` it is the acting ``SetCrew`` id.  Ownership-gated calls
MUST therefore use the matching per-instance builder below, passing the real
entity id.  The shared constants are only safe for opaque roles and for calls
that never reach an ownership check.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used by the four non-entity-backed roles.
NETWORK_ADMIN_USER_ID = "admin-net-1"
PERMIT_DESK_USER_ID = "permit-desk-1"
CLAIMS_ADJUSTER_USER_ID = "claims-adj-1"
SITE_INSPECTOR_USER_ID = "insp-site-1"
ANCHOR_INSPECTOR_USER_ID = "insp-anchor-1"
FINAL_INSPECTOR_USER_ID = "insp-final-1"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "network_admin_headers": build_user_headers(NETWORK_ADMIN_USER_ID, "NetworkAdmin"),
    "permit_desk_headers": build_user_headers(PERMIT_DESK_USER_ID, "PermitDesk"),
    "claims_adjuster_headers": build_user_headers(
        CLAIMS_ADJUSTER_USER_ID, "ClaimsAdjuster"
    ),
    "installation_inspector_headers": build_user_headers(
        SITE_INSPECTOR_USER_ID, "InstallationInspector"
    ),
    # Entity-backed roles — fallback for tests that never reach ownership.
    "plant_dispatcher_headers": build_user_headers(
        "test-plant-dispatcher-1", "PlantDispatcher"
    ),
    "transport_manager_headers": build_user_headers(
        "test-transport-manager-1", "TransportManager"
    ),
    "set_crew_lead_headers": build_user_headers("test-set-crew-lead-1", "SetCrewLead"),
}


def make_network_admin_headers(user_id=NETWORK_ADMIN_USER_ID):
    """For NetworkAdmin (opaque operator identifier)."""
    return build_user_headers(user_id, "NetworkAdmin")


def make_permit_desk_headers(user_id=PERMIT_DESK_USER_ID):
    """For PermitDesk (opaque operator identifier)."""
    return build_user_headers(user_id, "PermitDesk")


def make_claims_adjuster_headers(user_id=CLAIMS_ADJUSTER_USER_ID):
    """For ClaimsAdjuster (opaque operator identifier)."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_inspector_headers(user_id=SITE_INSPECTOR_USER_ID):
    """For InstallationInspector.

    The identifier is opaque but recorded: a site-readiness verdict stores it
    in ``last_inspector_user_id``, an anchoring review stores it in
    ``certifier_user_id``, and a final inspection stores it in
    ``final_inspector_user_id``.  Pass distinct identifiers when a test needs
    two different inspectors.
    """
    return build_user_headers(user_id, "InstallationInspector")


def make_plant_dispatcher_headers(plant_id):
    """For PlantDispatcher (entity-backed on Plant). Pass the real Plant id."""
    return build_user_headers(plant_id, "PlantDispatcher")


def make_transport_manager_headers(hauler_id):
    """For TransportManager (entity-backed on Hauler). Pass the real Hauler id."""
    return build_user_headers(hauler_id, "TransportManager")


def make_set_crew_lead_headers(set_crew_id):
    """For SetCrewLead (entity-backed on SetCrew). Pass the real SetCrew id."""
    return build_user_headers(set_crew_id, "SetCrewLead")


def headers_for_role(role, user_id):
    """Build headers for an arbitrary role/user pair, for role-matrix tests."""
    return build_user_headers(user_id, role)
