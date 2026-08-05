"""Pre-built role headers for every role in the PRD (§2.1 role model).

Two roles are entity-backed (Resident, Carrier): their X-User-ID must be the id of the
acting persisted record for ownership-gated calls. Use the per-instance builders
(make_resident_headers / make_carrier_headers) with the real entity id in those cases.
The other three roles (PropertyManager, ConciergeStaff, PmsIntegration) are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    "pm_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "concierge_headers": build_user_headers("test-concierge-1", "ConciergeStaff"),
    "pms_headers": build_user_headers("test-pms-1", "PmsIntegration"),
    # Entity-backed fallbacks: valid only for non-ownership tests (e.g. 403/404 negatives).
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "carrier_headers": build_user_headers("test-carrier-1", "Carrier"),
}


# ─── Opaque-role builders (control the recorded X-User-ID, e.g. for SoD dual-control) ─────
def make_pm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_concierge_headers(user_id: str) -> dict:
    """For ConciergeStaff. The X-User-ID is recorded into return_initiated_by_user_id, so
    dual-control (SoD) tests must be able to pin it."""
    return build_user_headers(user_id, "ConciergeStaff")


def make_pms_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PmsIntegration")


# ─── Entity-backed builders (mandatory for ownership-gated calls) ─────────────────────────
def make_resident_headers(user_id: str) -> dict:
    """For Resident (entity_backed:Resident). Pass the actual Resident.id whenever the call
    is ownership-gated (own-package pickup, own retail-return dropoff)."""
    return build_user_headers(user_id, "Resident")


def make_carrier_headers(user_id: str) -> dict:
    """For Carrier (entity_backed:Carrier). Pass the actual Carrier.id whenever the call is
    ownership-gated (collecting a staged return, logging a package as that carrier)."""
    return build_user_headers(user_id, "Carrier")
