"""Shared lookup, existence, and ownership helpers."""
import db
import errors
from errors import ApiError


def get_or_404(table, resource_id):
    """Return the stored record or raise ERR_NOT_FOUND (404)."""
    rec = table.get(resource_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced resource does not exist.")
    return rec


def require_field(body, name):
    """Return body[name] or raise ERR_INVALID_REQUEST when missing."""
    if name not in body or body[name] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Missing required field: {name}.")
    return body[name]


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val.strip() == "":
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be a non-empty string.")
    return val


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer.")
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if val not in allowed:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be one of {sorted(allowed)}.")
    return val


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean.")
    return val


# ---- ownership (PRD §2.1) ---------------------------------------------------

def check_customer_owns_vehicle(role, user_id, vehicle_profile):
    """Customer ownership: X-User-ID must equal vehicle's customer_user_id."""
    if role == "Customer" and vehicle_profile.get("customer_user_id") != user_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "Customer does not own this vehicle resource.")


def check_fleet_manager_owns(role, user_id, fleet_account):
    if role == "FleetManager" and fleet_account.get("fleet_manager_user_id") != user_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "FleetManager does not own this fleet account.")


def check_installer_self(role, user_id, installer):
    if role == "Installer" and installer.get("installer_user_id") != user_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "Installer is not the assigned installer.")


def vehicle_for_quote(quote):
    return db.vehicle_profiles.get(quote["vehicle_profile_id"])
