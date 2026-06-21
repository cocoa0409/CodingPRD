"""Pre-built role headers for every role in the PRD (Travel Agency Tour Booking API).

Per PRD §2.1: AgencyAdmin and TravelAgent carry an OPAQUE X-User-ID never compared
against any entity id, so their shared constants are the canonical form for every call.
Customer and Supplier carry an ENTITY-BACKED identity: X-User-ID must equal the acting
Customer.id / Supplier.id. Ownership-gated calls MUST use the per-instance builders
(make_customer_headers / make_supplier_headers) with the real entity id; the shared
constants below are only safe for non-ownership tests (e.g. 400/404 negatives).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "agency_admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    "travel_agent_headers": build_user_headers("agent-1", "TravelAgent"),
    # entity_backed fallbacks — non-ownership tests only.
    "customer_headers": build_user_headers("customer-1", "Customer"),
    "supplier_headers": build_user_headers("supplier-1", "Supplier"),
}


def make_agency_admin_headers(user_id: str) -> dict:
    """AgencyAdmin (opaque). user_id may be any operator identifier."""
    return build_user_headers(user_id, "AgencyAdmin")


def make_travel_agent_headers(user_id: str) -> dict:
    """TravelAgent (opaque). user_id may be any operator identifier."""
    return build_user_headers(user_id, "TravelAgent")


def make_customer_headers(user_id: str) -> dict:
    """Customer (entity_backed:Customer). Pass the acting Customer.id as user_id
    whenever the call is ownership-gated (booking pay/cancel/read)."""
    return build_user_headers(user_id, "Customer")


def make_supplier_headers(user_id: str) -> dict:
    """Supplier (entity_backed:Supplier). Pass the owning Supplier.id as user_id
    whenever the call is ownership-gated (component confirm/reject)."""
    return build_user_headers(user_id, "Supplier")
