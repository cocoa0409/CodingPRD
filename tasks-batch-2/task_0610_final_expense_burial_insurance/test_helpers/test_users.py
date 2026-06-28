"""Pre-built role headers for every role in the PRD.

All four roles are opaque identities (PRD §2.1): X-User-ID is an operator
identifier that is not tied to any persisted entity id. The only behavioural
exception is the Policyholder, whose X-User-ID is compared against a policy's
stored policyholder_user_id on owner-scoped mutations. For that reason the
Policyholder also gets a per-instance builder so ownership-gated calls can pass
the policy's actual policyholder_user_id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Policyholder resource ownership.
TEST_USERS = {
    "underwriter_headers": build_user_headers("uw-1", "Underwriter"),
    "policy_admin_headers": build_user_headers("pa-1", "PolicyAdmin"),
    "claims_examiner_headers": build_user_headers("ce-1", "ClaimsExaminer"),
    "policyholder_headers": build_user_headers("ph-default", "Policyholder"),
}


def make_policyholder_headers(user_id: str) -> dict:
    """For the Policyholder role. Pass the policy's stored policyholder_user_id
    as user_id whenever the call is owner-scoped (surrender, loan, repay)."""
    return build_user_headers(user_id, "Policyholder")


def make_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_policy_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PolicyAdmin")


def make_claims_examiner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsExaminer")
