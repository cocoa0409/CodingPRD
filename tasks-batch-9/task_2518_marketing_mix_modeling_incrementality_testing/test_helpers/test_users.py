"""Pre-built identity headers for every role.

Identity is deliberately opaque: any non-empty `X-User-ID` is accepted and only
`X-User-Role` decides capability. Two things follow, and both are exercised by
the suite:

* a second, distinct user id per role is needed for the two duty-separation
  rules, which compare the acting user id against a stored audit field rather
  than against a role name;
* the same user id may legitimately appear under two different role names, which
  is how a designer wearing the lead's hat is caught.
"""

from typing import Dict, Tuple

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ANALYTICS_LEAD,
    ROLE_AUDITOR,
    ROLE_BRAND_PLANNER,
    ROLE_DATA_ENGINEER,
    ROLE_EXPERIMENT_DESIGNER,
    ROLE_MODELER,
)

# --- Canonical user ids ----------------------------------------------------
# These strings are the ones the audit fields are expected to echo back.
DATA_ENGINEER_ID = "de-1"
MODELER_ID = "md-1"
EXPERIMENT_DESIGNER_ID = "ed-1"
ANALYTICS_LEAD_ID = "al-1"
BRAND_PLANNER_ID = "bp-1"
AUDITOR_ID = "au-1"

# --- Primary actor per role -------------------------------------------------
DATA_ENGINEER = build_user_headers(DATA_ENGINEER_ID, ROLE_DATA_ENGINEER)
MODELER = build_user_headers(MODELER_ID, ROLE_MODELER)
EXPERIMENT_DESIGNER = build_user_headers(EXPERIMENT_DESIGNER_ID, ROLE_EXPERIMENT_DESIGNER)
ANALYTICS_LEAD = build_user_headers(ANALYTICS_LEAD_ID, ROLE_ANALYTICS_LEAD)
BRAND_PLANNER = build_user_headers(BRAND_PLANNER_ID, ROLE_BRAND_PLANNER)
AUDITOR = build_user_headers(AUDITOR_ID, ROLE_AUDITOR)

# --- A second, distinct actor per role -------------------------------------
DATA_ENGINEER_2 = build_user_headers("de-2", ROLE_DATA_ENGINEER)
MODELER_2 = build_user_headers("md-2", ROLE_MODELER)
EXPERIMENT_DESIGNER_2 = build_user_headers("ed-2", ROLE_EXPERIMENT_DESIGNER)
ANALYTICS_LEAD_2 = build_user_headers("al-2", ROLE_ANALYTICS_LEAD)
BRAND_PLANNER_2 = build_user_headers("bp-2", ROLE_BRAND_PLANNER)
AUDITOR_2 = build_user_headers("au-2", ROLE_AUDITOR)

# --- One human wearing a second hat ----------------------------------------
# The designer's own user id presented under the lead's role name, and the
# planner's own user id presented under the lead's role name. Both clear the
# role check and must then fail the duty check on identity.
DESIGNER_AS_ANALYTICS_LEAD = build_user_headers(
    EXPERIMENT_DESIGNER_ID, ROLE_ANALYTICS_LEAD
)
PLANNER_AS_ANALYTICS_LEAD = build_user_headers(BRAND_PLANNER_ID, ROLE_ANALYTICS_LEAD)

# --- Rejected identities ---------------------------------------------------
NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_USER_ID: Dict[str, str] = {
    "X-User-Role": ROLE_DATA_ENGINEER,
    "Content-Type": "application/json",
}
MISSING_ROLE: Dict[str, str] = {
    "X-User-ID": DATA_ENGINEER_ID,
    "Content-Type": "application/json",
}
EMPTY_USER_ID = build_user_headers("", ROLE_DATA_ENGINEER)
EMPTY_ROLE = build_user_headers(DATA_ENGINEER_ID, "")
UNKNOWN_ROLE = build_user_headers("xx-1", "MarketingIntern")

# --- Lookup helpers --------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_DATA_ENGINEER: DATA_ENGINEER,
    ROLE_MODELER: MODELER,
    ROLE_EXPERIMENT_DESIGNER: EXPERIMENT_DESIGNER,
    ROLE_ANALYTICS_LEAD: ANALYTICS_LEAD,
    ROLE_BRAND_PLANNER: BRAND_PLANNER,
    ROLE_AUDITOR: AUDITOR,
}

SECOND_TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_DATA_ENGINEER: DATA_ENGINEER_2,
    ROLE_MODELER: MODELER_2,
    ROLE_EXPERIMENT_DESIGNER: EXPERIMENT_DESIGNER_2,
    ROLE_ANALYTICS_LEAD: ANALYTICS_LEAD_2,
    ROLE_BRAND_PLANNER: BRAND_PLANNER_2,
    ROLE_AUDITOR: AUDITOR_2,
}

# Every reader in the contract: all six roles may read every collection.
ALL_READERS: Tuple[Dict[str, str], ...] = (
    DATA_ENGINEER,
    MODELER,
    EXPERIMENT_DESIGNER,
    ANALYTICS_LEAD,
    BRAND_PLANNER,
    AUDITOR,
)


def headers_for(role: str) -> Dict[str, str]:
    """Primary headers for a role name."""
    return TEST_USERS[role]


def other_headers_for(role: str) -> Dict[str, str]:
    """A second, distinct user id under the same role name."""
    return SECOND_TEST_USERS[role]


def user_id_of(headers: Dict[str, str]) -> str:
    """The acting user id carried by a header dict."""
    return headers["X-User-ID"]


def role_of(headers: Dict[str, str]) -> str:
    """The acting role carried by a header dict."""
    return headers["X-User-Role"]


def roles_other_than(*allowed: str) -> Tuple[str, ...]:
    """Every role name outside the given set, in declaration order."""
    return tuple(role for role in TEST_USERS if role not in allowed)
