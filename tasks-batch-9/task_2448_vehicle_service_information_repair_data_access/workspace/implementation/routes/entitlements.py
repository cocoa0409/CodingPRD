"""Entitlement purchase, activation, settlement and seat assignment."""

from datetime import timedelta

from flask import Blueprint

from auth import authenticate, require_shop_scope
from calc import provisional_charge, recompute_seat_ledger, stamp_shop_coverage
from envelope import object_response
from errors import err
from serialize import project
from services import (
    append_audit,
    cascade_revoke_seats,
    find,
    seats_of_entitlement,
    settle_entitlement,
)
from store import store
from validate import body_object, check_allowed, get_dt, get_enum, get_int, get_ref, get_str, pagination, q_enum, q_str

from routes.common import (
    ENTITLEMENT_MODELS,
    ENTITLEMENT_STATUSES,
    SEAT_STATUSES,
    paged,
)

bp = Blueprint("entitlements", __name__)

ENTITLEMENT_READERS = ("PlatformAdmin", "ComplianceOfficer", "ShopManager")
SEAT_READERS = ("PlatformAdmin", "ComplianceOfficer", "ShopManager", "Technician")
COOLDOWN = timedelta(hours=24)
PERMITTED_MODELS = {
    "SUBSCRIPTION": ("SUBSCRIPTION",),
    "PER_VEHICLE": ("PER_VEHICLE",),
    "EITHER": ("SUBSCRIPTION", "PER_VEHICLE"),
}


