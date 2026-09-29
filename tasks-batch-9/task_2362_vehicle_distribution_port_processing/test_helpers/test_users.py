"""Acting identities for the Vehicle Distribution & Port Processing API.

Every request must carry ``X-User-ID`` (the acting user) and ``X-User-Role``
(the capacity in which they act).  For the five operator roles the
``X-User-ID`` is an opaque operator identifier that the server records into
actor fields but never compares against an entity ``id``.  For the ``Dealer``
role the ``X-User-ID`` *is* the ``id`` of the acting dealer record, so a
dealer identity can only be built once the dealer row exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --------------------------------------------------------------------------
# The six declared roles
# --------------------------------------------------------------------------
ROLE_PORT_OPERATIONS_PLANNER = "PortOperationsPlanner"
ROLE_DAMAGE_SURVEYOR = "DamageSurveyor"
ROLE_ACCESSORY_TECHNICIAN = "AccessoryTechnician"
ROLE_QUALITY_INSPECTOR = "QualityInspector"
ROLE_DISTRIBUTION_MANAGER = "DistributionManager"
ROLE_DEALER = "Dealer"

ALL_ROLES = (
    ROLE_PORT_OPERATIONS_PLANNER,
    ROLE_DAMAGE_SURVEYOR,
    ROLE_ACCESSORY_TECHNICIAN,
    ROLE_QUALITY_INSPECTOR,
    ROLE_DISTRIBUTION_MANAGER,
    ROLE_DEALER,
)

#: A role string that is not one of the six declared roles.
UNDECLARED_ROLE = "YardHostler"


@dataclass(frozen=True)
class TestUser:
    """An acting identity: an ``X-User-ID`` paired with an ``X-User-Role``."""

    user_id: str
    role: str

    def headers(self) -> Dict[str, str]:
        return build_user_headers(self.user_id, self.role)

    def with_role(self, role: str) -> "TestUser":
        """Same operator identifier acting in a different declared capacity."""
        return TestUser(user_id=self.user_id, role=role)


# --------------------------------------------------------------------------
# Operator identities (opaque X-User-ID values)
# --------------------------------------------------------------------------
PLANNER = TestUser("u-pop-1", ROLE_PORT_OPERATIONS_PLANNER)
PLANNER_2 = TestUser("u-pop-2", ROLE_PORT_OPERATIONS_PLANNER)

SURVEYOR = TestUser("u-ds-1", ROLE_DAMAGE_SURVEYOR)
SURVEYOR_2 = TestUser("u-ds-2", ROLE_DAMAGE_SURVEYOR)

TECHNICIAN = TestUser("u-tech-1", ROLE_ACCESSORY_TECHNICIAN)
TECHNICIAN_2 = TestUser("u-tech-2", ROLE_ACCESSORY_TECHNICIAN)

INSPECTOR = TestUser("u-qc-1", ROLE_QUALITY_INSPECTOR)
INSPECTOR_2 = TestUser("u-qc-2", ROLE_QUALITY_INSPECTOR)

MANAGER = TestUser("u-dm-1", ROLE_DISTRIBUTION_MANAGER)
MANAGER_2 = TestUser("u-dm-2", ROLE_DISTRIBUTION_MANAGER)

# ``u-dual-1`` acts first as the technician who installs an accessory and then
# tries to act as the inspector of the same unit; ``u-dual-2`` files a claim as
# a surveyor and then tries to settle it as a manager.  Both exist so the
# segregation-of-duties comparisons have a single operator identifier on both
# sides of the check.
DUAL_TECH = TestUser("u-dual-1", ROLE_ACCESSORY_TECHNICIAN)
DUAL_INSPECTOR = TestUser("u-dual-1", ROLE_QUALITY_INSPECTOR)
DUAL_SURVEYOR = TestUser("u-dual-2", ROLE_DAMAGE_SURVEYOR)
DUAL_MANAGER = TestUser("u-dual-2", ROLE_DISTRIBUTION_MANAGER)


def dealer_user(dealer_id: str) -> TestUser:
    """Build the consignee identity for a dealer record.

    The acting ``X-User-ID`` for the ``Dealer`` role is the ``id`` of the
    dealer record itself.
    """
    return TestUser(dealer_id, ROLE_DEALER)


#: One representative identity for each of the six declared roles, keyed by
#: role name.  ``Dealer`` is intentionally absent because a dealer identity
#: requires a persisted dealer ``id``; use :func:`dealer_user`.
OPERATOR_BY_ROLE: Dict[str, TestUser] = {
    ROLE_PORT_OPERATIONS_PLANNER: PLANNER,
    ROLE_DAMAGE_SURVEYOR: SURVEYOR,
    ROLE_ACCESSORY_TECHNICIAN: TECHNICIAN,
    ROLE_QUALITY_INSPECTOR: INSPECTOR,
    ROLE_DISTRIBUTION_MANAGER: MANAGER,
}


def headers_without_role(user_id: str = "u-anon-1") -> Dict[str, str]:
    """Headers carrying only ``X-User-ID`` — ``X-User-Role`` is absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user(role: str = ROLE_PORT_OPERATIONS_PLANNER) -> Dict[str, str]:
    """Headers carrying only ``X-User-Role`` — ``X-User-ID`` is absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_no_identity() -> Dict[str, str]:
    """Headers carrying neither identity header."""
    return {"Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = "u-anon-1") -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is not one of the six declared roles."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
