"""Identity headers for the five roles the PRD defines (§2.1).

Every request carries `X-User-ID` and `X-User-Role`.  Four of the five roles are
opaque actor identifiers; for `AdvertiserContact` the `X-User-ID` value is the
`AdvertiserContract.id` the caller speaks for, so that builder takes the
contract id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Canonical operator identities used across the suite.
MANAGER_PRIMARY = "mgr-01"
MANAGER_SECONDARY = "mgr-02"
SPECIALIST_PRIMARY = "qs-01"
AUDITOR_PRIMARY = "aud-01"
AUDITOR_SECONDARY = "aud-02"
EXECUTIVE_PRIMARY = "exec-01"


def make_circulation_manager_headers(user_id=MANAGER_PRIMARY):
    return build_user_headers(user_id, UserRole.CIRCULATION_MANAGER.value)


def make_qualification_specialist_headers(user_id=SPECIALIST_PRIMARY):
    return build_user_headers(user_id, UserRole.QUALIFICATION_SPECIALIST.value)


def make_circulation_auditor_headers(user_id=AUDITOR_PRIMARY):
    return build_user_headers(user_id, UserRole.CIRCULATION_AUDITOR.value)


def make_publisher_executive_headers(user_id=EXECUTIVE_PRIMARY):
    return build_user_headers(user_id, UserRole.PUBLISHER_EXECUTIVE.value)


def make_advertiser_contact_headers(contract_id):
    """`X-User-ID` carries the `AdvertiserContract.id` the contact speaks for."""
    return build_user_headers(contract_id, UserRole.ADVERTISER_CONTACT.value)


# Convenience aliases for the identities used most often.
MANAGER_HEADERS = make_circulation_manager_headers(MANAGER_PRIMARY)
MANAGER_2_HEADERS = make_circulation_manager_headers(MANAGER_SECONDARY)
SPECIALIST_HEADERS = make_qualification_specialist_headers(SPECIALIST_PRIMARY)
AUDITOR_HEADERS = make_circulation_auditor_headers(AUDITOR_PRIMARY)
AUDITOR_2_HEADERS = make_circulation_auditor_headers(AUDITOR_SECONDARY)
EXECUTIVE_HEADERS = make_publisher_executive_headers(EXECUTIVE_PRIMARY)


ALL_OPERATOR_HEADERS = {
    UserRole.CIRCULATION_MANAGER.value: MANAGER_HEADERS,
    UserRole.QUALIFICATION_SPECIALIST.value: SPECIALIST_HEADERS,
    UserRole.CIRCULATION_AUDITOR.value: AUDITOR_HEADERS,
    UserRole.PUBLISHER_EXECUTIVE.value: EXECUTIVE_HEADERS,
}