@bp.post("/entitlements")
def buy_entitlement():
    user_id, role = authenticate(("ShopManager",))
    body = body_object()
    shop_id = body.get("shop_id")
    if not isinstance(shop_id, str) or not shop_id:
        raise err("ERR_INVALID_REQUEST", "Field shop_id must be a non-empty string identifier.")
    require_shop_scope(role, user_id, shop_id)
    check_allowed(
        body,
        (
            "shop_id",
            "license_id",
            "entitlement_model",
            "seats_total",
            "vin_quota",
            "window_start",
            "window_end",
        ),
    )
    license_id = get_ref(body, "license_id")
    entitlement_model = get_enum(body, "entitlement_model", ENTITLEMENT_MODELS)
    seats_total = get_int(body, "seats_total", minimum=1, maximum=500)
    vin_quota = get_int(body, "vin_quota", minimum=0, required=False, default=0)
    start_raw, start = get_dt(body, "window_start")
    end_raw, end = get_dt(body, "window_end")
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")

    shop = find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")
    license_row = find(store.licenses, license_id, "ERR_LICENSE_NOT_FOUND")

    # PRD 3.3: the window must sit inside the license's effective bounds.
    if start < license_row["_effective_start"] or end > license_row["_effective_end"]:
        raise err(
            "ERR_INVALID_REQUEST",
            "The coverage window must sit inside the license's effective bounds.",
        )
    if license_row["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "The license is not ACTIVE.")

    if seats_total > license_row["seat_cap"]:
        raise err("ERR_SEAT_CAP_EXCEEDED", "seats_total exceeds the license seat_cap.")
    if entitlement_model not in PERMITTED_MODELS[license_row["license_model"]]:
        raise err(
            "ERR_SEAT_CAP_EXCEEDED", "entitlement_model is not permitted by the license_model."
        )
    if entitlement_model == "PER_VEHICLE" and vin_quota < 1:
        raise err("ERR_SEAT_CAP_EXCEEDED", "vin_quota must be at least 1 for a PER_VEHICLE term.")
    if entitlement_model == "SUBSCRIPTION" and vin_quota != 0:
        raise err("ERR_SEAT_CAP_EXCEEDED", "vin_quota must be 0 for a SUBSCRIPTION term.")

    for sibling in store.entitlements.values():
        if sibling["shop_id"] != shop_id or sibling["license_id"] != license_id:
            continue
        if sibling["status"] not in ("PENDING", "ACTIVE"):
            continue
        if start <= sibling["_window_end"] + COOLDOWN and sibling["_window_start"] <= end + COOLDOWN:
            raise err(
                "ERR_ENTITLEMENT_WINDOW_CONFLICT",
                "The coverage window crowds a sibling entitlement on this shop and license.",
            )

    charged_cents = provisional_charge(
        shop, license_row, entitlement_model, seats_total, vin_quota
    )
    if shop["data_credit_balance_cents"] < charged_cents:
        raise err("ERR_INSUFFICIENT_DATA_CREDIT", "The shop's data credit balance is too low.")

    row = store.base_row()
    row["shop_id"] = shop_id
    row["license_id"] = license_id
    row["entitlement_model"] = entitlement_model
    row["seats_total"] = seats_total
    row["vin_quota"] = vin_quota
    row["window_start"] = start_raw
    row["window_end"] = end_raw
    row["_window_start"] = start
    row["_window_end"] = end
    row["status"] = "PENDING"
    row["charged_cents"] = charged_cents
    row["settled_cents"] = 0
    row["settlement_status"] = "UNSETTLED"
    row["seats_assigned"] = 0
    row["seats_available"] = seats_total
    store.entitlements[row["id"]] = row

    shop["data_credit_balance_cents"] = shop["data_credit_balance_cents"] - charged_cents
    store.touch(shop)
    return object_response(project("entitlement", row), 201)


@bp.get("/entitlements/<entitlement_id>")
def read_entitlement(entitlement_id):
    authenticate(ENTITLEMENT_READERS)
    row = find(store.entitlements, entitlement_id, "ERR_ENTITLEMENT_NOT_FOUND")
    return object_response(project("entitlement", row))


@bp.get("/entitlements")
def list_entitlements():
    authenticate(ENTITLEMENT_READERS)
    shop_id = q_str("shop_id")
    license_id = q_str("license_id")
    status = q_enum("status", ENTITLEMENT_STATUSES)
    limit, offset = pagination()

    rows = [
        row
        for row in store.entitlements.values()
        if (shop_id is None or row["shop_id"] == shop_id)
        and (license_id is None or row["license_id"] == license_id)
        and (status is None or row["status"] == status)
    ]
    return paged("entitlement", rows, limit, offset)


@bp.post("/entitlements/<entitlement_id>/activate")
def activate_entitlement(entitlement_id):
    user_id, role = authenticate(("ShopManager",))
    check_allowed(body_object(), ())
    entitlement = find(store.entitlements, entitlement_id, "ERR_ENTITLEMENT_NOT_FOUND")
    require_shop_scope(role, user_id, entitlement["shop_id"])

    if entitlement["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING entitlement may be activated.")
    license_row = store.licenses.get(entitlement["license_id"])
    if license_row is None or license_row["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "The license is not ACTIVE.")

    entitlement["status"] = "ACTIVE"
    store.touch(entitlement)
    shop = store.shops.get(entitlement["shop_id"])
    if shop is not None:
        stamp_shop_coverage(shop)
    return object_response(project("entitlement", entitlement))


@bp.post("/entitlements/<entitlement_id>/cancel")
def cancel_entitlement(entitlement_id):
    user_id, role = authenticate(("ShopManager",))
    body = body_object()
    check_allowed(body, ("reason",))
    get_str(body, "reason", min_len=1)
    entitlement = find(store.entitlements, entitlement_id, "ERR_ENTITLEMENT_NOT_FOUND")
    require_shop_scope(role, user_id, entitlement["shop_id"])

    if entitlement["status"] not in ("PENDING", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Only a PENDING or ACTIVE entitlement may be cancelled.")

    settle_entitlement(entitlement, "CANCELLED", role, user_id)
    cascade_revoke_seats(
        seats_of_entitlement(entitlement),
        "ENTITLEMENT_CANCELLED",
        "SEAT_REVOKED",
        "SYSTEM",
        None,
    )
    return object_response(project("entitlement", entitlement))


# -- seat assignments -----------------------------------------------------


@bp.post("/seat-assignments")
def seat_technician():
    user_id, role = authenticate(("ShopManager",))
    body = body_object()
    check_allowed(body, ("entitlement_id", "technician_id", "expected_entitlement_version"))
    entitlement_id = get_ref(body, "entitlement_id")
    technician_id = get_ref(body, "technician_id")
    expected_version = get_int(body, "expected_entitlement_version", minimum=1)

    # PRD 2.6 entity precedence: technician before entitlement.
    technician = find(store.technicians, technician_id, "ERR_TECHNICIAN_NOT_FOUND")
    entitlement = find(store.entitlements, entitlement_id, "ERR_ENTITLEMENT_NOT_FOUND")
    require_shop_scope(role, user_id, entitlement["shop_id"])
    if technician["shop_id"] != entitlement["shop_id"]:
        raise err(
            "ERR_CROSS_SHOP_ACCESS",
            "The technician's employer shop does not hold this entitlement.",
        )

    if expected_version != entitlement["version"]:
        raise err(
            "ERR_STALE_ENTITLEMENT_VERSION",
            "expected_entitlement_version does not match the entitlement's current version.",
        )

    prior = [
        seat
        for seat in seats_of_entitlement(entitlement)
        if seat["technician_id"] == technician_id and seat["status"] == "ACTIVE"
    ]
    if not prior and entitlement["seats_available"] <= 0:
        raise err("ERR_NO_SEATS_AVAILABLE", "The entitlement has no free seat.")

    for seat in prior:
        seat["status"] = "SUPERSEDED"
        store.touch(seat)

    row = store.base_row()
    row["entitlement_id"] = entitlement_id
    row["technician_id"] = technician_id
    row["status"] = "ACTIVE"
    row["revocation_reason"] = None
    store.seat_assignments[row["id"]] = row

    recompute_seat_ledger(entitlement)
    store.touch(entitlement)
    append_audit(role, user_id, "SeatAssignment", row["id"], "SEAT_ASSIGNED")
    return object_response(project("seat_assignment", row), 201)


@bp.get("/seat-assignments/<seat_id>")
def read_seat(seat_id):
    authenticate(SEAT_READERS)
    row = find(store.seat_assignments, seat_id, "ERR_SEAT_ASSIGNMENT_NOT_FOUND")
    return object_response(project("seat_assignment", row))


@bp.get("/seat-assignments")
def list_seats():
    authenticate(SEAT_READERS)
    entitlement_id = q_str("entitlement_id")
    technician_id = q_str("technician_id")
    status = q_enum("status", SEAT_STATUSES)
    limit, offset = pagination()

    rows = [
        row
        for row in store.seat_assignments.values()
        if (entitlement_id is None or row["entitlement_id"] == entitlement_id)
        and (technician_id is None or row["technician_id"] == technician_id)
        and (status is None or row["status"] == status)
    ]
    return paged("seat_assignment", rows, limit, offset)


@bp.post("/seat-assignments/<seat_id>/revoke")
def revoke_seat(seat_id):
    user_id, role = authenticate(("ShopManager",))
    body = body_object()
    check_allowed(body, ("reason",))
    reason = get_str(body, "reason", min_len=1)
    seat = find(store.seat_assignments, seat_id, "ERR_SEAT_ASSIGNMENT_NOT_FOUND")
    entitlement = store.entitlements.get(seat["entitlement_id"])
    if entitlement is not None:
        require_shop_scope(role, user_id, entitlement["shop_id"])

    if seat["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE seat may be revoked.")

    cascade_revoke_seats([seat], reason, "SEAT_REVOKED", role, user_id)
    return object_response(project("seat_assignment", seat))
