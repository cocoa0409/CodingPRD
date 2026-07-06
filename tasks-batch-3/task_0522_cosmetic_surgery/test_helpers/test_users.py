"""Pre-built role headers for every role in the PRD.

All four roles use an opaque identity model: X-User-ID is an operator identifier
that is not tied to any persisted entity's id. The server records the caller's
X-User-ID only where a workflow demands it (surgeon_user_id on Consultation /
SurgeryBooking), and ownership checks compare X-User-ID against that stored value.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "practice_admin_headers": build_user_headers("admin-1", "PracticeAdmin"),
    "front_desk_headers": build_user_headers("frontdesk-1", "FrontDeskCoordinator"),
    "surgeon_headers": build_user_headers("surgeon-1", "Surgeon"),
    "billing_headers": build_user_headers("billing-1", "BillingSpecialist"),
}


def make_surgeon_headers(user_id: str) -> dict:
    """Headers for a Surgeon acting as the given operator id. Ownership checks compare
    X-User-ID against the surgeon_user_id stored on the Consultation / SurgeryBooking,
    so pass the same operator id that was recorded as surgeon_user_id."""
    return build_user_headers(user_id, "Surgeon")


def make_headers(role: str, user_id: str) -> dict:
    return build_user_headers(user_id, role)
