"""
Role identities for the five roles of §2.1.

Three roles are opaque: "When `X-User-Role` is `ProgramAdmin`, `ProgramApprover`,
or `FraudAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any
persisted entity", so fixed operator strings suffice — and second identities are
kept for each because §2.1 enforces segregation of duties across four operator
pairings, which needs two distinct principals on the same collection.

Two roles are entity-backed. A `Cardholder` acts under the `id` of its own
`Account` and an `AgencySupplier` under the `id` of its own `TravelAgencyPartner`,
so those headers can only be built once the row exists — hence the builders.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_AGENCY_SUPPLIER,
    ROLE_CARDHOLDER,
    ROLE_FRAUD_ANALYST,
    ROLE_PROGRAM_ADMIN,
    ROLE_PROGRAM_APPROVER,
)

# ─── Opaque operator identities ───────────────────────────────────────

ADMIN_USER_ID = "admin-1"
ADMIN_2_USER_ID = "admin-2"
APPROVER_USER_ID = "approver-1"
APPROVER_2_USER_ID = "approver-2"
ANALYST_USER_ID = "fraud-1"
ANALYST_2_USER_ID = "fraud-2"

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
ADMIN_2_HEADERS = build_user_headers(ADMIN_2_USER_ID, ROLE_PROGRAM_ADMIN)
APPROVER_HEADERS = build_user_headers(APPROVER_USER_ID, ROLE_PROGRAM_APPROVER)
APPROVER_2_HEADERS = build_user_headers(APPROVER_2_USER_ID, ROLE_PROGRAM_APPROVER)
ANALYST_HEADERS = build_user_headers(ANALYST_USER_ID, ROLE_FRAUD_ANALYST)
ANALYST_2_HEADERS = build_user_headers(ANALYST_2_USER_ID, ROLE_FRAUD_ANALYST)


# ─── Entity-backed identities ─────────────────────────────────────────


def make_cardholder_headers(account_id: str) -> Dict[str, str]:
    """
    Headers for a `Cardholder`: "`X-User-ID` is the `id` of the acting `Account`",
    which is what ownership checks compare a resource's `account_id` against.
    """
    return build_user_headers(account_id, ROLE_CARDHOLDER)


def make_agency_headers(agency_partner_id: str) -> Dict[str, str]:
    """
    Headers for an `AgencySupplier`: "`X-User-ID` is the `id` of the acting
    `TravelAgencyPartner`", which agency-scope checks compare an offer's
    `agency_partner_id` against.
    """
    return build_user_headers(agency_partner_id, ROLE_AGENCY_SUPPLIER)


# ─── Malformed identities, for the authentication checks of §2.1 ──────

#: No headers at all: "If either header is absent ... `ERR_MISSING_AUTH_HEADERS`".
NO_HEADERS: Dict[str, str] = {}

MISSING_ROLE_HEADERS = {"X-User-ID": ADMIN_USER_ID}

MISSING_USER_ID_HEADERS = {"X-User-Role": ROLE_PROGRAM_ADMIN}

#: "present but empty" is the other half of the same rejection.
EMPTY_USER_ID_HEADERS = {"X-User-ID": "", "X-User-Role": ROLE_PROGRAM_ADMIN}

EMPTY_ROLE_HEADERS = {"X-User-ID": ADMIN_USER_ID, "X-User-Role": ""}

#: "any string other than the five role names" — `ERR_UNKNOWN_ROLE`.
UNKNOWN_ROLE_HEADERS = build_user_headers("someone-1", "RewardsAuditor")

#: Case matters: "Spelling is exact and case-sensitive."
WRONG_CASE_ROLE_HEADERS = build_user_headers(ADMIN_USER_ID, "programadmin")
