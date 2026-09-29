"""Pre-built authentication headers for every role in the PRD role table.

Four roles carry an opaque operator identifier: SystemAdmin, ProofingAgent,
CredentialAdjudicator and PrivacyAuditor.  Two roles are entity backed - the
Holder's X-User-ID is a Holder id and the VerifierOperator's X-User-ID is a
Verifier id - so those two must always be built per row with the builder
functions below, never with a fixed constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# --------------------------------------------------------------------------
# Opaque operator identities
# --------------------------------------------------------------------------
SYSTEM_ADMIN_USER_ID = "admin-001"
SYSTEM_ADMIN_ALT_USER_ID = "admin-002"
PROOFING_AGENT_USER_ID = "pa-001"
PROOFING_AGENT_ALT_USER_ID = "pa-002"
ADJUDICATOR_USER_ID = "ca-001"
ADJUDICATOR_ALT_USER_ID = "ca-002"
PRIVACY_AUDITOR_USER_ID = "pauditor-001"

TEST_USERS = {
    "system_admin": build_user_headers(SYSTEM_ADMIN_USER_ID, "SystemAdmin"),
    "system_admin_alt": build_user_headers(SYSTEM_ADMIN_ALT_USER_ID, "SystemAdmin"),
    "proofing_agent": build_user_headers(PROOFING_AGENT_USER_ID, "ProofingAgent"),
    "proofing_agent_alt": build_user_headers(
        PROOFING_AGENT_ALT_USER_ID, "ProofingAgent"
    ),
    "adjudicator": build_user_headers(ADJUDICATOR_USER_ID, "CredentialAdjudicator"),
    "adjudicator_alt": build_user_headers(
        ADJUDICATOR_ALT_USER_ID, "CredentialAdjudicator"
    ),
    "privacy_auditor": build_user_headers(PRIVACY_AUDITOR_USER_ID, "PrivacyAuditor"),
}

ADMIN = TEST_USERS["system_admin"]
ADMIN_ALT = TEST_USERS["system_admin_alt"]
PROOFING_AGENT = TEST_USERS["proofing_agent"]
PROOFING_AGENT_ALT = TEST_USERS["proofing_agent_alt"]
ADJUDICATOR = TEST_USERS["adjudicator"]
ADJUDICATOR_ALT = TEST_USERS["adjudicator_alt"]
PRIVACY_AUDITOR = TEST_USERS["privacy_auditor"]


# --------------------------------------------------------------------------
# Entity backed identities
# --------------------------------------------------------------------------
def make_holder_headers(holder_id: str) -> dict:
    """Headers for the Holder role; X-User-ID must be the Holder row id."""
    return build_user_headers(holder_id, "Holder")


def make_verifier_operator_headers(verifier_id: str) -> dict:
    """Headers for VerifierOperator; X-User-ID must be the Verifier row id."""
    return build_user_headers(verifier_id, "VerifierOperator")


def make_proofing_agent_headers(user_id: str) -> dict:
    """Headers for an arbitrary ProofingAgent operator identifier."""
    return build_user_headers(user_id, "ProofingAgent")


def make_adjudicator_headers(user_id: str) -> dict:
    """Headers for an arbitrary CredentialAdjudicator operator identifier."""
    return build_user_headers(user_id, "CredentialAdjudicator")


def make_admin_headers(user_id: str) -> dict:
    """Headers for an arbitrary SystemAdmin operator identifier."""
    return build_user_headers(user_id, "SystemAdmin")


def make_privacy_auditor_headers(user_id: str) -> dict:
    """Headers for an arbitrary PrivacyAuditor operator identifier."""
    return build_user_headers(user_id, "PrivacyAuditor")


NO_AUTH_HEADERS = {"Content-Type": "application/json"}

ALL_ROLE_NAMES = [
    "SystemAdmin",
    "ProofingAgent",
    "CredentialAdjudicator",
    "Holder",
    "VerifierOperator",
    "PrivacyAuditor",
]
