"""Pre-built role headers for every role in the Paint & Sip Event Studio PRD.

Three roles (StudioManager, FrontDesk, PlatformAdmin) carry an opaque identity:
their X-User-ID is an operator id never compared to any entity. Customer is
identity-backed: ownership checks compare a reservation's customer_id to the
caller's X-User-ID, and a Customer may book only with their own customer_id. So
every Customer call that exercises ownership MUST use make_customer_headers with
the real Customer.id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles are canonical here; the Customer entry is a
# fallback only for tests that do NOT exercise ownership.
TEST_USERS = {
    "manager_headers": build_user_headers("manager-1", "StudioManager"),
    "front_desk_headers": build_user_headers("frontdesk-1", "FrontDesk"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Fallback only — see make_customer_headers for ownership-gated calls.
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (identity-backed). Pass the actual Customer.id as user_id
    whenever the call books, pays, confirms, or cancels that customer's own
    reservation, or registers attendees on it."""
    return build_user_headers(user_id, "Customer")
