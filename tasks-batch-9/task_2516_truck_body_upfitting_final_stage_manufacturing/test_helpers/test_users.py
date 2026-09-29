"""Pre-built auth headers for every role of PRD §2.1.

The six internal roles authenticate with an opaque operator identifier; the
``Customer`` role authenticates with the ``id`` of its own ``Customer`` row,
which is why customer headers must be built at runtime from a created record.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CUSTOMER,
    ROLE_INSTALL_TECHNICIAN,
    ROLE_PLANT_ADMIN,
    ROLE_PRODUCTION_SCHEDULER,
    ROLE_UPFIT_ENGINEER,
    ROLE_WARRANTY_ADMINISTRATOR,
    USER_ADMIN,
    USER_ENGINEER,
    USER_OFFICER,
    USER_OFFICER_ALT,
    USER_SCHEDULER,
    USER_SCHEDULER_ALT,
    USER_TECHNICIAN,
    USER_WARRANTY,
)

ADMIN = build_user_headers(USER_ADMIN, ROLE_PLANT_ADMIN)
SCHEDULER = build_user_headers(USER_SCHEDULER, ROLE_PRODUCTION_SCHEDULER)
SCHEDULER_ALT = build_user_headers(USER_SCHEDULER_ALT, ROLE_PRODUCTION_SCHEDULER)
ENGINEER = build_user_headers(USER_ENGINEER, ROLE_UPFIT_ENGINEER)
TECHNICIAN = build_user_headers(USER_TECHNICIAN, ROLE_INSTALL_TECHNICIAN)
OFFICER = build_user_headers(USER_OFFICER, ROLE_COMPLIANCE_OFFICER)
OFFICER_ALT = build_user_headers(USER_OFFICER_ALT, ROLE_COMPLIANCE_OFFICER)
WARRANTY_ADMIN = build_user_headers(USER_WARRANTY, ROLE_WARRANTY_ADMINISTRATOR)

# An operator identity wearing a role it does not normally hold. Used where a
# segregation-of-duties author must be tested against the role check that
# outranks it in the ladder of §2.6.
OFFICER_AS_ENGINEER = build_user_headers(USER_OFFICER, ROLE_UPFIT_ENGINEER)

STAFF_HEADERS = {
    ROLE_PLANT_ADMIN: ADMIN,
    ROLE_PRODUCTION_SCHEDULER: SCHEDULER,
    ROLE_UPFIT_ENGINEER: ENGINEER,
    ROLE_INSTALL_TECHNICIAN: TECHNICIAN,
    ROLE_COMPLIANCE_OFFICER: OFFICER,
    ROLE_WARRANTY_ADMINISTRATOR: WARRANTY_ADMIN,
}

# Requests that fail the authentication check of §2.1 outright.
NO_HEADERS: Dict[str, str] = {}
MISSING_ROLE = {"X-User-ID": USER_ADMIN, "Content-Type": "application/json"}
MISSING_USER_ID = {"X-User-Role": ROLE_PLANT_ADMIN, "Content-Type": "application/json"}
EMPTY_USER_ID = build_user_headers("", ROLE_PLANT_ADMIN)
EMPTY_ROLE = build_user_headers(USER_ADMIN, "")
UNKNOWN_ROLE = build_user_headers(USER_ADMIN, "PlantSuperintendent")


def customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for a ``Customer`` caller acting as the given Customer row."""
    return build_user_headers(customer_id, ROLE_CUSTOMER)


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/identity pairing."""
    return build_user_headers(user_id, role)
