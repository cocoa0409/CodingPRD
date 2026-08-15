"""Pre-built role headers for the five roles of PRD §2.1.

Every role's X-User-ID is an opaque operator identifier (PRD §2.1: it "is not
tied to any persisted entity"). The single domain use is shipper party binding:
shipper-side calls must carry X-User-ID equal to the agreement's stored
shipper_user_id. The canonical agreement payload stores "shipper-user-1", so
the shared shipper headers below are party-valid for canonical agreements;
use make_shipper_headers() with a different id for wrong-party tests.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import SHIPPER_USER_ID
from .types import UserRole

TEST_USERS = {
    "railroad_contracts_manager_headers": build_user_headers(
        "contracts-mgr-1", UserRole.RAILROAD_CONTRACTS_MANAGER.value
    ),
    # X-User-ID matches the canonical agreement's shipper_user_id, so these
    # headers pass the shipper party-binding check on party-gated endpoints.
    "shipper_facility_manager_headers": build_user_headers(
        SHIPPER_USER_ID, UserRole.SHIPPER_FACILITY_MANAGER.value
    ),
    "railroad_engineer_headers": build_user_headers(
        "engineer-1", UserRole.RAILROAD_ENGINEER.value
    ),
    "safety_inspector_headers": build_user_headers(
        "inspector-1", UserRole.SAFETY_INSPECTOR.value
    ),
    "railroad_service_manager_headers": build_user_headers(
        "service-mgr-1", UserRole.RAILROAD_SERVICE_MANAGER.value
    ),
}


def make_shipper_headers(user_id: str) -> dict:
    """ShipperFacilityManager headers bound to a specific X-User-ID.

    Use the agreement's shipper_user_id for party-gated calls; use any other
    id to exercise the ERR_NOT_AGREEMENT_PARTY path (PRD §2.1).
    """
    return build_user_headers(user_id, UserRole.SHIPPER_FACILITY_MANAGER.value)


def make_headers_without_role(user_id: str) -> dict:
    """Headers carrying X-User-ID but no X-User-Role (malformed user context)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
