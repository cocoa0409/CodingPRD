"""Pre-built desk-role headers for every role the PRD recognizes.

Four of the five roles carry an opaque operator identifier in X-User-ID; the
AccountHolder's X-User-ID is the id of the acting shareholder account, so
ownership-gated calls must use make_account_holder_headers(account_id).
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the four opaque desk roles, and for any test that
# does not exercise shareholder-account ownership.
TEST_USERS = {
    "operator_headers": build_user_headers("tao-1", "TransferAgentOperator"),
    "accountant_headers": build_user_headers("fa-1", "FundAccountant"),
    "compliance_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "dealer_headers": build_user_headers("dlr-1", "DealerOperations"),
    # Fallback only: never use for an ownership-gated call.
    "account_holder_headers": build_user_headers("holder-1", "AccountHolder"),
}


def make_operator_headers(user_id: str) -> dict:
    """TransferAgentOperator acting under a specific operator identifier."""
    return build_user_headers(user_id, "TransferAgentOperator")


def make_accountant_headers(user_id: str) -> dict:
    """FundAccountant acting under a specific operator identifier.

    Used by the segregation-of-duties scenarios, where the accountant that opens
    a pricing error case must differ from the one that reprocesses it.
    """
    return build_user_headers(user_id, "FundAccountant")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer acting under a specific operator identifier.

    Used by the as-of approval scenarios, where the approving officer must differ
    from the actor that captured the order.
    """
    return build_user_headers(user_id, "ComplianceOfficer")


def make_dealer_headers(user_id: str) -> dict:
    """DealerOperations acting under a specific operator identifier."""
    return build_user_headers(user_id, "DealerOperations")


def make_account_holder_headers(account_id: str) -> dict:
    """AccountHolder acting on their own account.

    X-User-ID must be the id of the acting shareholder account: pass the real
    account id whenever the call is ownership-gated.
    """
    return build_user_headers(account_id, "AccountHolder")


def make_headers(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role string (including undeclared roles)."""
    return build_user_headers(user_id, role)
