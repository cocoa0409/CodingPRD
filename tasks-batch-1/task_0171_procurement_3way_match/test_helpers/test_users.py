"""Pre-built role headers for every role in the PRD (§2.1).

All six roles carry an *opaque* identity (PRD §2.1): the X-User-ID is an operator
identifier never compared to any entity's primary key. The server records these
identifiers as audit anchors (requester_id, decided_by_id, posted_by_id) and
segregation-of-duties checks compare one recorded operator identifier against
another. Tests therefore need to control the literal X-User-ID, so this module
exposes both shared-constant headers and per-role builders parametrized by the
operator id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Canonical operator ids used across the test suite. Distinct buyer/approver/
# receiver/matcher/clerk ids keep segregation-of-duties checks satisfiable in
# the happy path (e.g., the approver is never the requester).
USER_IDS = {
    "ADMIN": "admin-a1",
    "BUYER": "buyer-b1",
    "APPROVER_MGR": "approver-mgr",
    "APPROVER_DIR": "approver-dir",
    "APPROVER_CFO": "approver-cfo",
    "RECEIVER": "receiver-r1",
    "MATCHER": "matcher-m1",
    "CLERK": "clerk-c1",
}

TEST_USERS = {
    "admin_headers": build_user_headers(USER_IDS["ADMIN"], "ProcurementAdmin"),
    "buyer_headers": build_user_headers(USER_IDS["BUYER"], "Buyer"),
    "approver_headers": build_user_headers(USER_IDS["APPROVER_MGR"], "Approver"),
    "approver_dir_headers": build_user_headers(USER_IDS["APPROVER_DIR"], "Approver"),
    "approver_cfo_headers": build_user_headers(USER_IDS["APPROVER_CFO"], "Approver"),
    "receiver_headers": build_user_headers(USER_IDS["RECEIVER"], "Receiver"),
    "matcher_headers": build_user_headers(USER_IDS["MATCHER"], "Matcher"),
    "clerk_headers": build_user_headers(USER_IDS["CLERK"], "PayablesClerk"),
}


# ── Per-role builders: pass the operator id the test wants to act as. ──
def make_admin_headers(user_id):
    return build_user_headers(user_id, "ProcurementAdmin")


def make_buyer_headers(user_id):
    return build_user_headers(user_id, "Buyer")


def make_approver_headers(user_id):
    return build_user_headers(user_id, "Approver")


def make_receiver_headers(user_id):
    return build_user_headers(user_id, "Receiver")


def make_matcher_headers(user_id):
    return build_user_headers(user_id, "Matcher")


def make_clerk_headers(user_id):
    return build_user_headers(user_id, "PayablesClerk")
