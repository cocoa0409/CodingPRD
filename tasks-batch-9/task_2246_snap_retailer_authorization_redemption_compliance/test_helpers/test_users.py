"""Role headers.

Four roles carry an opaque caller identifier the server never compares to an
entity id: Anonymous, FnsAdmin, FnsAnalyst and AdminReviewOfficer. Three are
entity backed and their X-User-ID must be an entity's own id -- a RetailerOwner
carries the Owner id, a StoreClerk carries the Store id and an Inspector carries
the Inspector id -- so every ownership-gated call must thread that id into its
headers rather than reuse a shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque caller identifiers
# --------------------------------------------------------------------------

ANONYMOUS_USER_ID = "anonymous-caller-1"
ADMIN_USER_ID = "fns-admin-1"
ADMIN_ALT_USER_ID = "fns-admin-2"
ANALYST_USER_ID = "fns-analyst-1"
ANALYST_ALT_USER_ID = "fns-analyst-2"
REVIEW_OFFICER_USER_ID = "review-officer-1"
REVIEW_OFFICER_ALT_USER_ID = "review-officer-2"

# The literal opener recorded for an investigation the monitoring engine opened
# automatically, which no human X-User-ID can collide with.
SYSTEM_OPENER_USER_ID = "system"


# --------------------------------------------------------------------------
# Opaque-identity header builders
# --------------------------------------------------------------------------

def make_anonymous_headers(user_id: str = ANONYMOUS_USER_ID):
    return build_user_headers(user_id, UserRole.ANONYMOUS.value)


def make_fns_admin_headers(user_id: str = ADMIN_USER_ID):
    return build_user_headers(user_id, UserRole.FNS_ADMIN.value)


def make_fns_analyst_headers(user_id: str = ANALYST_USER_ID):
    return build_user_headers(user_id, UserRole.FNS_ANALYST.value)


def make_admin_review_officer_headers(user_id: str = REVIEW_OFFICER_USER_ID):
    return build_user_headers(user_id, UserRole.ADMIN_REVIEW_OFFICER.value)


# --------------------------------------------------------------------------
# Entity-backed header builders
# --------------------------------------------------------------------------

def make_retailer_owner_headers(owner_id: str):
    """X-User-ID must be the id of the acting Owner."""
    return build_user_headers(owner_id, UserRole.RETAILER_OWNER.value)


def make_store_clerk_headers(store_id: str):
    """X-User-ID must be the id of the acting Store."""
    return build_user_headers(store_id, UserRole.STORE_CLERK.value)


def make_inspector_headers(inspector_id: str):
    """X-User-ID must be the id of the acting Inspector."""
    return build_user_headers(inspector_id, UserRole.INSPECTOR.value)


def make_headers_for_role(role: str, user_id: str):
    """Headers for an arbitrary role string, including unknown role values."""
    return build_user_headers(user_id, role)


# --------------------------------------------------------------------------
# Shared constants for the opaque roles
# --------------------------------------------------------------------------

TEST_USERS = {
    "anonymous": make_anonymous_headers(),
    "fns_admin": make_fns_admin_headers(),
    "fns_analyst": make_fns_analyst_headers(),
    "admin_review_officer": make_admin_review_officer_headers(),
}

# Both authentication headers omitted entirely.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

# Only one of the two mandatory headers supplied.
ROLE_ONLY_HEADERS = {"Content-Type": "application/json", "X-User-Role": "FnsAdmin"}
USER_ID_ONLY_HEADERS = {"Content-Type": "application/json", "X-User-ID": ADMIN_USER_ID}
