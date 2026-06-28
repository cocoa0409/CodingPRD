"""Driver, privacy-consent, discount-bank, and discount-grant endpoints
(PRD §3.2, §3.10)."""
from flask import Blueprint, request

import clock
import db
from common import (
    find_or_404,
    get_body,
    new_record,
    optional_str,
    pagination,
    paginate,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_owner, require_role
from response import array_response, object_response

bp = Blueprint("drivers", __name__)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
@bp.post("/drivers")
def create_driver():
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    state_code = require_str(body, "state_code")

    # Unique driver email, case-insensitive (PRD §3.2).
    lowered = email.lower()
    for d in db.drivers.values():
        if d["email"].lower() == lowered:
            raise ApiError("ERR_DUPLICATE_EMAIL")

    rec = new_record(
        {
            "email": email,
            "full_name": full_name,
            "state_code": state_code,
            "telematics_opted_out": False,
            "lifetime_safe_miles": 0,
            "status": "ACTIVE",
        }
    )
    db.drivers[rec["id"]] = rec

    # Provision a DiscountBank for the driver (PRD §3.2, §3.10).
    bank = new_record(
        {
            "driver_id": rec["id"],
            "earned_cents": 0,
            "redeemed_cents": 0,
            "available_cents": 0,
        }
    )
    db.discount_banks[bank["id"]] = bank

    return object_response(serialize(rec), 201)


@bp.get("/drivers")
def list_drivers():
    _, role = auth_context()
    require_role(role, ["UnderwritingOps", "ClaimsAdjuster"])
    limit, offset = pagination()
    email = request.args.get("email")
    items = list(db.drivers.values())
    if email is not None:
        items = [d for d in items if d["email"].lower() == email.lower()]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/drivers/<rid>")
def get_driver(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps", "ClaimsAdjuster"])
    rec = find_or_404(db.drivers, rid)
    return object_response(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Privacy consent (opt-out / opt-in) + cascade (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.post("/drivers/<rid>/privacy-consents")
def create_consent(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    driver = find_or_404(db.drivers, rid)
    require_owner(role, user_id, driver["id"])

    body = get_body()
    action = require_str(body, "action")
    if action not in ("GRANT", "REVOKE"):
        raise ApiError("ERR_VALIDATION", "action must be GRANT or REVOKE.")
    reason = optional_str(body, "reason")

    opted_out = driver["telematics_opted_out"]
    if action == "REVOKE":
        if opted_out:
            raise ApiError("ERR_ALREADY_OPTED_OUT")
        driver["telematics_opted_out"] = True
        _cascade_telematics(driver["id"], "SUSPENDED")
    else:  # GRANT
        if not opted_out:
            raise ApiError("ERR_NOT_OPTED_OUT")
        driver["telematics_opted_out"] = False
        _cascade_telematics(driver["id"], "CAPTURING")
    touch(driver)

    rec = new_record(
        {
            "driver_id": driver["id"],
            "action": action,
            "reason": reason,
            "effective_at": clock.iso_now(),
        },
        common=False,
    )
    db.privacy_consents[rec["id"]] = rec
    return object_response(serialize(rec), 201)


def _cascade_telematics(driver_id, new_status):
    """Cascade the telematics dimension across every ACTIVE policy (PRD §3.2)."""
    for pol in db.policies.values():
        if pol["driver_id"] == driver_id and pol["lifecycle_status"] == "ACTIVE":
            if pol["telematics_status"] != new_status:
                pol["telematics_status"] = new_status
                touch(pol)


@bp.get("/drivers/<rid>/privacy-consents")
def list_consents(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    driver = find_or_404(db.drivers, rid)
    if role == "DriverUser":
        user_id = request.headers.get("X-User-ID")
        require_owner(role, user_id, driver["id"])
    limit, offset = pagination()
    items = [c for c in db.privacy_consents.values() if c["driver_id"] == driver["id"]]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Discount bank + grants (PRD §3.10)
# ---------------------------------------------------------------------------
@bp.get("/discount-banks")
def list_banks():
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    limit, offset = pagination()
    driver_id = request.args.get("driver_id")
    items = list(db.discount_banks.values())
    if driver_id is not None:
        items = [b for b in items if b["driver_id"] == driver_id]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/discount-banks/<rid>")
def get_bank(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    rec = find_or_404(db.discount_banks, rid)
    return object_response(serialize(rec), 200)


@bp.get("/discount-banks/<rid>/grants")
def list_grants(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    bank = find_or_404(db.discount_banks, rid)
    limit, offset = pagination()
    items = [g for g in db.discount_grants.values() if g["discount_bank_id"] == bank["id"]]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)
