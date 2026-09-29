"""Caller identities for the six roles of PRD section 2.1.

Two roles are entity-backed: a Manufacturer's X-User-ID is the id of the
acting manufacturer row, and a Retailer's X-User-ID is the id of the acting
retailer row. Those two identities therefore cannot be constants — they must
be built per test from the row the fixture just created, which is what the
make_*_headers() builders below are for.

The other four roles are opaque operator identities. Two distinct FraudAnalyst
identities and two distinct SettlementOfficer identities are provided because
both segregation-of-duties walls require the second actor to differ from the
first.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Opaque operator identifiers -------------------------------------------
INTAKE_CLERK_ID = "clerk-1"
FRAUD_ANALYST_ID = "fa-1"
FRAUD_ANALYST_2_ID = "fa-2"
SETTLEMENT_OFFICER_ID = "so-1"
SETTLEMENT_OFFICER_2_ID = "so-2"
CLEARINGHOUSE_ADMIN_ID = "admin-1"

ROLE_MANUFACTURER = "Manufacturer"
ROLE_RETAILER = "Retailer"
ROLE_INTAKE_CLERK = "IntakeClerk"
ROLE_FRAUD_ANALYST = "FraudAnalyst"
ROLE_SETTLEMENT_OFFICER = "SettlementOfficer"
ROLE_CLEARINGHOUSE_ADMIN = "ClearinghouseAdmin"

ALL_ROLES = (
    ROLE_MANUFACTURER,
    ROLE_RETAILER,
    ROLE_INTAKE_CLERK,
    ROLE_FRAUD_ANALYST,
    ROLE_SETTLEMENT_OFFICER,
    ROLE_CLEARINGHOUSE_ADMIN,
)

# --- Ready-made headers for the four opaque roles ---------------------------
CLERK = build_user_headers(INTAKE_CLERK_ID, ROLE_INTAKE_CLERK)
ANALYST = build_user_headers(FRAUD_ANALYST_ID, ROLE_FRAUD_ANALYST)
ANALYST_2 = build_user_headers(FRAUD_ANALYST_2_ID, ROLE_FRAUD_ANALYST)
OFFICER = build_user_headers(SETTLEMENT_OFFICER_ID, ROLE_SETTLEMENT_OFFICER)
OFFICER_2 = build_user_headers(SETTLEMENT_OFFICER_2_ID, ROLE_SETTLEMENT_OFFICER)
ADMIN = build_user_headers(CLEARINGHOUSE_ADMIN_ID, ROLE_CLEARINGHOUSE_ADMIN)


def make_manufacturer_headers(manufacturer_id: str) -> Dict[str, str]:
    """Headers for a Manufacturer acting on its own rows."""
    return build_user_headers(manufacturer_id, ROLE_MANUFACTURER)


def make_retailer_headers(retailer_id: str) -> Dict[str, str]:
    """Headers for a Retailer acting on its own rows."""
    return build_user_headers(retailer_id, ROLE_RETAILER)


def make_clerk_headers(user_id: str = INTAKE_CLERK_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INTAKE_CLERK)


def make_analyst_headers(user_id: str = FRAUD_ANALYST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FRAUD_ANALYST)


def make_officer_headers(user_id: str = SETTLEMENT_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SETTLEMENT_OFFICER)


def make_admin_headers(user_id: str = CLEARINGHOUSE_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CLEARINGHOUSE_ADMIN)


def headers_missing_both() -> Dict[str, str]:
    """No identity headers at all."""
    return {"Content-Type": "application/json"}


def headers_missing_role(user_id: str = CLEARINGHOUSE_ADMIN_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user(role: str = ROLE_CLEARINGHOUSE_ADMIN) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_role(user_id: str = CLEARINGHOUSE_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "")


def headers_unknown_role(user_id: str = CLEARINGHOUSE_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "Auditor")
