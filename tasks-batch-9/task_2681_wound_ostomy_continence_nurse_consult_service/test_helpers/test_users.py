"""Pre-built role headers for every role named in PRD §2.1.

Two roles carry an identity that must be a real row's `id`:

* `WocNurse` — "When `X-User-Role` is `WocNurse`, `X-User-ID` is the `id` of the
  acting WOC nurse record".
* `UnitCharge` — "When `X-User-Role` is `UnitCharge`, `X-User-ID` is the `id` of
  the acting unit".

For those two, always build headers with the per-instance builders below and
pass the real entity id. The three remaining roles hold opaque operator
identifiers that the server never compares to any entity's `id`, so the shared
constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities — canonical form.
    "director_headers": build_user_headers("op-director-1", "WocProgramDirector"),
    "materials_headers": build_user_headers("op-materials-1", "MaterialsCoordinator"),
    "system_operator_headers": build_user_headers("op-sysop-1", "SystemOperator"),
    # Entity-backed identities — placeholder only, for calls whose outcome does
    # not depend on the caller owning the subject row (401/403/400/404 probes).
    "nurse_headers": build_user_headers("placeholder-nurse", "WocNurse"),
    "unit_charge_headers": build_user_headers("placeholder-unit", "UnitCharge"),
}


def make_nurse_headers(nurse_id: str) -> dict:
    """Headers for a `WocNurse` acting as the nurse row whose id is `nurse_id`."""
    return build_user_headers(nurse_id, "WocNurse")


def make_unit_charge_headers(unit_id: str) -> dict:
    """Headers for a `UnitCharge` acting as the unit whose id is `unit_id`."""
    return build_user_headers(unit_id, "UnitCharge")


def make_director_headers(user_id: str = "op-director-1") -> dict:
    """Headers for a `WocProgramDirector`; the identifier is opaque."""
    return build_user_headers(user_id, "WocProgramDirector")


def make_materials_headers(user_id: str = "op-materials-1") -> dict:
    """Headers for a `MaterialsCoordinator`; the identifier is opaque."""
    return build_user_headers(user_id, "MaterialsCoordinator")


def make_system_operator_headers(user_id: str = "op-sysop-1") -> dict:
    """Headers for a `SystemOperator`; the identifier is opaque."""
    return build_user_headers(user_id, "SystemOperator")


def make_unknown_role_headers(user_id: str = "op-unknown-1") -> dict:
    """Headers naming a role that is not one of the five declared role names."""
    return build_user_headers(user_id, "OrthopedicTech")


NO_HEADERS: dict = {"Content-Type": "application/json"}
"""A request carrying neither `X-User-ID` nor `X-User-Role`."""
