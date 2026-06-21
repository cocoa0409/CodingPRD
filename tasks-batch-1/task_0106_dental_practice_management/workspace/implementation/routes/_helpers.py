"""Per-route helpers shared across blueprints: auth+RBAC wrapper, Patient/Clinician
ownership enforcement, list-filter utilities."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import db
from errors import APIError, ERR_FORBIDDEN
from middleware import (
    ROLE_CLINICIAN,
    ROLE_PATIENT,
    authenticate,
    current_role,
    current_user_id,
    require_roles,
)


def guard(allowed_roles):
    """Run auth (401) then RBAC (403) for this endpoint, in PRD §2.8 order."""
    authenticate()
    require_roles(allowed_roles)


def enforce_patient_ownership(patient_fk: Optional[str]) -> None:
    """When the caller is a Patient, the named resource's patient FK must equal
    X-User-ID, else ERR_FORBIDDEN (PRD §2.1)."""
    if current_role() == ROLE_PATIENT:
        if patient_fk != current_user_id():
            raise APIError(ERR_FORBIDDEN, 403, "Patient may only access own records")


def patient_id_of_treatment_plan(plan: Dict[str, Any]) -> str:
    return plan["patient_id"]


def patient_id_of_item(item: Dict[str, Any]) -> str:
    plan = db.treatment_plans[item["treatment_plan_id"]]
    return plan["patient_id"]


def apply_filters(records: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Keep records where each provided filter field equals the record's value.
    A None filter value means the query param was not supplied (ignored)."""
    out = records
    for field, value in filters.items():
        if value is None:
            continue
        out = [r for r in out if r.get(field) == value]
    return out
