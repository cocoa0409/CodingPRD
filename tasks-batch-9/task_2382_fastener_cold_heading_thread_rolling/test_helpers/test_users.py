"""Pre-built operator headers for every role in PRD §2.1.

Identity in this API is deliberately shallow: PRD §2.1 states that for every one
of the six roles the ``X-User-ID`` is "an opaque operator identifier not tied to
any persisted entity", and that the server "never compares ``X-User-ID`` to any
entity's ``id``". The only comparison the system makes between operator
identifiers is the segregation-of-duties check of PRD §2.11, which compares the
acting ``X-User-ID`` against a stored ``performed_by_user_id``. The per-role
builders below exist so tests can pick a *specific* operator identifier for that
check (for example: open a test as ``insp-1`` then try to sign as ``insp-1``).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Stable operator identifiers used across the suite.
USER_IDS = {
    "PROCESS_ENGINEER": "eng-1",
    "HEAT_TREAT_OPERATOR": "ht-1",
    "QUALITY_INSPECTOR": "insp-1",
    "QUALITY_INSPECTOR_ALT": "insp-2",
    "QUALITY_MANAGER": "qm-1",
    "QUALITY_MANAGER_ALT": "qm-2",
    "SHIPPING_CLERK": "ship-1",
    "PLANT_ADMIN": "admin-1",
}

TEST_USERS: Dict[str, Dict[str, str]] = {
    "engineer_headers": build_user_headers("eng-1", "ProcessEngineer"),
    "heat_treat_headers": build_user_headers("ht-1", "HeatTreatOperator"),
    "inspector_headers": build_user_headers("insp-1", "QualityInspector"),
    "inspector_alt_headers": build_user_headers("insp-2", "QualityInspector"),
    "manager_headers": build_user_headers("qm-1", "QualityManager"),
    "manager_alt_headers": build_user_headers("qm-2", "QualityManager"),
    "clerk_headers": build_user_headers("ship-1", "ShippingClerk"),
    "admin_headers": build_user_headers("admin-1", "PlantAdmin"),
}

# Role name -> a header dict for that role. Handy for parametrized RBAC sweeps.
HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    "ProcessEngineer": TEST_USERS["engineer_headers"],
    "HeatTreatOperator": TEST_USERS["heat_treat_headers"],
    "QualityInspector": TEST_USERS["inspector_headers"],
    "QualityManager": TEST_USERS["manager_headers"],
    "ShippingClerk": TEST_USERS["clerk_headers"],
    "PlantAdmin": TEST_USERS["admin_headers"],
}


def make_engineer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ProcessEngineer acting under a specific operator identifier."""
    return build_user_headers(user_id, "ProcessEngineer")


def make_heat_treat_headers(user_id: str) -> Dict[str, str]:
    """Headers for a HeatTreatOperator acting under a specific operator identifier."""
    return build_user_headers(user_id, "HeatTreatOperator")


def make_inspector_headers(user_id: str) -> Dict[str, str]:
    """Headers for a QualityInspector acting under a specific operator identifier.

    Use this when a test needs the identifier stored as ``performed_by_user_id``
    on a lot test, or as ``verified_by_user_id`` on a steel heat.
    """
    return build_user_headers(user_id, "QualityInspector")


def make_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for a QualityManager acting under a specific operator identifier.

    Use this when a test needs the signing identifier to equal (or differ from)
    a lot test's stored ``performed_by_user_id``.
    """
    return build_user_headers(user_id, "QualityManager")


def make_clerk_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ShippingClerk acting under a specific operator identifier."""
    return build_user_headers(user_id, "ShippingClerk")


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a PlantAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "PlantAdmin")


def headers_without_role(user_id: str = "eng-1") -> Dict[str, str]:
    """A request carrying X-User-ID but no X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "ProcessEngineer") -> Dict[str, str]:
    """A request carrying X-User-Role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "eng-1") -> Dict[str, str]:
    """A request declaring a role the plant does not recognise."""
    return build_user_headers(user_id, "PlantSupervisor")
