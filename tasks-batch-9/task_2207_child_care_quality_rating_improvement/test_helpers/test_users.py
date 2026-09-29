"""Pre-built role headers for every role named in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque-identifier roles (StateAdministrator, Coach, AppealReviewer, FamilyViewer)
# may safely use shared constants: the PRD says their X-User-ID is never compared
# to any entity id. The Provider and Observer entries are fallbacks for tests that
# do NOT exercise ownership; ownership-gated calls must use the builders below.
TEST_USERS = {
    "admin_headers": build_user_headers("admin_ops_1", "StateAdministrator"),
    "admin_alt_headers": build_user_headers("admin_ops_2", "StateAdministrator"),
    "provider_headers": build_user_headers("provider-not-an-entity", "Provider"),
    "observer_headers": build_user_headers("observer-not-an-entity", "Observer"),
    "coach_headers": build_user_headers("coach_user_1", "Coach"),
    "coach_alt_headers": build_user_headers("coach_user_2", "Coach"),
    "reviewer_headers": build_user_headers("reviewer_1", "AppealReviewer"),
    "reviewer_alt_headers": build_user_headers("reviewer_2", "AppealReviewer"),
    "family_headers": build_user_headers("family_1", "FamilyViewer"),
}

ADMIN_USER_ID = "admin_ops_1"
ADMIN_ALT_USER_ID = "admin_ops_2"
COACH_USER_ID = "coach_user_1"
COACH_ALT_USER_ID = "coach_user_2"
REVIEWER_USER_ID = "reviewer_1"
REVIEWER_ALT_USER_ID = "reviewer_2"


def make_provider_headers(provider_id: str) -> dict:
    """Provider is entity_backed: X-User-ID must be the Provider entity's id."""
    return build_user_headers(provider_id, "Provider")


def make_observer_headers(observer_id: str) -> dict:
    """Observer is entity_backed: X-User-ID must be the Observer entity's id."""
    return build_user_headers(observer_id, "Observer")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "StateAdministrator")


def make_coach_headers(coach_user_id: str = COACH_USER_ID) -> dict:
    """Coach writes require X-User-ID == the allocation's coach_user_id."""
    return build_user_headers(coach_user_id, "Coach")


def make_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "AppealReviewer")


def make_family_headers(user_id: str = "family_1") -> dict:
    return build_user_headers(user_id, "FamilyViewer")


def family_headers_without_user_id() -> dict:
    """FamilyViewer is the only role whose X-User-ID header may be omitted."""
    return {"X-User-Role": "FamilyViewer"}
