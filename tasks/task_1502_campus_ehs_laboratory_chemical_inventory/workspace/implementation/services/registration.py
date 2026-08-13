"""Registration lifecycle service (PRD §3.7)."""
import db
from errors import ApiError, ERR_REGISTRATION_STATE
from services.common import touch


def apply_suspend(reg):
    """Shared effect for direct suspend and the FROZEN cascade:
    ACTIVE -> SUSPENDED, version bump, access_blocked recomputed on read."""
    reg["status"] = "SUSPENDED"
    touch(reg)


def activate(reg):
    if reg["status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError(ERR_REGISTRATION_STATE,
                       "Registration must be PENDING or SUSPENDED to activate", 409)
    reg["status"] = "ACTIVE"
    touch(reg)


def suspend(reg):
    if reg["status"] != "ACTIVE":
        raise ApiError(ERR_REGISTRATION_STATE,
                       "Registration must be ACTIVE to suspend", 409)
    apply_suspend(reg)


def surrender(reg):
    if reg["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_REGISTRATION_STATE,
                       "Registration must be ACTIVE or SUSPENDED to surrender", 409)
    reg["status"] = "SURRENDERED"
    touch(reg)
