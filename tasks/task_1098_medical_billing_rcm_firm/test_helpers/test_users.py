"""Pre-built role headers for every role in the PRD.

Six firm-staff roles carry opaque X-User-ID values not tied to any entity. The
one entity-backed role is PracticeUser, whose X-User-ID must equal the acting
Practice's own id for ownership checks; use make_practice_user_headers(practice_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque staff roles and for tests that do not
# exercise ownership. PracticeUser's shared entry is a fallback for
# non-ownership tests only.
TEST_USERS = {
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "coder_headers": build_user_headers("coder-1", "Coder"),
    "biller_headers": build_user_headers("biller-1", "Biller"),
    "denial_specialist_headers": build_user_headers("ds-1", "DenialSpecialist"),
    "payment_poster_headers": build_user_headers("pp-1", "PaymentPoster"),
    "credentialing_specialist_headers": build_user_headers("cred-1", "CredentialingSpecialist"),
    "practice_user_headers": build_user_headers("practice-user-1", "PracticeUser"),
}


# ---- Per-instance builders (opaque staff roles: any distinct id works) ----
def make_account_manager_headers(user_id="am-1"):
    return build_user_headers(user_id, "AccountManager")


def make_coder_headers(user_id="coder-1"):
    return build_user_headers(user_id, "Coder")


def make_biller_headers(user_id="biller-1"):
    return build_user_headers(user_id, "Biller")


def make_denial_specialist_headers(user_id="ds-1"):
    return build_user_headers(user_id, "DenialSpecialist")


def make_payment_poster_headers(user_id="pp-1"):
    return build_user_headers(user_id, "PaymentPoster")


def make_credentialing_specialist_headers(user_id="cred-1"):
    return build_user_headers(user_id, "CredentialingSpecialist")


def make_practice_user_headers(practice_id):
    """For PracticeUser (entity_backed:Practice). Pass the actual Practice.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(practice_id, "PracticeUser")


# Anonymous: no auth headers at all (triggers ERR_UNAUTHENTICATED).
ANONYMOUS_HEADERS: dict = {}
