"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (PRD Section 2.1): ``Resident`` (X-User-ID must
equal the acting resident's own id) and ``Vendor`` (X-User-ID must equal the
acting vendor's own id). Every ownership-gated call MUST use the per-instance
builder with the real entity id. ``PropertyManager`` and ``FrontDesk`` are
opaque staff roles whose X-User-ID is never compared to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque staff roles and for tests that do not
# exercise ownership (404-on-missing, 422-on-bad-payload, unauthorized-role).
TEST_USERS = {
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    # Fallback constants — only for non-ownership scenarios.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    # An unrecognized role name — used to exercise ERR_UNAUTHENTICATED.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


# --- Per-instance builders --------------------------------------------------
def make_property_manager_headers(user_id: str) -> dict:
    """For PropertyManager (opaque). Use a distinct user_id to drive/observe
    the segregation-of-duties trail (triaged_by vs invoice_approved_by)."""
    return build_user_headers(user_id, "PropertyManager")


def make_front_desk_headers(user_id: str) -> dict:
    """For FrontDesk (opaque)."""
    return build_user_headers(user_id, "FrontDesk")


def make_resident_headers(user_id: str) -> dict:
    """For Resident (entity_backed:Resident). Pass the actual Resident.id as
    user_id on every ownership-gated call (booking create/cancel, register,
    guest passes, package pickup, survey responses, service requests)."""
    return build_user_headers(user_id, "Resident")


def make_vendor_headers(user_id: str) -> dict:
    """For Vendor (entity_backed:Vendor). Pass the actual Vendor.id as user_id
    on every ownership-gated call (start/complete a service request)."""
    return build_user_headers(user_id, "Vendor")
