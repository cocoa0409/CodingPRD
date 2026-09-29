"""
Principals and auth headers.

Four of the five roles carry an opaque operator identifier that "the server
records ... but never compares ... to any entity's id" (PRD 2.1), so a fixed
constant per operator is safe and two distinct operators per role are provided
for the segregation-of-duties rules of PRD 2.10.

``VendorOperator`` is different in kind: "When ``X-User-Role`` is
``VendorOperator``, ``X-User-ID`` is the ``id`` of the acting Vendor". There is
therefore no constant operator identity for that role - every VendorOperator call
must thread the id of the vendor being acted for through
``make_vendor_operator_headers``.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers. Two per role so that a create and the action that
# must not be taken by the creator can use different principals.
ANALYST_ONE = "ana-001"
ANALYST_TWO = "ana-002"
SUPERVISOR_ONE = "sup-001"
SUPERVISOR_TWO = "sup-002"
INVESTIGATOR_ONE = "inv-001"
INVESTIGATOR_TWO = "inv-002"
SYSTEM_ONE = "sys-001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "analyst_one": {"user_id": ANALYST_ONE, "role": Role.VENDOR_UNIT_ANALYST.value},
    "analyst_two": {"user_id": ANALYST_TWO, "role": Role.VENDOR_UNIT_ANALYST.value},
    "supervisor_one": {
        "user_id": SUPERVISOR_ONE,
        "role": Role.VENDOR_UNIT_SUPERVISOR.value,
    },
    "supervisor_two": {
        "user_id": SUPERVISOR_TWO,
        "role": Role.VENDOR_UNIT_SUPERVISOR.value,
    },
    "investigator_one": {
        "user_id": INVESTIGATOR_ONE,
        "role": Role.COMPLIANCE_INVESTIGATOR.value,
    },
    "investigator_two": {
        "user_id": INVESTIGATOR_TWO,
        "role": Role.COMPLIANCE_INVESTIGATOR.value,
    },
    "system_operator": {"user_id": SYSTEM_ONE, "role": Role.SYSTEM_OPERATOR.value},
}


# --- Ready-made header dicts for the opaque roles ---------------------------

ANALYST_HEADERS = build_user_headers(ANALYST_ONE, Role.VENDOR_UNIT_ANALYST.value)
ANALYST_TWO_HEADERS = build_user_headers(ANALYST_TWO, Role.VENDOR_UNIT_ANALYST.value)
SUPERVISOR_HEADERS = build_user_headers(
    SUPERVISOR_ONE, Role.VENDOR_UNIT_SUPERVISOR.value
)
SUPERVISOR_TWO_HEADERS = build_user_headers(
    SUPERVISOR_TWO, Role.VENDOR_UNIT_SUPERVISOR.value
)
INVESTIGATOR_HEADERS = build_user_headers(
    INVESTIGATOR_ONE, Role.COMPLIANCE_INVESTIGATOR.value
)
INVESTIGATOR_TWO_HEADERS = build_user_headers(
    INVESTIGATOR_TWO, Role.COMPLIANCE_INVESTIGATOR.value
)
SYSTEM_HEADERS = build_user_headers(SYSTEM_ONE, Role.SYSTEM_OPERATOR.value)


# --- Builders ---------------------------------------------------------------


def make_analyst_headers(user_id: str = ANALYST_ONE) -> Dict[str, str]:
    """Headers for a VendorUnitAnalyst acting under the given operator id."""
    return build_user_headers(user_id, Role.VENDOR_UNIT_ANALYST.value)


def make_supervisor_headers(user_id: str = SUPERVISOR_ONE) -> Dict[str, str]:
    """Headers for a VendorUnitSupervisor acting under the given operator id."""
    return build_user_headers(user_id, Role.VENDOR_UNIT_SUPERVISOR.value)


def make_investigator_headers(user_id: str = INVESTIGATOR_ONE) -> Dict[str, str]:
    """Headers for a ComplianceInvestigator acting under the given operator id."""
    return build_user_headers(user_id, Role.COMPLIANCE_INVESTIGATOR.value)


def make_system_operator_headers(user_id: str = SYSTEM_ONE) -> Dict[str, str]:
    """Headers for a SystemOperator acting under the given operator id."""
    return build_user_headers(user_id, Role.SYSTEM_OPERATOR.value)


def make_vendor_operator_headers(vendor_id: str) -> Dict[str, str]:
    """
    Headers for the retail vendor itself.

    ``X-User-ID`` is the ``id`` of the acting Vendor, so ownership checks compare
    a resource's vendor foreign key against this value. Pass the id of the vendor
    the request is made on behalf of; never a fixed operator constant.
    """
    return build_user_headers(vendor_id, Role.VENDOR_OPERATOR.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary principal and role string."""
    return build_user_headers(user_id, role)


def make_partial_headers(
    user_id: Optional[str] = None, role: Optional[str] = None
) -> Dict[str, str]:
    """
    Headers with either identity header deliberately omitted.

    Used to exercise "If either header is absent ... the request is rejected"
    (PRD 2.1). A ``None`` argument leaves that header out entirely.
    """
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers
