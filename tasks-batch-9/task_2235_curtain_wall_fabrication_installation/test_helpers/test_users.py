"""Pre-built role headers for every participant role in the PRD.

All eight roles carry an opaque identity: the accompanying `X-User-ID` is an
opaque operator identifier that is not tied to any persisted entity and is
never compared against any resource's `id`. The shared constants below are
therefore the canonical form for every role. The per-role builders exist for
the segregation-of-duties rules, which compare the incoming `X-User-ID`
against previously recorded operator identifiers on the row.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import USER_IDS

# Shared constants — one per role, safe for every non-segregation call.
TEST_USERS = {
    "cw_project_manager_headers": build_user_headers(
        USER_IDS["PROJECT_MANAGER"], "CWProjectManager"
    ),
    "cw_detailer_headers": build_user_headers(USER_IDS["DETAILER"], "CWDetailer"),
    "delegated_engineer_headers": build_user_headers(
        USER_IDS["ENGINEER"], "DelegatedEngineer"
    ),
    "architect_of_record_headers": build_user_headers(
        USER_IDS["ARCHITECT"], "ArchitectOfRecord"
    ),
    "glazing_procurement_headers": build_user_headers(
        USER_IDS["PROCUREMENT"], "GlazingProcurement"
    ),
    "structural_contractor_headers": build_user_headers(
        USER_IDS["STRUCTURAL"], "StructuralContractor"
    ),
    "field_superintendent_headers": build_user_headers(
        USER_IDS["SUPERINTENDENT"], "FieldSuperintendent"
    ),
    "qc_inspector_headers": build_user_headers(USER_IDS["QC_1"], "QCInspector"),
}

ROLE_HEADER_KEYS = {
    "CWProjectManager": "cw_project_manager_headers",
    "CWDetailer": "cw_detailer_headers",
    "DelegatedEngineer": "delegated_engineer_headers",
    "ArchitectOfRecord": "architect_of_record_headers",
    "GlazingProcurement": "glazing_procurement_headers",
    "StructuralContractor": "structural_contractor_headers",
    "FieldSuperintendent": "field_superintendent_headers",
    "QCInspector": "qc_inspector_headers",
}


def headers_for_role(role: str) -> dict:
    """Shared headers for the named role."""
    return TEST_USERS[ROLE_HEADER_KEYS[role]]


# --- Per-operator builders ------------------------------------------------
def make_cw_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CWProjectManager")


def make_cw_detailer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CWDetailer")


def make_delegated_engineer_headers(user_id: str) -> dict:
    """The sealing engineer's identity is recorded as sealed_by_user_id."""
    return build_user_headers(user_id, "DelegatedEngineer")


def make_architect_of_record_headers(user_id: str) -> dict:
    """The reviewer's identity is recorded as reviewed_by_user_id."""
    return build_user_headers(user_id, "ArchitectOfRecord")


def make_glazing_procurement_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GlazingProcurement")


def make_structural_contractor_headers(user_id: str) -> dict:
    """The surveyor's identity is recorded as surveyed_by_user_id."""
    return build_user_headers(user_id, "StructuralContractor")


def make_field_superintendent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldSuperintendent")


def make_qc_inspector_headers(user_id: str) -> dict:
    """The inspector's identity is recorded as raised_by_user_id,
    reinspected_by_user_id and recorded_by_user_id."""
    return build_user_headers(user_id, "QCInspector")


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/operator pair."""
    return build_user_headers(user_id, role)


# --- Deliberately malformed header sets ----------------------------------
def headers_without_role(user_id: str = "u-anon-1") -> dict:
    """No X-User-Role at all."""
    return {"X-User-ID": user_id}


def headers_with_empty_role(user_id: str = "u-anon-1") -> dict:
    """X-User-Role present but empty."""
    return {"X-User-Role": "", "X-User-ID": user_id}


def headers_without_user(role: str) -> dict:
    """A role header with no X-User-ID at all."""
    return {"X-User-Role": role}


def headers_with_empty_user(role: str) -> dict:
    """A role header with an empty X-User-ID."""
    return {"X-User-Role": role, "X-User-ID": ""}
