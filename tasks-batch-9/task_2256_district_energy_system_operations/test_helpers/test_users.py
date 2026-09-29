"""Auth header sets for the six roles the API recognises.

Five of the six roles act under an opaque operator identifier that is never
compared to any entity id, so a shared constant header dict is enough for them —
except where a workflow stores the acting identifier for an audit trail (plan
authorship, work-order reporting), in which case tests need a second distinct
identity of the same role and use the per-identity builders below.

The sixth role, ``CustomerAccount``, is entity-backed: its ``X-User-ID`` is the
``id`` of the acting ConnectionAgreement. Ownership-gated calls must therefore
always be made with ``make_customer_account_headers(agreement["id"])`` and never
with a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_SYSTEM_CONTROLLER = "SystemController"
ROLE_DISPATCH_OPERATOR = "DispatchOperator"
ROLE_NETWORK_ENGINEER = "NetworkEngineer"
ROLE_FIELD_TECHNICIAN = "FieldTechnician"
ROLE_BILLING_ANALYST = "BillingAnalyst"
ROLE_CUSTOMER_ACCOUNT = "CustomerAccount"

ALL_ROLES = (
    ROLE_SYSTEM_CONTROLLER,
    ROLE_DISPATCH_OPERATOR,
    ROLE_NETWORK_ENGINEER,
    ROLE_FIELD_TECHNICIAN,
    ROLE_BILLING_ANALYST,
    ROLE_CUSTOMER_ACCOUNT,
)

# Canonical opaque operator identifiers used across the suite.
CTRL_1 = "ctrl-1"
CTRL_2 = "ctrl-2"
OP_1 = "op-1"
OP_2 = "op-2"
ENG_1 = "eng-1"
ENG_2 = "eng-2"
TECH_1 = "tech-1"
TECH_2 = "tech-2"
BILL_1 = "bill-1"
BILL_2 = "bill-2"


# ─── Per-identity builders ──────────────────────────────────────────────────


def make_system_controller_headers(user_id: str = CTRL_1) -> dict:
    """Headers for a SystemController acting under a specific operator id."""
    return build_user_headers(user_id, ROLE_SYSTEM_CONTROLLER)


def make_dispatch_operator_headers(user_id: str = OP_1) -> dict:
    """Headers for a DispatchOperator; the id lands in a plan's author field."""
    return build_user_headers(user_id, ROLE_DISPATCH_OPERATOR)


def make_network_engineer_headers(user_id: str = ENG_1) -> dict:
    """Headers for a NetworkEngineer acting under a specific operator id."""
    return build_user_headers(user_id, ROLE_NETWORK_ENGINEER)


def make_field_technician_headers(user_id: str = TECH_1) -> dict:
    """Headers for a FieldTechnician; the id lands in a work order's reporter."""
    return build_user_headers(user_id, ROLE_FIELD_TECHNICIAN)


def make_billing_analyst_headers(user_id: str = BILL_1) -> dict:
    """Headers for a BillingAnalyst acting under a specific operator id."""
    return build_user_headers(user_id, ROLE_BILLING_ANALYST)


def make_customer_account_headers(agreement_id: str) -> dict:
    """Headers for the connected customer itself.

    ``agreement_id`` must be the id of the ConnectionAgreement the customer is
    acting as; ownership checks compare a resource's agreement foreign key
    against this value.
    """
    return build_user_headers(agreement_id, ROLE_CUSTOMER_ACCOUNT)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/identifier pair, including unknown roles."""
    return build_user_headers(user_id, role)


# ─── Shared constants ───────────────────────────────────────────────────────

TEST_USERS = {
    "system_controller": make_system_controller_headers(CTRL_1),
    "system_controller_alt": make_system_controller_headers(CTRL_2),
    "dispatch_operator": make_dispatch_operator_headers(OP_1),
    "dispatch_operator_alt": make_dispatch_operator_headers(OP_2),
    "network_engineer": make_network_engineer_headers(ENG_1),
    "network_engineer_alt": make_network_engineer_headers(ENG_2),
    "field_technician": make_field_technician_headers(TECH_1),
    "field_technician_alt": make_field_technician_headers(TECH_2),
    "billing_analyst": make_billing_analyst_headers(BILL_1),
    "billing_analyst_alt": make_billing_analyst_headers(BILL_2),
}

SYSTEM_CONTROLLER = TEST_USERS["system_controller"]
SYSTEM_CONTROLLER_ALT = TEST_USERS["system_controller_alt"]
DISPATCH_OPERATOR = TEST_USERS["dispatch_operator"]
DISPATCH_OPERATOR_ALT = TEST_USERS["dispatch_operator_alt"]
NETWORK_ENGINEER = TEST_USERS["network_engineer"]
NETWORK_ENGINEER_ALT = TEST_USERS["network_engineer_alt"]
FIELD_TECHNICIAN = TEST_USERS["field_technician"]
FIELD_TECHNICIAN_ALT = TEST_USERS["field_technician_alt"]
BILLING_ANALYST = TEST_USERS["billing_analyst"]
BILLING_ANALYST_ALT = TEST_USERS["billing_analyst_alt"]

__all__ = [
    "ROLE_SYSTEM_CONTROLLER",
    "ROLE_DISPATCH_OPERATOR",
    "ROLE_NETWORK_ENGINEER",
    "ROLE_FIELD_TECHNICIAN",
    "ROLE_BILLING_ANALYST",
    "ROLE_CUSTOMER_ACCOUNT",
    "ALL_ROLES",
    "CTRL_1",
    "CTRL_2",
    "OP_1",
    "OP_2",
    "ENG_1",
    "ENG_2",
    "TECH_1",
    "TECH_2",
    "BILL_1",
    "BILL_2",
    "make_system_controller_headers",
    "make_dispatch_operator_headers",
    "make_network_engineer_headers",
    "make_field_technician_headers",
    "make_billing_analyst_headers",
    "make_customer_account_headers",
    "make_headers",
    "TEST_USERS",
    "SYSTEM_CONTROLLER",
    "SYSTEM_CONTROLLER_ALT",
    "DISPATCH_OPERATOR",
    "DISPATCH_OPERATOR_ALT",
    "NETWORK_ENGINEER",
    "NETWORK_ENGINEER_ALT",
    "FIELD_TECHNICIAN",
    "FIELD_TECHNICIAN_ALT",
    "BILLING_ANALYST",
    "BILLING_ANALYST_ALT",
]
