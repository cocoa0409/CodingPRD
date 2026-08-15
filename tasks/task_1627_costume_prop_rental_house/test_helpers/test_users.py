"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The opaque roles (HouseAdmin, WardrobeStaff, Accountant) may use
# these freely. The RenterContact constant is a fallback ONLY for tests that never
# exercise ownership; ownership-gated calls must use make_renter_contact_headers()
# with the actual Renter id (X-User-ID must equal the renter's id per PRD §2.1).
TEST_USERS = {
    "house_admin_headers": build_user_headers("admin-1", "HouseAdmin"),
    "wardrobe_staff_headers": build_user_headers("ws-1", "WardrobeStaff"),
    "accountant_headers": build_user_headers("acct-1", "Accountant"),
    "renter_contact_headers": build_user_headers("test-renter-1", "RenterContact"),
}


def make_house_admin_headers(user_id: str = "admin-1") -> dict:
    """HouseAdmin is an opaque role; any operator id is fine."""
    return build_user_headers(user_id, "HouseAdmin")


def make_wardrobe_staff_headers(user_id: str = "ws-1") -> dict:
    """WardrobeStaff is an opaque role; the id is recorded on assessments/claims."""
    return build_user_headers(user_id, "WardrobeStaff")


def make_accountant_headers(user_id: str = "acct-1") -> dict:
    """Accountant is an opaque role; the id is recorded as posted_by_user_id."""
    return build_user_headers(user_id, "Accountant")


def make_renter_contact_headers(user_id: str) -> dict:
    """RenterContact is entity-backed: user_id MUST be the acting Renter's id
    whenever the call is ownership-gated (productions, reservations, pull lists,
    fittings, disputes, own certificates)."""
    return build_user_headers(user_id, "RenterContact")
