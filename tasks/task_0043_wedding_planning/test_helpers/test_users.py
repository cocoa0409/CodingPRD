"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes two role identity shapes:

- Planner, Couple, and Auditor carry an opaque operator id in X-User-ID:
  "X-User-ID is an opaque operator identifier; it is not the id of any
  persisted entity." Project ownership for Planner is enforced by string-
  equality of X-User-ID against WeddingProject.planner_user_id; Auditor
  ownership of a project at close-time is enforced by string-equality of
  X-User-ID against WeddingProject.auditor_user_id. Because the planner_user_id
  and auditor_user_id are SET on the WeddingProject from the creation
  payload, fixtures that need ownership simply pass the SAME opaque id into
  the create-project payload AND the request headers.

- VendorRep is entity-backed: "X-User-ID is the id of the acting Vendor."
  Vendor-rep ownership checks compare X-User-ID directly to the bound
  Vendor.id. Ownership-gated calls (POST /vendors/{vid}/quotes,
  /quotes/{id}/offer, /quotes/{id}/withdraw, /contracts/{id}/revise,
  /settlement/confirm) MUST use make_vendor_rep_headers(vendor['id']) so
  X-User-ID resolves to a real Vendor.id. Falling back to TEST_USERS
  would defeat every ownership check.

PRD §3.4 segregation-of-duties for change-order approval requires the
approver's X-User-ID to differ from requested_by_user_id. PRD §3.4 settlement
finalize requires the auditor's X-User-ID to differ from confirmed_by_user_id.
PRD §3.1 project-creation segregation requires auditor_user_id to differ
from planner_user_id. We provision multiple distinct opaque ids per role.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Canonical for opaque roles' generic tests; for
# entity_backed VendorRep, the constant is a fallback for tests that do
# NOT exercise an ownership comparison (e.g., 404 not-found, role-mismatch
# RBAC). Whenever a Planner-owned or Auditor-owned project is created in a
# fixture, the SAME opaque id is passed into the payload, so the constant
# is in fact the legitimate owner of those test resources.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # --- Planner (opaque) ----------------------------------------------------
    "planner_headers": build_user_headers("planner-001", "Planner"),
    "planner_headers_alt": build_user_headers("planner-002", "Planner"),
    "planner_headers_third": build_user_headers("planner-003", "Planner"),

    # --- Auditor (opaque) ----------------------------------------------------
    "auditor_headers": build_user_headers("auditor-001", "Auditor"),
    "auditor_headers_alt": build_user_headers("auditor-002", "Auditor"),

    # --- Couple (opaque) -----------------------------------------------------
    "couple_headers": build_user_headers("couple-001", "Couple"),

    # --- VendorRep (entity_backed:Vendor) -- fallback constant ---------------
    # Use only on tests that do NOT exercise an ownership comparison
    # (e.g., RBAC role-not-allowed, ERR_VENDOR_NOT_FOUND with NON_EXISTENT_UUID).
    "vendor_rep_headers_fallback": build_user_headers(
        "vendor-rep-fallback", "VendorRep"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder for the entity-backed VendorRep role.
# Use this whenever the call is ownership-gated against Vendor.id -- create
# quote, offer/withdraw quote, revise contract, confirm settlement, or any
# other call where PRD §2.1 says X-User-ID must equal the bound Vendor.id.
# ---------------------------------------------------------------------------
def make_vendor_rep_headers(vendor_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is VendorRep, X-User-ID is the id of the
    acting Vendor.' Pass the actual Vendor.id minted by POST /vendors so the
    server's vendor-ownership check succeeds."""
    return build_user_headers(vendor_id, "VendorRep")


def make_planner_headers(planner_id: str = "planner-001") -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Planner, X-User-ID is an opaque
    operator identifier.' The same opaque id is recorded as planner_user_id
    on the project at creation, so subsequent calls owned by that planner
    must reuse this id in the header."""
    return build_user_headers(planner_id, "Planner")


def make_auditor_headers(auditor_id: str = "auditor-001") -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Auditor, X-User-ID is again an opaque
    operator identifier.' To close a project, the acting auditor's X-User-ID
    MUST equal WeddingProject.auditor_user_id."""
    return build_user_headers(auditor_id, "Auditor")


def make_couple_headers(couple_id: str = "couple-001") -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Couple, X-User-ID is an opaque
    identifier not tied to any persisted entity.'"""
    return build_user_headers(couple_id, "Couple")


# ---------------------------------------------------------------------------
# Convenience symbolic ids -- the SAME ids embedded in TEST_USERS, exposed
# so fixtures can put them into the create-project payload as
# planner_user_id / auditor_user_id and still have ownership succeed.
# ---------------------------------------------------------------------------
PLANNER_ID = "planner-001"
PLANNER_ID_ALT = "planner-002"
PLANNER_ID_THIRD = "planner-003"
AUDITOR_ID = "auditor-001"
AUDITOR_ID_ALT = "auditor-002"
COUPLE_ID = "couple-001"


__all__ = [
    "TEST_USERS",
    "make_vendor_rep_headers",
    "make_planner_headers",
    "make_auditor_headers",
    "make_couple_headers",
    "PLANNER_ID",
    "PLANNER_ID_ALT",
    "PLANNER_ID_THIRD",
    "AUDITOR_ID",
    "AUDITOR_ID_ALT",
    "COUPLE_ID",
]
