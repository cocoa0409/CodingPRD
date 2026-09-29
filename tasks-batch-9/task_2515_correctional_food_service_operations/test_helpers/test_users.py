"""Pre-built authentication headers for every role in the PRD.

Identity is opaque: the API accepts any non-empty `X-User-ID` and only the role
name is checked, so the same user string may legitimately appear under different
roles. Distinct user strings are provided per role so that the
segregation-of-duties rules can be exercised in both directions.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Primary actor per role --------------------------------------------------

CONTRACT_ADMIN = build_user_headers("ca-001", "ContractAdministrator")
FOOD_SUPERVISOR = build_user_headers("fs-001", "FoodServiceSupervisor")
DIETITIAN = build_user_headers("rd-001", "RegisteredDietitian")
OFFICER = build_user_headers("co-001", "CorrectionalOfficer")
MEDICAL = build_user_headers("md-001", "MedicalProvider")
CHAPLAIN = build_user_headers("ch-001", "ChaplainDesignee")
GRIEVANCE_COORD = build_user_headers("gc-001", "GrievanceCoordinator")
AUDITOR = build_user_headers("au-001", "ComplianceAuditor")

# --- Second, distinct actor per role (for segregation-of-duties pairs) -------

CONTRACT_ADMIN_2 = build_user_headers("ca-002", "ContractAdministrator")
FOOD_SUPERVISOR_2 = build_user_headers("fs-002", "FoodServiceSupervisor")
DIETITIAN_2 = build_user_headers("rd-002", "RegisteredDietitian")
OFFICER_2 = build_user_headers("co-002", "CorrectionalOfficer")
MEDICAL_2 = build_user_headers("md-002", "MedicalProvider")
CHAPLAIN_2 = build_user_headers("ch-002", "ChaplainDesignee")
GRIEVANCE_COORD_2 = build_user_headers("gc-002", "GrievanceCoordinator")
AUDITOR_2 = build_user_headers("au-002", "ComplianceAuditor")

# --- A single human wearing two hats ----------------------------------------
# The same user string under two different role names: used to prove the
# segregation-of-duties comparison is on the user id, not on the role.

DUAL_HAT_DIETITIAN = build_user_headers("du-001", "RegisteredDietitian")
DUAL_HAT_CONTRACT_ADMIN = build_user_headers("du-001", "ContractAdministrator")
DUAL_HAT_OFFICER = build_user_headers("du-001", "CorrectionalOfficer")
DUAL_HAT_SUPERVISOR = build_user_headers("du-001", "FoodServiceSupervisor")

# --- Malformed / rejected identities ----------------------------------------

UNKNOWN_ROLE = build_user_headers("xx-001", "KitchenIntern")
MISSING_USER_ID = {"X-User-Role": "ContractAdministrator", "Content-Type": "application/json"}
EMPTY_USER_ID = build_user_headers("", "ContractAdministrator")
MISSING_ROLE = {"X-User-ID": "ca-001", "Content-Type": "application/json"}
EMPTY_ROLE = build_user_headers("ca-001", "")

# --- Lookup table by role name ----------------------------------------------

TEST_USERS: Dict[str, Dict[str, str]] = {
    "ContractAdministrator": CONTRACT_ADMIN,
    "FoodServiceSupervisor": FOOD_SUPERVISOR,
    "RegisteredDietitian": DIETITIAN,
    "CorrectionalOfficer": OFFICER,
    "MedicalProvider": MEDICAL,
    "ChaplainDesignee": CHAPLAIN,
    "GrievanceCoordinator": GRIEVANCE_COORD,
    "ComplianceAuditor": AUDITOR,
}


def headers_for(role: str) -> Dict[str, str]:
    """Return the primary headers for a role name."""
    return TEST_USERS[role]


def user_id_of(headers: Dict[str, str]) -> str:
    """Extract the acting user id from a header dict."""
    return headers["X-User-ID"]
