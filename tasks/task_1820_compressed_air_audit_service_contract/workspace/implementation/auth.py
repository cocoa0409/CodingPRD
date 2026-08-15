"""Auth context, role gating, and FacilityManager ownership checks."""

from flask import request

from errors import (
    ApiError,
    ERR_AUTH_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_FACILITY_OWNERSHIP_MISMATCH,
)
import store

ROLES = {"DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"}


def get_context():
    """Tier 1: X-User-ID / X-User-Role present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_AUTH_HEADER,
            400,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_roles(allowed):
    """Tier 1 then tier 2: role must be in the endpoint's authorized set."""
    user_id, role = get_context()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403, f"Role {role} is not permitted on this endpoint")
    return user_id, role


def owning_facility_id(kind, obj):
    """Resolve the owning Facility id of a resource (directly or via parents)."""
    if obj is None:
        return None
    if kind == "facility":
        return obj["id"]
    if kind == "rental_asset":
        return None  # dealer fleet: no owning facility
    if kind == "leak_tag":
        survey = store.leak_surveys.get(obj["survey_id"])
        return survey["facility_id"] if survey else None
    if kind == "service_credit":
        contract = store.service_contracts.get(obj["contract_id"])
        return contract["facility_id"] if contract else None
    return obj.get("facility_id")


def check_ownership(user_id, role, facility_id):
    """Tier 5: FacilityManager X-User-ID must equal the owning Facility id."""
    if role != "FacilityManager":
        return
    if facility_id is None:
        return  # unowned resource (rental fleet)
    if user_id != facility_id:
        raise ApiError(
            ERR_FACILITY_OWNERSHIP_MISMATCH,
            403,
            "FacilityManager X-User-ID does not equal the owning Facility id",
        )
