"""Canonical operator identities and their pre-built request headers.

PRD §2.1 requires an X-User-ID and an X-User-Role on every request. All five
roles are opaque operator identities — nothing in the service resolves an
X-User-ID against a stored row — so a fixed table of identifiers is safe to
share across the whole suite.

Two identifiers per approval-bearing role are declared deliberately, because
the three segregation-of-duties rules of PRD §2.10 compare X-User-ID against a
previously recorded operator identifier and therefore need a same-role peer
that is nevertheless a different person.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DATA_STEWARD,
    ROLE_ML_ENGINEER,
    ROLE_MODEL_APPROVER,
    ROLE_PLATFORM_ADMIN,
    ROLE_RELIABILITY_ENGINEER,
    UNDECLARED_ROLE,
)

# ─── Operator identifiers ───

USER_MLE_1 = "u_mle_1"
USER_MLE_2 = "u_mle_2"
USER_STEW_1 = "u_stew_1"
USER_STEW_2 = "u_stew_2"
USER_APPR_1 = "u_appr_1"
USER_APPR_2 = "u_appr_2"
USER_REL_1 = "u_rel_1"
USER_REL_2 = "u_rel_2"
USER_ADMIN_1 = "u_admin_1"
USER_ADMIN_2 = "u_admin_2"

# One operator who acts under two different roles at different moments. Used to
# show that the segregation-of-duties comparison is on the identifier and not
# on the role.
USER_DUAL_1 = "u_dual_1"

# An operator presenting a role name the service does not declare.
USER_AUDITOR = "u_aud_1"


# ─── Pre-built header dictionaries ───

MLE_1 = build_user_headers(USER_MLE_1, ROLE_ML_ENGINEER)
MLE_2 = build_user_headers(USER_MLE_2, ROLE_ML_ENGINEER)
STEWARD_1 = build_user_headers(USER_STEW_1, ROLE_DATA_STEWARD)
STEWARD_2 = build_user_headers(USER_STEW_2, ROLE_DATA_STEWARD)
APPROVER_1 = build_user_headers(USER_APPR_1, ROLE_MODEL_APPROVER)
APPROVER_2 = build_user_headers(USER_APPR_2, ROLE_MODEL_APPROVER)
RELIABILITY_1 = build_user_headers(USER_REL_1, ROLE_RELIABILITY_ENGINEER)
RELIABILITY_2 = build_user_headers(USER_REL_2, ROLE_RELIABILITY_ENGINEER)
ADMIN_1 = build_user_headers(USER_ADMIN_1, ROLE_PLATFORM_ADMIN)
ADMIN_2 = build_user_headers(USER_ADMIN_2, ROLE_PLATFORM_ADMIN)

# The dual-hatted operator, seen through each of the roles it may present.
DUAL_AS_MLE = build_user_headers(USER_DUAL_1, ROLE_ML_ENGINEER)
DUAL_AS_APPROVER = build_user_headers(USER_DUAL_1, ROLE_MODEL_APPROVER)
DUAL_AS_STEWARD = build_user_headers(USER_DUAL_1, ROLE_DATA_STEWARD)

# Undeclared role name.
UNDECLARED_ROLE_HEADERS = build_user_headers(USER_AUDITOR, UNDECLARED_ROLE)

# Headers with a missing or empty X-User-ID / X-User-Role.
NO_USER_ID_HEADERS = {
    "X-User-Role": ROLE_ML_ENGINEER,
    "Content-Type": "application/json",
}
NO_ROLE_HEADERS = {
    "X-User-ID": USER_MLE_1,
    "Content-Type": "application/json",
}
NO_HEADERS_AT_ALL = {"Content-Type": "application/json"}
EMPTY_USER_ID_HEADERS = build_user_headers("", ROLE_ML_ENGINEER)
EMPTY_ROLE_HEADERS = build_user_headers(USER_MLE_1, "")


# One representative holder of each declared role, for sweeps over all roles.
HEADERS_BY_ROLE = {
    ROLE_ML_ENGINEER: MLE_1,
    ROLE_DATA_STEWARD: STEWARD_1,
    ROLE_MODEL_APPROVER: APPROVER_1,
    ROLE_RELIABILITY_ENGINEER: RELIABILITY_1,
    ROLE_PLATFORM_ADMIN: ADMIN_1,
}

# Every read endpoint is available to all five roles (PRD §2.1), so this is the
# canonical sweep list for read authorization.
ALL_ROLE_HEADERS = [
    MLE_1,
    STEWARD_1,
    APPROVER_1,
    RELIABILITY_1,
    ADMIN_1,
]
