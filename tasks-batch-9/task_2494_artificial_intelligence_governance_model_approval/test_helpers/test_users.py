"""Pre-built request headers for the six roles (PRD §2.1).

Identity in this API is opaque: PRD §2.1 states that ``X-User-ID`` is never
compared against any record's ``id``. What the API *does* compare is recorded
operator strings against each other — ``requester_user_id`` against a clearing
reviewer, a clearing reviewer against the approving officer, a reassessment
officer against the requester. So the tests need stable, *distinct* user ids per
actor rather than ids that correspond to stored rows.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BUSINESS,
    ROLE_LEGAL,
    ROLE_OFFICER,
    ROLE_PRIVACY,
    ROLE_REQUESTER,
    ROLE_SECURITY,
)

# ─── Canonical actor ids ───────────────────────────────────────────────────
USER_REQUESTER_1 = "usr_req_1"
USER_REQUESTER_2 = "usr_req_2"
USER_LEGAL_1 = "usr_legal_1"
USER_PRIVACY_1 = "usr_priv_1"
USER_PRIVACY_2 = "usr_priv_2"
USER_SECURITY_1 = "usr_sec_1"
USER_BUSINESS_1 = "usr_biz_1"
USER_OFFICER_1 = "usr_gov_1"
USER_OFFICER_2 = "usr_gov_2"

# ─── One header set per role (the default actor for that role) ─────────────
REQUESTER = build_user_headers(USER_REQUESTER_1, ROLE_REQUESTER)
REQUESTER_2 = build_user_headers(USER_REQUESTER_2, ROLE_REQUESTER)
LEGAL_REVIEWER = build_user_headers(USER_LEGAL_1, ROLE_LEGAL)
PRIVACY_REVIEWER = build_user_headers(USER_PRIVACY_1, ROLE_PRIVACY)
PRIVACY_REVIEWER_2 = build_user_headers(USER_PRIVACY_2, ROLE_PRIVACY)
SECURITY_REVIEWER = build_user_headers(USER_SECURITY_1, ROLE_SECURITY)
BUSINESS_REVIEWER = build_user_headers(USER_BUSINESS_1, ROLE_BUSINESS)
OFFICER = build_user_headers(USER_OFFICER_1, ROLE_OFFICER)
OFFICER_2 = build_user_headers(USER_OFFICER_2, ROLE_OFFICER)

# Role name → default header set, for role-matrix sweeps.
HEADERS_BY_ROLE = {
    ROLE_REQUESTER: REQUESTER,
    ROLE_LEGAL: LEGAL_REVIEWER,
    ROLE_PRIVACY: PRIVACY_REVIEWER,
    ROLE_SECURITY: SECURITY_REVIEWER,
    ROLE_BUSINESS: BUSINESS_REVIEWER,
    ROLE_OFFICER: OFFICER,
}

# Gate type → the header set of the reviewer role that owns it (PRD §2.1).
GATE_REVIEWER_HEADERS = {
    "LEGAL": LEGAL_REVIEWER,
    "PRIVACY": PRIVACY_REVIEWER,
    "SECURITY": SECURITY_REVIEWER,
    "BUSINESS": BUSINESS_REVIEWER,
}

# ─── Deliberately mismatched identities ────────────────────────────────────
# A reviewer role acting under the requester's user id, used to probe the
# separation-of-duties comparison rather than the role check: the role is
# authorized for the endpoint, but the recorded operator collides.
BUSINESS_REVIEWER_AS_REQUESTER = build_user_headers(USER_REQUESTER_1, ROLE_BUSINESS)
PRIVACY_REVIEWER_AS_REQUESTER = build_user_headers(USER_REQUESTER_1, ROLE_PRIVACY)
LEGAL_REVIEWER_AS_REQUESTER = build_user_headers(USER_REQUESTER_1, ROLE_LEGAL)

# An officer acting under a clearing reviewer's user id, so that signing the
# approval collides with the identity that cleared a gate.
OFFICER_AS_BUSINESS_REVIEWER = build_user_headers(USER_BUSINESS_1, ROLE_OFFICER)
OFFICER_AS_PRIVACY_REVIEWER = build_user_headers(USER_PRIVACY_1, ROLE_OFFICER)
OFFICER_AS_REQUESTER = build_user_headers(USER_REQUESTER_1, ROLE_OFFICER)

# A reviewer whose role does not own the gate it addresses, used to probe the
# gate-ownership check (PRD §2.1).
BUSINESS_REVIEWER_HEADERS_FOR_PRIVACY_GATE = PRIVACY_REVIEWER

# ─── Malformed authentication (PRD §2.1) ───────────────────────────────────
NO_AUTH_HEADERS: dict[str, str] = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {
    "X-User-ID": USER_OFFICER_1,
    "Content-Type": "application/json",
}
BLANK_ROLE_HEADERS = build_user_headers(USER_OFFICER_1, "")
INVALID_ROLE_HEADERS = build_user_headers(USER_OFFICER_1, "ChiefRobotWrangler")
