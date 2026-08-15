"""Pre-built role headers for every role named in PRD 2.1.

`Volunteer` and `Guest` are entity-backed: their `X-User-ID` must equal the
acting Volunteer or GuestProfile row's `id` whenever the call is
ownership-gated (shift check-in / self-cancel, own-order create / release,
own-record reads).  Use `make_volunteer_headers(volunteer_id)` and
`make_guest_headers(guest_id)` for those calls; the shared constants below are
safe only for opaque roles or for tests whose outcome does not depend on the
caller owning the subject resource.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers("admin-op-1", "ProgramAdmin"),
    "kitchen_manager_headers": build_user_headers("km-op-1", "KitchenManager"),
    "food_safety_officer_headers": build_user_headers("fso-op-1", "FoodSafetyOfficer"),
    # Entity-backed identities — fallbacks for non-ownership tests only.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
}


def make_program_admin_headers(user_id: str = "admin-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramAdmin")


def make_kitchen_manager_headers(user_id: str = "km-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "KitchenManager")


def make_food_safety_officer_headers(user_id: str = "fso-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "FoodSafetyOfficer")


def make_volunteer_headers(volunteer_id: str) -> Dict[str, str]:
    """For Volunteer (entity-backed).  Pass the acting Volunteer's id whenever
    the call is ownership-gated (check-in, self-cancel, prep pipeline)."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_guest_headers(guest_id: str) -> Dict[str, str]:
    """For Guest (entity-backed).  Pass the acting GuestProfile's id whenever
    the call is ownership-gated (own-order create/release, own-record reads)."""
    return build_user_headers(guest_id, "Guest")


# Headers carrying neither X-User-ID nor X-User-Role — used to exercise the
# authentication rung directly (PRD 2.6 step 1).
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
