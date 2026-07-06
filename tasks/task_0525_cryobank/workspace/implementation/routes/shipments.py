from flask import Blueprint, request

import errors
from errors import err
from db import db, base_fields, touch
from clock import iso_millis
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, paginate
from routes.common import get_shipment, get_reservation
import domain
from billing import issue_invoice

bp = Blueprint("shipments", __name__)

READ_ROLES = {"LabTech", "ComplianceOfficer", "Recipient"}


@bp.post("/shipments")
def create_shipment():
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    data = body()
    reservation_id = require_str(data, "reservation_id")
    clinic_address = require_str(data, "clinic_address")
    ln2_dewar_serial = require_str(data, "ln2_dewar_serial")
    res = get_reservation(reservation_id)
    sh = base_fields(db)
    sh.update({
        "reservation_id": reservation_id,
        "recipient_id": res["recipient_id"],
        "clinic_address": clinic_address,
        "ln2_dewar_serial": ln2_dewar_serial,
        "dispatched_at": None,
        "status": "PREPARING",
    })
    db.shipments[sh["id"]] = sh
    return ok_object(sh, 201)


@bp.get("/shipments/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    return ok_object(get_shipment(i))


@bp.get("/shipments")
def list_shipments():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    items = list(db.shipments.values())
    reservation_f = request.args.get("reservation_id")
    recipient_f = request.args.get("recipient_id")
    status_f = request.args.get("status")
    if reservation_f is not None:
        items = [s for s in items if s["reservation_id"] == reservation_f]
    if recipient_f is not None:
        items = [s for s in items if s["recipient_id"] == recipient_f]
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/shipments/<i>/dispatch")
def dispatch(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    sh = get_shipment(i)
    if sh["status"] != "PREPARING":
        raise err(errors.ERR_INVALID_STATE, "Shipment not PREPARING")
    res = db.vial_reservations.get(sh["reservation_id"])
    if res is None or res["status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Linked reservation not CONFIRMED")
    inv = db.donor_inventories.get(res["inventory_id"])
    if inv is None or inv["hold_status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Inventory hold not OPEN")

    sh["status"] = "DISPATCHED"
    sh["dispatched_at"] = iso_millis(db.now())
    touch(db, sh)

    # drive reservation CONFIRMED -> SHIPPED
    res["status"] = "SHIPPED"
    touch(db, res)
    domain.recompute_inventory(inv, bump=True)

    # create StorageAccount + period-0 RENEWAL invoice (full period)
    acct = base_fields(db)
    acct.update({
        "recipient_id": res["recipient_id"],
        "reservation_id": res["id"],
        "stored_vials": res["vial_count"],
        "period_start": iso_millis(db.now()),
        "paid_through": None,
        "status": "ACTIVE",
    })
    db.storage_accounts[acct["id"]] = acct
    issue_invoice(acct, period_index=0, billing_mode="RENEWAL",
                  remaining_days=domain.BILLING_PERIOD_DAYS)
    return ok_object(sh)


@bp.post("/shipments/<i>/deliver")
def deliver(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    sh = get_shipment(i)
    if sh["status"] != "DISPATCHED":
        raise err(errors.ERR_INVALID_STATE, "Shipment not DISPATCHED")
    sh["status"] = "DELIVERED"
    touch(db, sh)
    return ok_object(sh)
