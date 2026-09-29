"""Licensing manufacturer service information -- PRD 3.2."""

from flask import Blueprint

from auth import authenticate
from envelope import object_response
from errors import err
from serialize import project
from services import (
    append_audit,
    cascade_revoke_seats,
    find,
    seats_of_entitlement,
    settle_entitlement,
    sorted_rows,
)
from store import store
from validate import body_object, check_allowed, get_dt, get_enum, get_int, get_ref, get_ref_list, get_str

from routes.common import LICENSE_MODELS

bp = Blueprint("licenses", __name__)


@bp.post("/licenses")
def draft_license():
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(
        body,
        (
            "manufacturer_id",
            "license_model",
            "monthly_fee_cents",
            "per_vehicle_fee_cents",
            "seat_cap",
            "covered_system_area_ids",
            "effective_start",
            "effective_end",
        ),
    )
    manufacturer_id = get_ref(body, "manufacturer_id")
    license_model = get_enum(body, "license_model", LICENSE_MODELS)
    monthly_fee_cents = get_int(body, "monthly_fee_cents", minimum=1)
    per_vehicle_fee_cents = get_int(body, "per_vehicle_fee_cents", minimum=1)
    seat_cap = get_int(body, "seat_cap", minimum=1, maximum=500)
    area_ids = get_ref_list(body, "covered_system_area_ids", 1, 12)
    start_raw, start = get_dt(body, "effective_start")
    end_raw, end = get_dt(body, "effective_end")
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "effective_end must be strictly after effective_start.")

    find(store.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")
    for area_id in area_ids:
        if area_id not in store.system_areas:
            raise err(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "covered_system_area_ids contains an unknown system area.",
            )

    row = store.base_row()
    row["manufacturer_id"] = manufacturer_id
    row["license_model"] = license_model
    row["monthly_fee_cents"] = monthly_fee_cents
    row["per_vehicle_fee_cents"] = per_vehicle_fee_cents
    row["seat_cap"] = seat_cap
    row["covered_system_area_ids"] = list(area_ids)
    row["effective_start"] = start_raw
    row["effective_end"] = end_raw
    row["_effective_start"] = start
    row["_effective_end"] = end
    row["status"] = "DRAFT"
    row["suspension_reason"] = None
    store.licenses[row["id"]] = row
    return object_response(project("license", row), 201)


@bp.post("/licenses/<license_id>/activate")
def activate_license(license_id):
    user_id, role = authenticate(("PlatformAdmin",))
    check_allowed(body_object(), ())
    license_row = find(store.licenses, license_id, "ERR_LICENSE_NOT_FOUND")

    # PRD 3.2: every activation re-resolves every covered system area id.
    for area_id in license_row["covered_system_area_ids"]:
        if area_id not in store.system_areas:
            raise err(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "covered_system_area_ids contains an unknown system area.",
            )
    if license_row["status"] not in ("DRAFT", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Only a DRAFT or SUSPENDED license may be activated.")
    manufacturer = store.manufacturers.get(license_row["manufacturer_id"])
    if manufacturer is None or manufacturer["parity_status"] != "COMPLIANT":
        raise err("ERR_PARITY_NON_COMPLIANT", "The granting OEM does not pass pricing parity.")

    license_row["status"] = "ACTIVE"
    store.touch(license_row)
    return object_response(project("license", license_row))


@bp.post("/licenses/<license_id>/suspend")
def suspend_license(license_id):
    user_id, role = authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("reason",))
    reason = get_str(body, "reason", min_len=1)
    license_row = find(store.licenses, license_id, "ERR_LICENSE_NOT_FOUND")

    if license_row["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE license may be suspended.")

    license_row["status"] = "SUSPENDED"
    license_row["suspension_reason"] = reason
    store.touch(license_row)
    return object_response(project("license", license_row))


@bp.post("/licenses/<license_id>/terminate")
def terminate_license(license_id):
    user_id, role = authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("reason",))
    reason = get_str(body, "reason", min_len=1)
    license_row = find(store.licenses, license_id, "ERR_LICENSE_NOT_FOUND")

    if license_row["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Only an ACTIVE or SUSPENDED license may be terminated.")

    license_row["status"] = "TERMINATED"
    license_row["suspension_reason"] = reason
    store.touch(license_row)
    append_audit(
        role, user_id, "License", license_row["id"], "LICENSE_TERMINATED", "reason=%s" % reason
    )

    # HOP 1: every ACTIVE entitlement on this license -> LAPSED, settled.
    entitlements = sorted_rows(
        [
            row
            for row in store.entitlements.values()
            if row["license_id"] == license_row["id"] and row["status"] == "ACTIVE"
        ]
    )
    for entitlement in entitlements:
        settle_entitlement(entitlement, "LAPSED", "SYSTEM", None)

    # HOP 2 and HOP 3: their ACTIVE seats, then those seats' ACTIVE sessions.
    seats = []
    for entitlement in entitlements:
        seats.extend(seats_of_entitlement(entitlement))
    cascade_revoke_seats(seats, "LICENSE_TERMINATED", "SEAT_REVOKED", "SYSTEM", None)

    return object_response(project("license", license_row))
