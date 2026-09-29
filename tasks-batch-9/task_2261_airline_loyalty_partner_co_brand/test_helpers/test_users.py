"""Pre-built role headers for the seven roles the PRD declares.

Five roles carry an opaque identity, so a shared constant is their canonical
form.  Two roles are entity-backed and therefore have no meaningful shared
constant: an ``IssuerRepresentative``'s ``X-User-ID`` is the ``id`` of the
``CoBrandIssuer`` it acts for, and a ``Member``'s ``X-User-ID`` is the ``id`` of
its own ``MemberAccount``.  Calls made as those two roles MUST build headers
from the real row id via :func:`make_issuer_representative_headers` and
:func:`make_member_headers`.
"""
from prd_bench_local_runner.testing import build_user_headers

PROGRAM_ADMIN_USER_ID = "pa-1"
SECOND_PROGRAM_ADMIN_USER_ID = "pa-2"
PARTNER_MANAGER_USER_ID = "pm-1"
SECOND_PARTNER_MANAGER_USER_ID = "pm-2"
CONTRACTS_OFFICER_USER_ID = "co-1"
SECOND_CONTRACTS_OFFICER_USER_ID = "co-2"
REVENUE_ACCOUNTANT_USER_ID = "ra-1"
FRAUD_ANALYST_USER_ID = "fa-1"
SECOND_FRAUD_ANALYST_USER_ID = "fa-2"

#: Placeholder identity for the two entity-backed roles, for use only where the
#: call under test is rejected before any scope comparison happens.
PLACEHOLDER_ENTITY_USER_ID = "00000000-0000-4000-8000-0000000000ff"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers(
        PROGRAM_ADMIN_USER_ID, "ProgramAdmin"
    ),
    "second_program_admin_headers": build_user_headers(
        SECOND_PROGRAM_ADMIN_USER_ID, "ProgramAdmin"
    ),
    "partner_manager_headers": build_user_headers(
        PARTNER_MANAGER_USER_ID, "PartnerManager"
    ),
    "second_partner_manager_headers": build_user_headers(
        SECOND_PARTNER_MANAGER_USER_ID, "PartnerManager"
    ),
    "contracts_officer_headers": build_user_headers(
        CONTRACTS_OFFICER_USER_ID, "ContractsOfficer"
    ),
    "second_contracts_officer_headers": build_user_headers(
        SECOND_CONTRACTS_OFFICER_USER_ID, "ContractsOfficer"
    ),
    "revenue_accountant_headers": build_user_headers(
        REVENUE_ACCOUNTANT_USER_ID, "RevenueAccountant"
    ),
    "fraud_analyst_headers": build_user_headers(
        FRAUD_ANALYST_USER_ID, "FraudAnalyst"
    ),
    "second_fraud_analyst_headers": build_user_headers(
        SECOND_FRAUD_ANALYST_USER_ID, "FraudAnalyst"
    ),
    # Entity-backed roles — placeholders for non-scoped calls only.
    "issuer_representative_headers": build_user_headers(
        PLACEHOLDER_ENTITY_USER_ID, "IssuerRepresentative"
    ),
    "member_headers": build_user_headers(PLACEHOLDER_ENTITY_USER_ID, "Member"),
}

PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
PROGRAM_ADMIN_2 = TEST_USERS["second_program_admin_headers"]
PARTNER_MANAGER = TEST_USERS["partner_manager_headers"]
PARTNER_MANAGER_2 = TEST_USERS["second_partner_manager_headers"]
CONTRACTS_OFFICER = TEST_USERS["contracts_officer_headers"]
CONTRACTS_OFFICER_2 = TEST_USERS["second_contracts_officer_headers"]
REVENUE_ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]
FRAUD_ANALYST = TEST_USERS["fraud_analyst_headers"]
FRAUD_ANALYST_2 = TEST_USERS["second_fraud_analyst_headers"]


def make_program_admin_headers(user_id: str) -> dict:
    """For a ProgramAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_partner_manager_headers(user_id: str) -> dict:
    """For a PartnerManager acting under a specific operator identifier."""
    return build_user_headers(user_id, "PartnerManager")


def make_contracts_officer_headers(user_id: str) -> dict:
    """For a ContractsOfficer acting under a specific operator identifier."""
    return build_user_headers(user_id, "ContractsOfficer")


def make_revenue_accountant_headers(user_id: str) -> dict:
    """For a RevenueAccountant acting under a specific operator identifier."""
    return build_user_headers(user_id, "RevenueAccountant")


def make_fraud_analyst_headers(user_id: str) -> dict:
    """For a FraudAnalyst acting under a specific operator identifier."""
    return build_user_headers(user_id, "FraudAnalyst")


def make_issuer_representative_headers(issuer_id: str) -> dict:
    """For an IssuerRepresentative: pass the acting CoBrandIssuer's own ``id``.

    Every issuer scope check compares the agreement's ``issuer_id`` against
    ``X-User-ID``, so a scoped call must carry the real issuer row id.
    """
    return build_user_headers(issuer_id, "IssuerRepresentative")


def make_member_headers(member_id: str) -> dict:
    """For a Member: pass the acting MemberAccount's own ``id``.

    Every member scope check compares the addressed row's owning member against
    ``X-User-ID``, so a scoped call must carry the real member row id.
    """
    return build_user_headers(member_id, "Member")


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/identifier pair, including undeclared roles."""
    return build_user_headers(user_id, role)


def headers_without_identity() -> dict:
    """Headers carrying neither ``X-User-ID`` nor ``X-User-Role``."""
    return {"Content-Type": "application/json"}
