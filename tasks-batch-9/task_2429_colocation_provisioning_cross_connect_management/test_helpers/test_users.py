"""Pre-built identity headers for every role the PRD declares.

Every request carries `X-User-ID` and `X-User-Role`. Four of the five roles are
operator roles whose `X-User-ID` is an opaque staff identifier, used only for the
segregation-of-duties and self-authorization comparisons — which is why several
numbered identities exist per role (a route may not be approved by the engineer who
raised the order, a ticket may not be authorized by the user who created it, and the
two decommission steps may not be recorded by the same user).

`CustomerAdmin` is different: its `X-User-ID` is the `Customer.id` it acts for, so
every ownership-gated call must be built per instance with
:func:`make_customer_admin_headers`. The shared `customer_admin_headers` constant
carries an identifier that owns nothing and is therefore only for role-gate and
scope-violation tests.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- opaque operator identities -------------------------------------------

ENGINEER_1_ID = "eng-1"
ENGINEER_2_ID = "eng-2"
ENGINEER_3_ID = "eng-3"

FACILITY_MANAGER_1_ID = "fm-1"
FACILITY_MANAGER_2_ID = "fm-2"

SECURITY_OFFICER_1_ID = "sec-1"
SECURITY_OFFICER_2_ID = "sec-2"

BILLING_OPERATOR_1_ID = "bill-1"
BILLING_OPERATOR_2_ID = "bill-2"

FOREIGN_CUSTOMER_ADMIN_ID = "cust-admin-owns-nothing"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # ProvisioningEngineer — opaque; three identities because duties are split
    # between the raiser of an order and the recorder of a second step.
    "provisioning_engineer_headers": build_user_headers(ENGINEER_1_ID, "ProvisioningEngineer"),
    "provisioning_engineer_2_headers": build_user_headers(ENGINEER_2_ID, "ProvisioningEngineer"),
    "provisioning_engineer_3_headers": build_user_headers(ENGINEER_3_ID, "ProvisioningEngineer"),
    # FacilityManager — opaque
    "facility_manager_headers": build_user_headers(FACILITY_MANAGER_1_ID, "FacilityManager"),
    "facility_manager_2_headers": build_user_headers(FACILITY_MANAGER_2_ID, "FacilityManager"),
    # SecurityOfficer — opaque
    "security_officer_headers": build_user_headers(SECURITY_OFFICER_1_ID, "SecurityOfficer"),
    "security_officer_2_headers": build_user_headers(SECURITY_OFFICER_2_ID, "SecurityOfficer"),
    # BillingOperator — opaque
    "billing_operator_headers": build_user_headers(BILLING_OPERATOR_1_ID, "BillingOperator"),
    "billing_operator_2_headers": build_user_headers(BILLING_OPERATOR_2_ID, "BillingOperator"),
    # CustomerAdmin — identity is the Customer.id, so this shared constant owns
    # nothing and is only for role-gate / scope-violation tests.
    "customer_admin_headers": build_user_headers(FOREIGN_CUSTOMER_ADMIN_ID, "CustomerAdmin"),
}


# --- per-instance builders -------------------------------------------------


def make_customer_admin_headers(customer_id: str) -> Dict[str, str]:
    """Headers for the `CustomerAdmin` role.

    Pass the real `Customer.id`: the customer scope check compares the owning
    customer of every addressed resource against `X-User-ID`.
    """
    return build_user_headers(customer_id, "CustomerAdmin")


def make_provisioning_engineer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary `ProvisioningEngineer` identity."""
    return build_user_headers(user_id, "ProvisioningEngineer")


def make_facility_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary `FacilityManager` identity."""
    return build_user_headers(user_id, "FacilityManager")


def make_security_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary `SecurityOfficer` identity."""
    return build_user_headers(user_id, "SecurityOfficer")


def make_billing_operator_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary `BillingOperator` identity."""
    return build_user_headers(user_id, "BillingOperator")


# Convenience aliases for the identities the setup helpers use by default.
ENGINEER_1 = TEST_USERS["provisioning_engineer_headers"]
ENGINEER_2 = TEST_USERS["provisioning_engineer_2_headers"]
ENGINEER_3 = TEST_USERS["provisioning_engineer_3_headers"]
FACILITY_MANAGER = TEST_USERS["facility_manager_headers"]
FACILITY_MANAGER_2 = TEST_USERS["facility_manager_2_headers"]
SECURITY_OFFICER = TEST_USERS["security_officer_headers"]
SECURITY_OFFICER_2 = TEST_USERS["security_officer_2_headers"]
BILLING_OPERATOR = TEST_USERS["billing_operator_headers"]
BILLING_OPERATOR_2 = TEST_USERS["billing_operator_2_headers"]

NO_ROLE_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
"""No `X-User-Role` at all — the unauthenticated case."""

UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers("who-1", "DataCentreTourist")
"""A syntactically present but undeclared role."""
