"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for opaque roles (Anonymous, Inspector, OperationsAdmin)
# and for any test whose success does not depend on the caller owning the
# subject resource.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "inspector_1_headers": build_user_headers("insp-1", "Inspector"),
    "inspector_2_headers": build_user_headers("insp-2", "Inspector"),
    "ops_admin_headers": build_user_headers("ops-1", "OperationsAdmin"),
    "ops_admin_2_headers": build_user_headers("ops-2", "OperationsAdmin"),
    "ops_admin_9_headers": build_user_headers("ops-9", "OperationsAdmin"),
}


# Per-instance builders — mandatory for entity-backed roles. When a call is
# ownership-gated (Customer owns reservations; HotelPartner reads its own
# guests' reservations), pass the actual entity id as user_id.
def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: user_id must be the real Customer.id."""
    return build_user_headers(user_id, "Customer")


def make_hotel_partner_headers(user_id: str) -> dict:
    """HotelPartner is entity-backed: user_id must be the real HotelPartner.id."""
    return build_user_headers(user_id, "HotelPartner")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector is opaque; any operator id works."""
    return build_user_headers(user_id, "Inspector")


def make_ops_headers(user_id: str) -> dict:
    """OperationsAdmin is opaque; any operator id works."""
    return build_user_headers(user_id, "OperationsAdmin")
