"""Auth header builders for the five roles.

Two of the roles carry an opaque operator identifier that the server never
compares against any entity id, so shared constants are safe for them. The
other three carry the id of a specific persisted row, so every call made in one
of those capacities MUST build its headers from the id of the row under test —
a shared constant would fail the ownership rung instead of exercising the rule
the test is about.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_ALTERNATE_PAYEE,
    ROLE_ATTORNEY,
    ROLE_PARTICIPANT,
    ROLE_PLAN_ADMINISTRATOR,
    ROLE_QDRO_ANALYST,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────
#
# Distinct administrator identifiers matter because a qualification compares the
# acting X-User-ID against the draft order's reviewed_by_user_id. Distinct
# analyst identifiers matter for the same reason from the other side.

ADMIN_USER_ID = "admin-1"
ADMIN_USER_ID_2 = "admin-2"
ADMIN_USER_ID_6 = "admin-6"
ADMIN_USER_ID_7 = "admin-7"
ADMIN_USER_ID_9 = "admin-9"
ADMIN_USER_ID_11 = "admin-11"

ANALYST_USER_ID = "analyst-2"
ANALYST_USER_ID_4 = "analyst-4"
ANALYST_USER_ID_7 = "analyst-7"

# The reviewer identifier the design recipes plant as reviewed_by_user_id, and
# the distinct human who signs the determination afterwards.
REVIEWER_USER_ID = "u-9001"
DETERMINER_USER_ID = "u-7777"

TEST_USERS = {
    "admin": {"user_id": ADMIN_USER_ID, "role": ROLE_PLAN_ADMINISTRATOR},
    "admin_2": {"user_id": ADMIN_USER_ID_2, "role": ROLE_PLAN_ADMINISTRATOR},
    "admin_6": {"user_id": ADMIN_USER_ID_6, "role": ROLE_PLAN_ADMINISTRATOR},
    "admin_7": {"user_id": ADMIN_USER_ID_7, "role": ROLE_PLAN_ADMINISTRATOR},
    "admin_9": {"user_id": ADMIN_USER_ID_9, "role": ROLE_PLAN_ADMINISTRATOR},
    "admin_11": {"user_id": ADMIN_USER_ID_11, "role": ROLE_PLAN_ADMINISTRATOR},
    "analyst": {"user_id": ANALYST_USER_ID, "role": ROLE_QDRO_ANALYST},
    "analyst_4": {"user_id": ANALYST_USER_ID_4, "role": ROLE_QDRO_ANALYST},
    "analyst_7": {"user_id": ANALYST_USER_ID_7, "role": ROLE_QDRO_ANALYST},
    "reviewer": {"user_id": REVIEWER_USER_ID, "role": ROLE_QDRO_ANALYST},
    "determiner": {"user_id": DETERMINER_USER_ID, "role": ROLE_PLAN_ADMINISTRATOR},
}


# ─── Opaque-role header builders ──────────────────────────────────────────

def make_admin_headers(user_id=ADMIN_USER_ID):
    """Headers for a PlanAdministrator acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_PLAN_ADMINISTRATOR)


def make_analyst_headers(user_id=ANALYST_USER_ID):
    """Headers for a QdroAnalyst acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_QDRO_ANALYST)


def make_reviewer_headers():
    """The analyst whose identifier gets planted as reviewed_by_user_id."""
    return build_user_headers(REVIEWER_USER_ID, ROLE_QDRO_ANALYST)


def make_determiner_headers():
    """An administrator guaranteed distinct from the planted reviewer."""
    return build_user_headers(DETERMINER_USER_ID, ROLE_PLAN_ADMINISTRATOR)


# ─── Entity-backed header builders ────────────────────────────────────────

def make_participant_headers(participant_id):
    """Headers for the Participant whose own id is participant_id."""
    return build_user_headers(participant_id, ROLE_PARTICIPANT)


def make_alternate_payee_headers(alternate_payee_account_id):
    """Headers for the AlternatePayee acting as one payee account."""
    return build_user_headers(alternate_payee_account_id, ROLE_ALTERNATE_PAYEE)


def make_attorney_headers(attorney_authorization_id):
    """Headers for the Attorney acting under one authorization."""
    return build_user_headers(attorney_authorization_id, ROLE_ATTORNEY)


def make_headers(user_id, role):
    """Escape hatch for role-matrix tests that pair an arbitrary id with a role."""
    return build_user_headers(user_id, role)


# Convenience singletons for the two opaque roles.
ADMIN_HEADERS = make_admin_headers()
ANALYST_HEADERS = make_analyst_headers()

# Neither identity header, for the authentication rung. The content type is kept
# so the request itself is still well formed at the transport level.
NO_CREDENTIALS = {"Content-Type": "application/json"}

# Well formed headers naming a capacity that is not one of the five roles.
UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": ADMIN_USER_ID,
    "X-User-Role": "PlanTrustee",
    "Content-Type": "application/json",
}
