"""Header builders for the six roles.

Four roles carry an opaque operator identifier in ``X-User-ID`` and may
therefore use a fixed constant. The two entity-backed roles must carry a real
entity identifier: a ``PhysicianUser`` sends the acting ``PhysicianMember`` id
and a ``PayerRepresentative`` sends the acting ``DelegationAgreement`` id, so
those two get per-instance builders instead of a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLAIMS_EXAMINER,
    ROLE_IPA_ADMIN,
    ROLE_NETWORK_MANAGER,
    ROLE_PAYER_REPRESENTATIVE,
    ROLE_PHYSICIAN_USER,
    ROLE_REINSURANCE_UNDERWRITER,
)

Headers = Dict[str, str]

# Opaque operator identifiers. Two distinct examiner identifiers and two
# distinct underwriter identifiers are provided so that segregation-of-duties
# scenarios can act as "the same person" or "a different person" on purpose.
IPA_ADMIN_USER_ID = "ipa-admin-001"
NETWORK_MANAGER_USER_ID = "network-manager-001"
CLAIMS_EXAMINER_USER_ID = "claims-examiner-001"
CLAIMS_EXAMINER_ALT_USER_ID = "claims-examiner-002"
REINSURANCE_UNDERWRITER_USER_ID = "reinsurance-underwriter-001"
REINSURANCE_UNDERWRITER_ALT_USER_ID = "reinsurance-underwriter-002"

IPA_ADMIN_HEADERS: Headers = build_user_headers(IPA_ADMIN_USER_ID, ROLE_IPA_ADMIN)
NETWORK_MANAGER_HEADERS: Headers = build_user_headers(
    NETWORK_MANAGER_USER_ID, ROLE_NETWORK_MANAGER
)
CLAIMS_EXAMINER_HEADERS: Headers = build_user_headers(
    CLAIMS_EXAMINER_USER_ID, ROLE_CLAIMS_EXAMINER
)
CLAIMS_EXAMINER_ALT_HEADERS: Headers = build_user_headers(
    CLAIMS_EXAMINER_ALT_USER_ID, ROLE_CLAIMS_EXAMINER
)
REINSURANCE_UNDERWRITER_HEADERS: Headers = build_user_headers(
    REINSURANCE_UNDERWRITER_USER_ID, ROLE_REINSURANCE_UNDERWRITER
)
REINSURANCE_UNDERWRITER_ALT_HEADERS: Headers = build_user_headers(
    REINSURANCE_UNDERWRITER_ALT_USER_ID, ROLE_REINSURANCE_UNDERWRITER
)

TEST_USERS = {
    ROLE_IPA_ADMIN: IPA_ADMIN_HEADERS,
    ROLE_NETWORK_MANAGER: NETWORK_MANAGER_HEADERS,
    ROLE_CLAIMS_EXAMINER: CLAIMS_EXAMINER_HEADERS,
    ROLE_REINSURANCE_UNDERWRITER: REINSURANCE_UNDERWRITER_HEADERS,
}


def make_physician_user_headers(physician_id: str) -> Headers:
    """Headers for a ``PhysicianUser`` acting as the given physician record."""
    return build_user_headers(physician_id, ROLE_PHYSICIAN_USER)


def make_payer_representative_headers(agreement_id: str) -> Headers:
    """Headers for the ``PayerRepresentative`` of the given agreement."""
    return build_user_headers(agreement_id, ROLE_PAYER_REPRESENTATIVE)


def make_ipa_admin_headers(user_id: str) -> Headers:
    """Headers for an ``IpaAdmin`` with a caller-chosen opaque identifier."""
    return build_user_headers(user_id, ROLE_IPA_ADMIN)


def make_claims_examiner_headers(user_id: str) -> Headers:
    """Headers for a ``ClaimsExaminer`` with a caller-chosen opaque identifier."""
    return build_user_headers(user_id, ROLE_CLAIMS_EXAMINER)


def make_reinsurance_underwriter_headers(user_id: str) -> Headers:
    """Headers for a ``ReinsuranceUnderwriter`` with a chosen opaque identifier."""
    return build_user_headers(user_id, ROLE_REINSURANCE_UNDERWRITER)


def make_network_manager_headers(user_id: str) -> Headers:
    """Headers for a ``NetworkManager`` with a caller-chosen opaque identifier."""
    return build_user_headers(user_id, ROLE_NETWORK_MANAGER)


def make_headers(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)
