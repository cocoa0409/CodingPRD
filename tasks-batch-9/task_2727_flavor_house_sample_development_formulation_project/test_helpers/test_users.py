"""Pre-built role headers for the six roles named in the PRD.

No role in this API is backed by a persisted entity: X-User-ID is an opaque
operator identifier that the server never compares against any entity's id.
The shared constants below are therefore the canonical form for ordinary
calls.  The per-role builders exist for the two segregation-of-duties rules,
where the server compares a later caller's X-User-ID against a value it
stamped earlier and the test must therefore control the operator identity.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "account_manager_headers": build_user_headers("u_am_1", "AccountManager"),
    "technical_director_headers": build_user_headers("u_dir_1", "TechnicalDirector"),
    "flavorist_headers": build_user_headers("u_flav_1", "Flavorist"),
    "regulatory_affairs_headers": build_user_headers("u_reg_1", "RegulatoryAffairs"),
    "lab_tech_headers": build_user_headers("u_lab_1", "LabTech"),
    "purchasing_manager_headers": build_user_headers("u_purch_1", "PurchasingManager"),
}


def make_account_manager_headers(user_id: str) -> dict:
    """Headers for an AccountManager acting as the given operator identity."""
    return build_user_headers(user_id, "AccountManager")


def make_technical_director_headers(user_id: str) -> dict:
    """Headers for a TechnicalDirector acting as the given operator identity."""
    return build_user_headers(user_id, "TechnicalDirector")


def make_flavorist_headers(user_id: str) -> dict:
    """Headers for a Flavorist acting as the given operator identity."""
    return build_user_headers(user_id, "Flavorist")


def make_regulatory_affairs_headers(user_id: str) -> dict:
    """Headers for RegulatoryAffairs acting as the given operator identity."""
    return build_user_headers(user_id, "RegulatoryAffairs")


def make_lab_tech_headers(user_id: str) -> dict:
    """Headers for a LabTech acting as the given operator identity."""
    return build_user_headers(user_id, "LabTech")


def make_purchasing_manager_headers(user_id: str) -> dict:
    """Headers for a PurchasingManager acting as the given operator identity."""
    return build_user_headers(user_id, "PurchasingManager")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary operator identity and declared role."""
    return build_user_headers(user_id, role)


# Operator identities used by the segregation-of-duties scenarios: the
# formula submitter must differ from the approver, and the lot compounder
# must differ from the operator recording QC.
FLAVORIST_SUBMITTER_ID = "u_flav_1"
FLAVORIST_SECOND_ID = "u_flav_2"
DIRECTOR_APPROVER_ID = "u_dir_1"
DIRECTOR_SECOND_ID = "u_dir_2"
DUAL_HAT_ID = "u_dual_1"
LAB_COMPOUNDER_ID = "u_lab_1"
LAB_QC_ID = "u_lab_2"

# Headers built on those identities, ready to use.
FLAVORIST_SUBMITTER = build_user_headers(FLAVORIST_SUBMITTER_ID, "Flavorist")
FLAVORIST_SECOND = build_user_headers(FLAVORIST_SECOND_ID, "Flavorist")
DIRECTOR_APPROVER = build_user_headers(DIRECTOR_APPROVER_ID, "TechnicalDirector")
DIRECTOR_SECOND = build_user_headers(DIRECTOR_SECOND_ID, "TechnicalDirector")
LAB_COMPOUNDER = build_user_headers(LAB_COMPOUNDER_ID, "LabTech")
LAB_QC = build_user_headers(LAB_QC_ID, "LabTech")

ALL_ROLE_NAMES = [
    "AccountManager",
    "TechnicalDirector",
    "Flavorist",
    "RegulatoryAffairs",
    "LabTech",
    "PurchasingManager",
]

ALL_ROLE_HEADERS = [build_user_headers(f"u_any_{i}", role)
                    for i, role in enumerate(ALL_ROLE_NAMES, start=1)]

# Canonical headers for the four roles that carry no segregation-of-duties
# requirement, plus the two dual-identity roles' primary operators.
ACCOUNT_MANAGER = build_user_headers("u_am_1", "AccountManager")
TECHNICAL_DIRECTOR = DIRECTOR_APPROVER
FLAVORIST = FLAVORIST_SUBMITTER
REGULATORY_AFFAIRS = build_user_headers("u_reg_1", "RegulatoryAffairs")
LAB_TECH = LAB_COMPOUNDER
PURCHASING_MANAGER = build_user_headers("u_purch_1", "PurchasingManager")

# The one operator who holds two role hats, used to prove that the
# segregation-of-duties comparison is made on X-User-ID and not on the
# declared role.
DUAL_HAT_FLAVORIST = build_user_headers(DUAL_HAT_ID, "Flavorist")
DUAL_HAT_DIRECTOR = build_user_headers(DUAL_HAT_ID, "TechnicalDirector")

ROLE_HEADERS_BY_NAME = {
    "AccountManager": ACCOUNT_MANAGER,
    "TechnicalDirector": TECHNICAL_DIRECTOR,
    "Flavorist": FLAVORIST,
    "RegulatoryAffairs": REGULATORY_AFFAIRS,
    "LabTech": LAB_TECH,
    "PurchasingManager": PURCHASING_MANAGER,
}
