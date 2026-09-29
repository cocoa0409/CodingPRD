"""Shared actor identities and per-role header builders.

The PRD states that ``X-User-ID`` is an opaque operator identifier that is not
tied to any persisted entity, so these values are free-form strings. Distinct
identifiers per actor matter because several rules compare the acting operator
against a recorded one.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_EXPORT_COMPLIANCE_OFFICER,
    ROLE_METROLOGY_TECHNICIAN,
    ROLE_OPTICS_ENGINEER,
    ROLE_PLANT_ADMIN,
    ROLE_PROCESS_TECHNICIAN,
    ROLE_PROCUREMENT_OFFICER,
    ROLE_QUALITY_MANAGER,
)

# Metrology technicians: distinct ids so a report may be recorded by one and
# signed by another.
MT_RECORDER = "mt-001"
MT_SIGNER = "mt-002"
MT_THIRD = "mt-003"
MT_CALIBRATOR = "mt-004"

# Quality managers: distinct ids for the inspection/waiver and
# submission/review segregation pairs.
QM_PRIMARY = "qm-001"
QM_SECOND = "qm-002"
QM_THIRD = "qm-003"

# Export compliance officers: distinct ids for classify / decide / revoke.
ECO_CLASSIFIER = "eco-001"
ECO_DECIDER = "eco-002"
ECO_REVOKER = "eco-003"

OPTICS_ENGINEER_ID = "oe-001"
PROCUREMENT_OFFICER_ID = "po-001"
PROCESS_TECHNICIAN_ID = "pt-001"
PLANT_ADMIN_ID = "pa-001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "optics_engineer": {"user_id": OPTICS_ENGINEER_ID, "role": ROLE_OPTICS_ENGINEER},
    "procurement_officer": {
        "user_id": PROCUREMENT_OFFICER_ID,
        "role": ROLE_PROCUREMENT_OFFICER,
    },
    "process_technician": {
        "user_id": PROCESS_TECHNICIAN_ID,
        "role": ROLE_PROCESS_TECHNICIAN,
    },
    "metrology_recorder": {"user_id": MT_RECORDER, "role": ROLE_METROLOGY_TECHNICIAN},
    "metrology_signer": {"user_id": MT_SIGNER, "role": ROLE_METROLOGY_TECHNICIAN},
    "metrology_third": {"user_id": MT_THIRD, "role": ROLE_METROLOGY_TECHNICIAN},
    "metrology_calibrator": {
        "user_id": MT_CALIBRATOR,
        "role": ROLE_METROLOGY_TECHNICIAN,
    },
    "quality_manager": {"user_id": QM_PRIMARY, "role": ROLE_QUALITY_MANAGER},
    "quality_manager_second": {"user_id": QM_SECOND, "role": ROLE_QUALITY_MANAGER},
    "quality_manager_third": {"user_id": QM_THIRD, "role": ROLE_QUALITY_MANAGER},
    "export_classifier": {
        "user_id": ECO_CLASSIFIER,
        "role": ROLE_EXPORT_COMPLIANCE_OFFICER,
    },
    "export_decider": {"user_id": ECO_DECIDER, "role": ROLE_EXPORT_COMPLIANCE_OFFICER},
    "export_revoker": {"user_id": ECO_REVOKER, "role": ROLE_EXPORT_COMPLIANCE_OFFICER},
    "plant_admin": {"user_id": PLANT_ADMIN_ID, "role": ROLE_PLANT_ADMIN},
}


def make_optics_engineer_headers(user_id: str = OPTICS_ENGINEER_ID) -> Dict[str, str]:
    """Headers for an ``OpticsEngineer``."""
    return build_user_headers(user_id, ROLE_OPTICS_ENGINEER)


def make_procurement_officer_headers(
    user_id: str = PROCUREMENT_OFFICER_ID,
) -> Dict[str, str]:
    """Headers for a ``ProcurementOfficer``."""
    return build_user_headers(user_id, ROLE_PROCUREMENT_OFFICER)


def make_process_technician_headers(
    user_id: str = PROCESS_TECHNICIAN_ID,
) -> Dict[str, str]:
    """Headers for a ``ProcessTechnician``."""
    return build_user_headers(user_id, ROLE_PROCESS_TECHNICIAN)


def make_metrology_technician_headers(user_id: str = MT_RECORDER) -> Dict[str, str]:
    """Headers for a ``MetrologyTechnician``."""
    return build_user_headers(user_id, ROLE_METROLOGY_TECHNICIAN)


def make_quality_manager_headers(user_id: str = QM_PRIMARY) -> Dict[str, str]:
    """Headers for a ``QualityManager``."""
    return build_user_headers(user_id, ROLE_QUALITY_MANAGER)


def make_export_compliance_officer_headers(
    user_id: str = ECO_CLASSIFIER,
) -> Dict[str, str]:
    """Headers for an ``ExportComplianceOfficer``."""
    return build_user_headers(user_id, ROLE_EXPORT_COMPLIANCE_OFFICER)


def make_plant_admin_headers(user_id: str = PLANT_ADMIN_ID) -> Dict[str, str]:
    """Headers for a ``PlantAdmin``."""
    return build_user_headers(user_id, ROLE_PLANT_ADMIN)


def make_headers_for_role(role: str, user_id: str = "actor-001") -> Dict[str, str]:
    """Headers for an arbitrary role literal, including undefined ones."""
    return build_user_headers(user_id, role)
