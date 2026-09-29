"""
Role headers (PRD §2.1).

'Every request to every endpoint must carry two headers: `X-User-ID`,
identifying the acting principal, and `X-User-Role`, declaring the capacity in
which that principal acts.'

Five of the six roles are lender-side operators whose `X-User-ID` is 'an opaque
operator identifier that is not tied to any persisted entity'. Those get
pre-built header dicts with stable identifiers, plus per-identifier builders so
a test can distinguish two analysts or two committee members — which is what the
segregation-of-duties rule at PRD §2.10 position 33 turns on.

`InstitutionRepresentative` is the one entity-backed identity: 'When
`X-User-Role` is `InstitutionRepresentative`, `X-User-ID` is the `id` of the
acting `Institution`.' It therefore has no module-level constant, only the
``make_institution_representative_headers(institution_id)`` builder.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CREDIT_ANALYST,
    ROLE_CREDIT_COMMITTEE_MEMBER,
    ROLE_GOVERNANCE_OFFICER,
    ROLE_INSTITUTION_REPRESENTATIVE,
    ROLE_LOAN_SERVICER,
    ROLE_PLATFORM_ADMIN,
)

# ─── Stable opaque operator identifiers ───────────────────────────────────
ADMIN_1 = "admin-1"
OFFICER_1 = "officer-1"
OFFICER_2 = "officer-2"
ANALYST_1 = "analyst-1"
ANALYST_2 = "analyst-2"
COMMITTEE_1 = "committee-1"
COMMITTEE_2 = "committee-2"
SERVICER_1 = "servicer-1"


# ─── Per-identifier builders ──────────────────────────────────────────────


def make_platform_admin_headers(user_id: str = ADMIN_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_governance_officer_headers(user_id: str = OFFICER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_GOVERNANCE_OFFICER)


def make_credit_analyst_headers(user_id: str = ANALYST_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CREDIT_ANALYST)


def make_committee_member_headers(user_id: str = COMMITTEE_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CREDIT_COMMITTEE_MEMBER)


def make_loan_servicer_headers(user_id: str = SERVICER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LOAN_SERVICER)


def make_institution_representative_headers(institution_id: str) -> Dict[str, str]:
    """
    PRD §2.1: for this role `X-User-ID` is the `id` of the acting `Institution`,
    so the header can only be built once the institution exists.
    """
    return build_user_headers(institution_id, ROLE_INSTITUTION_REPRESENTATIVE)


def make_undeclared_role_headers(
    user_id: str = "someone-1", role: str = "UnknownRole"
) -> Dict[str, str]:
    """
    PRD §2.1: 'presenting an `X-User-Role` value that is not one of those six
    strings, is rejected with `ERR_UNAUTHENTICATED`'.
    """
    return build_user_headers(user_id, role)


# ─── Pre-built headers for the five opaque operator roles ─────────────────
PLATFORM_ADMIN = make_platform_admin_headers()
GOVERNANCE_OFFICER = make_governance_officer_headers()
CREDIT_ANALYST = make_credit_analyst_headers()
CREDIT_ANALYST_2 = make_credit_analyst_headers(ANALYST_2)
COMMITTEE_MEMBER = make_committee_member_headers()
COMMITTEE_MEMBER_2 = make_committee_member_headers(COMMITTEE_2)
LOAN_SERVICER = make_loan_servicer_headers()
