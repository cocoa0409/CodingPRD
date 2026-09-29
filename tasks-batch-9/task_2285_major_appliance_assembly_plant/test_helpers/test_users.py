"""Pre-built request headers for every role.

The six plant-internal roles carry an opaque `X-User-ID`: no ownership check of
any kind is derived from it, so a single fixed identifier per role is enough.
Where a test needs two *distinct* human identities inside the same role — the
engineering-change segregation-of-duties rule is the only such place — use
:func:`make_engineering_lead_headers`.

`SupplierPortal` is different: its `X-User-ID` **is** the supplier's id, so it
has no pre-built constant and must always be built with
:func:`make_supplier_portal_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- Opaque identities for the six plant-internal roles ----------------------
PLANT_ADMIN_USER_ID = "user-plant-admin"
PRODUCTION_PLANNER_USER_ID = "user-production-planner"
LINE_OPERATOR_USER_ID = "user-line-operator"
QUALITY_INSPECTOR_USER_ID = "user-quality-inspector"
ENGINEERING_LEAD_USER_ID = "user-engineering-lead"
WARRANTY_ANALYST_USER_ID = "user-warranty-analyst"

PLANT_ADMIN_HEADERS = build_user_headers(PLANT_ADMIN_USER_ID, Role.PLANT_ADMIN.value)
PRODUCTION_PLANNER_HEADERS = build_user_headers(
    PRODUCTION_PLANNER_USER_ID, Role.PRODUCTION_PLANNER.value
)
LINE_OPERATOR_HEADERS = build_user_headers(
    LINE_OPERATOR_USER_ID, Role.LINE_OPERATOR.value
)
QUALITY_INSPECTOR_HEADERS = build_user_headers(
    QUALITY_INSPECTOR_USER_ID, Role.QUALITY_INSPECTOR.value
)
ENGINEERING_LEAD_HEADERS = build_user_headers(
    ENGINEERING_LEAD_USER_ID, Role.ENGINEERING_LEAD.value
)
WARRANTY_ANALYST_HEADERS = build_user_headers(
    WARRANTY_ANALYST_USER_ID, Role.WARRANTY_ANALYST.value
)

TEST_USERS = {
    Role.PLANT_ADMIN.value: PLANT_ADMIN_HEADERS,
    Role.PRODUCTION_PLANNER.value: PRODUCTION_PLANNER_HEADERS,
    Role.LINE_OPERATOR.value: LINE_OPERATOR_HEADERS,
    Role.QUALITY_INSPECTOR.value: QUALITY_INSPECTOR_HEADERS,
    Role.ENGINEERING_LEAD.value: ENGINEERING_LEAD_HEADERS,
    Role.WARRANTY_ANALYST.value: WARRANTY_ANALYST_HEADERS,
}


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/user-id pair."""
    return build_user_headers(user_id, role)


def make_supplier_portal_headers(supplier_id: str) -> dict:
    """Headers for a supplier portal caller.

    `supplier_id` must be the id of the Supplier the caller represents; the API
    reads the calling supplier's identity straight out of `X-User-ID`.
    """
    return build_user_headers(supplier_id, Role.SUPPLIER_PORTAL.value)


def make_engineering_lead_headers(user_id: str) -> dict:
    """Headers for a named engineering lead (distinct submitter/decider)."""
    return build_user_headers(user_id, Role.ENGINEERING_LEAD.value)


def make_plant_admin_headers(user_id: str) -> dict:
    """Headers for a named plant administrator."""
    return build_user_headers(user_id, Role.PLANT_ADMIN.value)


#: A well-formed header set whose `X-User-Role` is not one of the seven roles.
UNKNOWN_ROLE_HEADERS = build_user_headers("user-intruder", "Janitor")

#: Headers with no `X-User-ID` at all.
NO_USER_ID_HEADERS = {"X-User-Role": Role.PLANT_ADMIN.value,
                      "Content-Type": "application/json"}

#: Headers whose `X-User-ID` is present but empty.
EMPTY_USER_ID_HEADERS = build_user_headers("", Role.PLANT_ADMIN.value)
