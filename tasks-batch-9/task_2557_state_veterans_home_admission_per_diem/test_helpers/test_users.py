"""Header builders for every role, plus stable default user identifiers.

Two rules of the API drive the shape of this module. First, several writes
compare the acting `X-User-ID` against a user identifier stored on an earlier
record, so tests must be able to choose the acting user independently of the
role. Second, a resident representative's `X-User-ID` is not an opaque operator
identifier at all: it must equal the `Resident.id` whose record is being read.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ADMISSIONS_COORDINATOR,
    ROLE_BUSINESS_OFFICE_MANAGER,
    ROLE_CLINICAL_ASSESSOR,
    ROLE_FEDERAL_PER_DIEM_AUDITOR,
    ROLE_RESIDENT_REPRESENTATIVE,
    ROLE_STATE_PROGRAM_ADMIN,
    ROLE_SURVEY_AGENCY,
)

DEFAULT_ADMIN_USER = "admin-1"
DEFAULT_COORDINATOR_USER = "coordinator-1"
DEFAULT_ASSESSOR_USER = "assessor-1"
DEFAULT_BOM_USER = "bom-1"
SECOND_BOM_USER = "bom-2"
DEFAULT_AUDITOR_USER = "auditor-1"
DEFAULT_SURVEYOR_USER = "surveyor-1"
SECOND_COORDINATOR_USER = "coordinator-2"
SECOND_ASSESSOR_USER = "assessor-2"


def make_state_program_admin_headers(user_id: str = DEFAULT_ADMIN_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STATE_PROGRAM_ADMIN)


def make_admissions_coordinator_headers(
    user_id: str = DEFAULT_COORDINATOR_USER,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ADMISSIONS_COORDINATOR)


def make_clinical_assessor_headers(user_id: str = DEFAULT_ASSESSOR_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CLINICAL_ASSESSOR)


def make_business_office_manager_headers(user_id: str = DEFAULT_BOM_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BUSINESS_OFFICE_MANAGER)


def make_federal_per_diem_auditor_headers(
    user_id: str = DEFAULT_AUDITOR_USER,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FEDERAL_PER_DIEM_AUDITOR)


def make_survey_agency_headers(user_id: str = DEFAULT_SURVEYOR_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SURVEY_AGENCY)


def make_resident_representative_headers(resident_id: str) -> Dict[str, str]:
    """A representative acts under the identifier of the resident they speak for."""
    return build_user_headers(resident_id, ROLE_RESIDENT_REPRESENTATIVE)


HEADER_FACTORY_BY_ROLE = {
    ROLE_STATE_PROGRAM_ADMIN: make_state_program_admin_headers,
    ROLE_ADMISSIONS_COORDINATOR: make_admissions_coordinator_headers,
    ROLE_CLINICAL_ASSESSOR: make_clinical_assessor_headers,
    ROLE_BUSINESS_OFFICE_MANAGER: make_business_office_manager_headers,
    ROLE_FEDERAL_PER_DIEM_AUDITOR: make_federal_per_diem_auditor_headers,
    ROLE_SURVEY_AGENCY: make_survey_agency_headers,
    ROLE_RESIDENT_REPRESENTATIVE: make_resident_representative_headers,
}


def headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Build headers for an arbitrary role name, defaulting the acting user."""
    if role == ROLE_RESIDENT_REPRESENTATIVE:
        if user_id is None:
            raise ValueError("a resident representative must act as a specific resident id")
        return make_resident_representative_headers(user_id)
    factory = HEADER_FACTORY_BY_ROLE.get(role)
    if factory is None:
        return build_user_headers(user_id or "unknown-1", role)
    if user_id is None:
        return factory()
    return factory(user_id)


def make_headers_missing_user_id(role: str) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_missing_role(user_id: str = DEFAULT_ADMIN_USER) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_unknown_role(user_id: str = DEFAULT_ADMIN_USER) -> Dict[str, str]:
    return build_user_headers(user_id, "DietaryManager")


def make_no_auth_headers() -> Dict[str, str]:
    return {"Content-Type": "application/json"}
