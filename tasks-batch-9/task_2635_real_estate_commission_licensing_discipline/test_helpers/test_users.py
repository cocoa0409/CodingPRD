"""Header sets for the PRD's ten roles.

Six roles are *opaque*: `X-User-ID` is an operator identifier that the server
never compares to any persisted row, so a fixed literal is fine — except where
the workflow records the identifier and later gates on it (`auditor_user_id`,
`panel_chair_user_id`, `investigator_user_id`, `offered_by_user_id`).  For those
the `make_*_headers` factories below let a test name an exact operator.

Four roles are *entity-backed*: `X-User-ID` is the primary key of a persisted
row, and ownership is compared against it.  A test acting as `Broker`,
`Salesperson`, `Respondent` or `ProviderAdmin` must therefore always build its
headers from the id of the row it is acting for — never from a fixed literal —
or every ownership check will refuse the request.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Opaque operator identifiers ──────────────────────────────────────────
ANALYST_USER_ID = "analyst-01"
AUDITOR_USER_ID = "auditor-01"
COUNSEL_USER_ID = "counsel-01"
CHAIR_USER_ID = "chair-01"
TRUSTEE_USER_ID = "trustee-01"
PUBLIC_USER_ID = "public-01"

# A second distinct operator per gated seat, for segregation-of-duties tests.
SECOND_AUDITOR_USER_ID = "auditor-02"
SECOND_COUNSEL_USER_ID = "counsel-02"
SECOND_CHAIR_USER_ID = "chair-02"


def make_analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "LicensingAnalyst")


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "TrustAuditor")


def make_counsel_headers(user_id: str = COUNSEL_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "CommissionCounsel")


def make_chair_headers(user_id: str = CHAIR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "HearingPanelChair")


def make_trustee_headers(user_id: str = TRUSTEE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "RecoveryFundTrustee")


def make_public_headers(user_id: str = PUBLIC_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "Public")


# ─── Entity-backed roles: the id must be a real row's primary key ──────────
def make_broker_headers(licensee_id: str) -> Dict[str, str]:
    """`X-User-ID` is the id of the acting `Licensee` whose type is BROKER."""
    return build_user_headers(licensee_id, "Broker")


def make_salesperson_headers(licensee_id: str) -> Dict[str, str]:
    """`X-User-ID` is the id of the acting `Licensee`."""
    return build_user_headers(licensee_id, "Salesperson")


def make_respondent_headers(licensee_id: str) -> Dict[str, str]:
    """`X-User-ID` is the id of the `Licensee` named in the disciplinary matter."""
    return build_user_headers(licensee_id, "Respondent")


def make_provider_admin_headers(admin_user_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `admin_user_id` recorded on the EducationProvider."""
    return build_user_headers(admin_user_id, "ProviderAdmin")


PROVIDER_ADMIN_USER_ID = "provider-admin-01"

TEST_USERS = {
    # Opaque roles — safe to reuse as-is.
    "analyst_headers": make_analyst_headers(),
    "auditor_headers": make_auditor_headers(),
    "second_auditor_headers": make_auditor_headers(SECOND_AUDITOR_USER_ID),
    "counsel_headers": make_counsel_headers(),
    "second_counsel_headers": make_counsel_headers(SECOND_COUNSEL_USER_ID),
    "chair_headers": make_chair_headers(),
    "second_chair_headers": make_chair_headers(SECOND_CHAIR_USER_ID),
    "trustee_headers": make_trustee_headers(),
    "public_headers": make_public_headers(),
    # Entity-backed roles have no reusable default; use the make_* factories.
}

UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "someone",
    "X-User-Role": "NotARole",
    "Content-Type": "application/json",
}

MISSING_ROLE_HEADERS = {
    "X-User-ID": ANALYST_USER_ID,
    "Content-Type": "application/json",
}

MISSING_USER_ID_HEADERS = {
    "X-User-Role": "LicensingAnalyst",
    "Content-Type": "application/json",
}
