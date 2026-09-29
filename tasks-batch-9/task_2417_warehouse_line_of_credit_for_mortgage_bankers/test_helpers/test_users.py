"""Pre-built auth headers for every role the PRD declares.

The three lender-side roles (`CreditOfficer`, `CollateralAnalyst`,
`WireOperator`) take an opaque operator identifier in `X-User-ID`, so shared
constants are the canonical form for them.

The three counterparty roles are entity-backed: `X-User-ID` is the `id` of the
acting `WarehouseFacility` (`Borrower`), `DocumentCustodian` (`Custodian`) or
`TakeoutInvestor` (`Investor`). For those, always use the per-instance builder
with the real row's `id`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATOR_IDS

# ─── Shared constants ─────────────────────────────────────────────────────────
# Safe for the three opaque operator roles. The entity-backed entries exist only
# for tests that never reach an ownership check (missing-header, bad-payload and
# unresolvable-identity scenarios).
TEST_USERS = {
    "credit_officer_headers": build_user_headers(
        OPERATOR_IDS["CREDIT_OFFICER_PRIMARY"], "CreditOfficer"
    ),
    "second_credit_officer_headers": build_user_headers(
        OPERATOR_IDS["CREDIT_OFFICER_SECOND"], "CreditOfficer"
    ),
    "collateral_analyst_headers": build_user_headers(
        OPERATOR_IDS["COLLATERAL_ANALYST_PRIMARY"], "CollateralAnalyst"
    ),
    "second_collateral_analyst_headers": build_user_headers(
        OPERATOR_IDS["COLLATERAL_ANALYST_SECOND"], "CollateralAnalyst"
    ),
    "wire_operator_headers": build_user_headers(
        OPERATOR_IDS["WIRE_OPERATOR_PRIMARY"], "WireOperator"
    ),
    "second_wire_operator_headers": build_user_headers(
        OPERATOR_IDS["WIRE_OPERATOR_SECOND"], "WireOperator"
    ),
    # Entity-backed roles: unresolvable identity on purpose.
    "unresolvable_borrower_headers": build_user_headers(
        "not-a-uuid-in-any-table", "Borrower"
    ),
    "unresolvable_custodian_headers": build_user_headers(
        "not-a-uuid-in-any-table", "Custodian"
    ),
    "unresolvable_investor_headers": build_user_headers(
        "not-a-uuid-in-any-table", "Investor"
    ),
}

CREDIT_OFFICER = TEST_USERS["credit_officer_headers"]
SECOND_CREDIT_OFFICER = TEST_USERS["second_credit_officer_headers"]
COLLATERAL_ANALYST = TEST_USERS["collateral_analyst_headers"]
SECOND_COLLATERAL_ANALYST = TEST_USERS["second_collateral_analyst_headers"]
WIRE_OPERATOR = TEST_USERS["wire_operator_headers"]
SECOND_WIRE_OPERATOR = TEST_USERS["second_wire_operator_headers"]


# ─── Per-instance builders for the entity-backed roles ────────────────────────

def make_borrower_headers(facility_id: str) -> dict:
    """`Borrower` headers. `X-User-ID` is the acting `WarehouseFacility`'s `id`."""
    return build_user_headers(facility_id, "Borrower")


def make_custodian_headers(custodian_id: str) -> dict:
    """`Custodian` headers. `X-User-ID` is the acting `DocumentCustodian`'s `id`."""
    return build_user_headers(custodian_id, "Custodian")


def make_investor_headers(investor_id: str) -> dict:
    """`Investor` headers. `X-User-ID` is the acting `TakeoutInvestor`'s `id`."""
    return build_user_headers(investor_id, "Investor")


# ─── Per-instance builders for the opaque operator roles ─────────────────────

def make_credit_officer_headers(user_id: str) -> dict:
    """`CreditOfficer` headers with an explicit operator identifier."""
    return build_user_headers(user_id, "CreditOfficer")


def make_collateral_analyst_headers(user_id: str) -> dict:
    """`CollateralAnalyst` headers with an explicit operator identifier."""
    return build_user_headers(user_id, "CollateralAnalyst")


def make_wire_operator_headers(user_id: str) -> dict:
    """`WireOperator` headers with an explicit operator identifier."""
    return build_user_headers(user_id, "WireOperator")


def headers_for_role(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role/identifier pair.

    Used by the role-denial families, which re-send an identical body under
    every role that the endpoint does not authorise.
    """
    return build_user_headers(user_id, role)


CONTENT_TYPE_ONLY = {"Content-Type": "application/json"}
"""Headers carrying neither `X-User-ID` nor `X-User-Role`."""
