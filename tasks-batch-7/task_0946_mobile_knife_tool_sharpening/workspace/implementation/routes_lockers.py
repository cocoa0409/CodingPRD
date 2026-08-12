"""The customer-operated drop-off locker channel."""

import datetime

from flask import Blueprint

import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import COMPARTMENT_STATUSES, LOCKER_ABANDON_GRACE_HOURS, LOCKER_SIZES
from errors import ApiError
from store import db, touch

bp = Blueprint("lockers", __name__)

ACCESS_SPEC = ladder.Spec(required=[("access_code", "string")])


def _holding_request(compartment):
    return db.service_requests.get(compartment["current_service_request_id"])


def _holding_account(compartment):
    request_row = _holding_request(compartment)
    if request_row is None:
        return None
    return db.accounts.get(request_row["account_id"])


@bp.route("/sharpening/locker-compartments/<id>", methods=["GET"])
def get_compartment(id):
    ctx = ladder.begin("PlatformAdmin", "AccountOwner", "Technician")
    row = ladder.must_exist(db.locker_compartments, id, "LockerCompartment")
    account = _holding_account(row)
    services.own_account(ctx, account["id"] if account else None)
    services.acting_technician(ctx)
    return envelope.ok(ser.locker_compartment(row))


@bp.route("/sharpening/locker-compartments", methods=["GET"])
def list_compartments():
    ctx = ladder.begin("PlatformAdmin", "AccountOwner", "Technician")
    ladder.check_query_enums(
        ctx.query, {"size": LOCKER_SIZES, "status": COMPARTMENT_STATUSES}
    )
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.locker_compartments.values())
    for field in ("site_code", "size", "status", "current_service_request_id"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing(
        [ser.locker_compartment(r) for r in page], limit, offset, total
    )


# ---------------------------------------------------------------------------
# POST /sharpening/locker-compartments/{id}/deposit
# ---------------------------------------------------------------------------
@bp.route("/sharpening/locker-compartments/<id>/deposit", methods=["POST"])
def deposit(id):
    ctx = ladder.begin("AccountOwner")
    compartment = ladder.must_exist(db.locker_compartments, id, "LockerCompartment")
    ACCESS_SPEC.validate(ctx.body)
    account = _holding_account(compartment)
    services.own_account(ctx, account["id"] if account else None)
    services.account_active(account)
    request_row = _holding_request(compartment)
    if compartment["status"] != "ASSIGNED" or request_row is None:
        raise ApiError("ERR_INVALID_STATE", "The compartment is not awaiting a deposit.")
    if request_row["status"] != "SUBMITTED" or request_row["channel"] != "LOCKER":
        raise ApiError("ERR_INVALID_STATE", "The request cannot be deposited.")
    # Rung 21 -- deliberately above the access-code rung.
    if compartment["hold_expires_at"] is not None and (
        clockmod.now() >= compartment["hold_expires_at"]
    ):
        raise ApiError("ERR_LOCKER_HOLD_EXPIRED")
    # Rung 57 -- the last rung of all.
    if ctx.body["access_code"] != compartment["access_code"]:
        raise ApiError("ERR_ACCESS_CODE_INVALID")

    for item in ser.request_items(request_row["id"]):
        if item["custody_location"] == "CUSTOMER":
            item["custody_location"] = "LOCKER"
            touch(item)
    compartment["status"] = "OCCUPIED"
    touch(compartment)
    request_row["status"] = "IN_SERVICE"
    touch(request_row)
    return envelope.ok(ser.locker_compartment(compartment))


# ---------------------------------------------------------------------------
# POST /sharpening/locker-compartments/{id}/release
# ---------------------------------------------------------------------------
@bp.route("/sharpening/locker-compartments/<id>/release", methods=["POST"])
def release(id):
    ctx = ladder.begin("AccountOwner")
    compartment = ladder.must_exist(db.locker_compartments, id, "LockerCompartment")
    ACCESS_SPEC.validate(ctx.body)
    account = _holding_account(compartment)
    services.own_account(ctx, account["id"] if account else None)
    services.account_active(account)
    request_row = _holding_request(compartment)
    if compartment["status"] != "OCCUPIED" or request_row is None:
        raise ApiError("ERR_INVALID_STATE", "The compartment is not OCCUPIED.")
    items = ser.request_items(request_row["id"])
    if any(i["service_status"] != "DELIVERED" for i in items):
        raise ApiError("ERR_INVALID_STATE", "The work is not finished.")
    # Rung 19.
    if any(i["custody_location"] != "LOCKER" for i in items):
        raise ApiError("ERR_ITEM_NOT_IN_CUSTODY")
    # Rung 21.
    if compartment["hold_expires_at"] is not None and (
        clockmod.now() >= compartment["hold_expires_at"]
    ):
        raise ApiError("ERR_LOCKER_HOLD_EXPIRED")
    # Rung 57.
    if ctx.body["access_code"] != compartment["access_code"]:
        raise ApiError("ERR_ACCESS_CODE_INVALID")

    now = clockmod.now()
    for item in items:
        item["custody_location"] = "DELIVERED"
        item["delivered_at"] = now
        touch(item)
    compartment["status"] = "AVAILABLE"
    compartment["access_code"] = None
    compartment["current_service_request_id"] = None
    compartment["last_released_at"] = now
    touch(compartment)
    issue = services.open_loaner_issue_for(request_row["id"])
    if issue is not None:
        services.close_loaner_issue(issue, damage_reported=False)
    return envelope.ok(ser.locker_compartment(compartment))


# ---------------------------------------------------------------------------
# POST /sharpening/locker-compartments/{id}/expire-hold
# ---------------------------------------------------------------------------
@bp.route("/sharpening/locker-compartments/<id>/expire-hold", methods=["POST"])
def expire_hold(id):
    ladder.begin("PlatformAdmin")
    compartment = ladder.must_exist(db.locker_compartments, id, "LockerCompartment")
    services.account_active(_holding_account(compartment))
    if compartment["status"] != "OCCUPIED":
        raise ApiError("ERR_INVALID_STATE", "The compartment is not OCCUPIED.")
    if compartment["hold_expires_at"] is None or clockmod.now() < compartment["hold_expires_at"]:
        raise ApiError("ERR_INVALID_STATE", "The hold has not expired yet.")
    compartment["status"] = "HOLD_EXPIRED"
    compartment["access_code"] = None
    touch(compartment)
    return envelope.ok(ser.locker_compartment(compartment))


# ---------------------------------------------------------------------------
# POST /sharpening/locker-compartments/{id}/abandon
# ---------------------------------------------------------------------------
@bp.route("/sharpening/locker-compartments/<id>/abandon", methods=["POST"])
def abandon(id):
    ladder.begin("PlatformAdmin")
    compartment = ladder.must_exist(db.locker_compartments, id, "LockerCompartment")
    services.account_active(_holding_account(compartment))
    if compartment["status"] != "HOLD_EXPIRED":
        raise ApiError("ERR_INVALID_STATE", "The compartment is not HOLD_EXPIRED.")
    if compartment["hold_expires_at"] is None:
        raise ApiError("ERR_INVALID_STATE", "The compartment carries no hold expiry.")
    grace_end = compartment["hold_expires_at"] + datetime.timedelta(
        hours=LOCKER_ABANDON_GRACE_HOURS
    )
    if clockmod.now() < grace_end:
        raise ApiError("ERR_INVALID_STATE", "The abandonment grace has not elapsed.")
    request_row = _holding_request(compartment)
    items = ser.request_items(request_row["id"]) if request_row else []
    # Rung 19.
    if any(i["custody_location"] != "LOCKER" for i in items):
        raise ApiError("ERR_ITEM_NOT_IN_CUSTODY")

    for item in items:
        item["custody_location"] = "ABANDONED"
        item["service_status"] = "ABANDONED"
        touch(item)
    compartment["status"] = "AVAILABLE"
    compartment["access_code"] = None
    compartment["current_service_request_id"] = None
    compartment["last_released_at"] = clockmod.now()
    touch(compartment)
    return envelope.ok(ser.locker_compartment(compartment))
