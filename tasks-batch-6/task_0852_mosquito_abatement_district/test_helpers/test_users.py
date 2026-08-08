"""Pre-built role headers for every role named in the PRD.

Five roles carry opaque identity (`DistrictAdmin`, `LabAnalyst`,
`VectorEcologist`, `AbatementManager`, `Resident`) so a shared constant is the
canonical form for them.  Two roles are entity-backed: a `FieldTech` presents
the `id` of the acting `Applicator` and a `SensitiveSiteOperator` presents the
`id` of the acting `SensitiveSite`, so ownership-gated calls MUST use the
per-instance builders below with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque identities — safe to share across tests.
    "admin_headers": build_user_headers("u-admin-1", "DistrictAdmin"),
    "lab_headers": build_user_headers("u-lab-1", "LabAnalyst"),
    "ecologist_headers": build_user_headers("u-eco-1", "VectorEcologist"),
    "manager_headers": build_user_headers("u-mgr-1", "AbatementManager"),
    "manager2_headers": build_user_headers("u-mgr-2", "AbatementManager"),
    "resident_headers": build_user_headers("u-res-1", "Resident"),
    # Entity-backed identities — these shared constants are only valid for
    # calls that never touch an ownership check (404 / 403-role probes).
    "field_tech_headers": build_user_headers("u-tech-unbacked", "FieldTech"),
    "site_operator_headers": build_user_headers("u-site-unbacked", "SensitiveSiteOperator"),
}

ADMIN = TEST_USERS["admin_headers"]
LAB = TEST_USERS["lab_headers"]
ECOLOGIST = TEST_USERS["ecologist_headers"]
MANAGER = TEST_USERS["manager_headers"]
MANAGER2 = TEST_USERS["manager2_headers"]
RESIDENT = TEST_USERS["resident_headers"]

ADMIN_USER_ID = "u-admin-1"
ECOLOGIST_USER_ID = "u-eco-1"
MANAGER_USER_ID = "u-mgr-1"
MANAGER2_USER_ID = "u-mgr-2"
RESIDENT_USER_ID = "u-res-1"


def make_field_tech_headers(applicator_id: str) -> dict:
    """For FieldTech: `X-User-ID` is the acting Applicator's id."""
    return build_user_headers(applicator_id, "FieldTech")


def make_site_operator_headers(sensitive_site_id: str) -> dict:
    """For SensitiveSiteOperator: `X-User-ID` is the acting SensitiveSite's id."""
    return build_user_headers(sensitive_site_id, "SensitiveSiteOperator")


def make_manager_headers(user_id: str) -> dict:
    """An AbatementManager acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "AbatementManager")


def make_ecologist_headers(user_id: str) -> dict:
    """A VectorEcologist acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "VectorEcologist")


def make_resident_headers(user_id: str) -> dict:
    """A Resident acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "Resident")


def make_admin_headers(user_id: str) -> dict:
    """A DistrictAdmin acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "DistrictAdmin")


def make_lab_headers(user_id: str) -> dict:
    """A LabAnalyst acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "LabAnalyst")


NO_AUTH_HEADERS: dict = {}
