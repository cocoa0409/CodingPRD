"""Acting identities for the four roles of PRD section 2.1.

Three of the four roles carry an opaque operator identifier: "When
`X-User-Role` is `ProgramAdmin`, `QAVerifier`, or `UtilityInspector`,
`X-User-ID` is an opaque operator identifier not tied to any persisted entity."
Those three therefore get fixed, module-level header dictionaries.

`FieldTechnician` is different: "When `X-User-Role` is `FieldTechnician`,
`X-User-ID` is the `id` of the acting `Technician`". A technician's headers can
only be built once the technician row exists, so that role gets a builder
function taking the freshly minted technician id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FIELD_TECHNICIAN,
    ROLE_PROGRAM_ADMIN,
    ROLE_QA_VERIFIER,
    ROLE_UTILITY_INSPECTOR,
)

# --- Opaque operator identifiers ------------------------------------------
ADMIN_USER_ID = "admin-1"
QA_VERIFIER_USER_ID = "qa-1"
SECOND_QA_VERIFIER_USER_ID = "qa-2"
INSPECTOR_USER_ID = "insp-1"
SECOND_INSPECTOR_USER_ID = "insp-2"

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
QA_HEADERS = build_user_headers(QA_VERIFIER_USER_ID, ROLE_QA_VERIFIER)
SECOND_QA_HEADERS = build_user_headers(SECOND_QA_VERIFIER_USER_ID, ROLE_QA_VERIFIER)
INSPECTOR_HEADERS = build_user_headers(INSPECTOR_USER_ID, ROLE_UTILITY_INSPECTOR)
SECOND_INSPECTOR_HEADERS = build_user_headers(
    SECOND_INSPECTOR_USER_ID, ROLE_UTILITY_INSPECTOR
)


def make_field_technician_headers(technician_id: str) -> Dict[str, str]:
    """Headers for a `FieldTechnician` acting as the `Technician` row given."""
    return build_user_headers(technician_id, ROLE_FIELD_TECHNICIAN)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identifier/role pair.

    Used where a test must present a *known* identifier under a *different*
    role, because "presenting the same `X-User-ID` under a different
    `X-User-Role` does **not** escape" the segregation rule of PRD 2.9.
    """
    return build_user_headers(user_id, role)


def headers_for_role(role: str, technician_id: str = "") -> Dict[str, str]:
    """The canonical headers for `role`, used by the role-matrix tests."""
    if role == ROLE_FIELD_TECHNICIAN:
        assert technician_id, "FieldTechnician headers need a technician id"
        return make_field_technician_headers(technician_id)
    if role == ROLE_PROGRAM_ADMIN:
        return dict(ADMIN_HEADERS)
    if role == ROLE_QA_VERIFIER:
        return dict(QA_HEADERS)
    if role == ROLE_UTILITY_INSPECTOR:
        return dict(INSPECTOR_HEADERS)
    raise AssertionError(f"unknown role {role!r}")


#: Headers with an empty `X-User-ID`. "When `X-User-ID` is absent or empty the
#: request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)".
EMPTY_USER_ID_ADMIN_HEADERS = build_user_headers("", ROLE_PROGRAM_ADMIN)
EMPTY_USER_ID_QA_HEADERS = build_user_headers("", ROLE_QA_VERIFIER)
