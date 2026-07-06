from datetime import timedelta

from flask import Blueprint, request

import errors
from errors import err
from db import db, base_fields, touch
from clock import iso_millis
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, require_positive_int, paginate
from routes.common import get_reservation, get_recipient, get_inventory
import domain

bp = Blueprint("reservations", __name__)

READ_ROLES = {"CatalogManager", "Recipient", "LabTech", "ComplianceOfficer", "BillingClerk"}


def _require_int_field(data, field):
    v = data.get(field)
    if field not in data or v is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


@bp.post("/vial-reservations")
def create_reservation():
    uid, role = get_auth()
    require_role(role, {"CatalogManager", "Recipient"})
    data = body()
    recipient_id = require_str(data, "recipient_id")
    inventory_id = require_str(data, "inventory_id")
    vial_count = require_positive_int(data, "vial_count")
    expected_version = _require_int_field(data, "expected_inventory_version")

    # existence (body ids): validate recipient then inventory
    recipient = get_recipient(recipient_id)
    inv = get_inventory(inventory_id)
    donor = db.donors.get(inv["donor_id"])

    # ownership for Recipient role
    if role == "Recipient" and recipient_id != uid:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Recipient may only reserve for themselves")

    # Business checks in fixed order:
    # 1) consent present (SIGNED for recipient+donor)
    has_consent = any(
        c["recipient_id"] == recipient_id
        and c["donor_id"] == inv["donor_id"]
        and c["status"] == "SIGNED"
        for c in db.recipient_consents.values()
    )
    if not has_consent:
        raise err(errors.ERR_CONSENT_MISSING, "No signed consent for recipient+donor")

    # 2) family limit
    if donor is not None and donor["is_family_limit_reached"]:
        raise err(errors.ERR_FAMILY_LIMIT_REACHED, "Donor family limit reached")

    # 3) inventory listable
    if not inv["is_listed"]:
        raise err(errors.ERR_INVENTORY_NOT_LISTED, "Inventory not listable")

    # 4) sufficient vials (booking view)
    if vial_count > inv["available_vials"]:
        raise err(errors.ERR_INSUFFICIENT_VIALS, "Insufficient available vials")

    # 5) OCC guard
    if expected_version != inv["version"]:
        raise err(errors.ERR_STALE_INVENTORY_VERSION, "Stale inventory version")

    res = base_fields(db)
    hold_expiry = res["_created_dt"] + timedelta(days=domain.HOLD_TTL_DAYS)
    res.update({
        "recipient_id": recipient_id,
        "inventory_id": inventory_id,
        "donor_id": inv["donor_id"],
        "vial_count": vial_count,
        "expected_inventory_version": expected_version,
        "hold_expiry": iso_millis(hold_expiry),
        "status": "HELD",
    })
    db.vial_reservations[res["id"]] = res
    # bump inventory version + recompute counts
    domain.recompute_inventory(inv, bump=True)
    return ok_object(res, 201)


@bp.get("/vial-reservations/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    return ok_object(get_reservation(i))


@bp.get("/vial-reservations")
def list_res():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    items = list(db.vial_reservations.values())
    recipient_f = request.args.get("recipient_id")
    inventory_f = request.args.get("inventory_id")
    donor_f = request.args.get("donor_id")
    status_f = request.args.get("status")
    if recipient_f is not None:
        items = [r for r in items if r["recipient_id"] == recipient_f]
    if inventory_f is not None:
        items = [r for r in items if r["inventory_id"] == inventory_f]
    if donor_f is not None:
        items = [r for r in items if r["donor_id"] == donor_f]
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/vial-reservations/<i>/confirm")
def confirm(i):
    _uid, role = get_auth()
    require_role(role, {"CatalogManager"})
    res = get_reservation(i)
    if res["status"] != "HELD":
        raise err(errors.ERR_INVALID_STATE, "Reservation not in HELD")
    from clock import parse_iso
    if db.now() >= parse_iso(res["hold_expiry"]):
        raise err(errors.ERR_INVALID_STATE, "Hold expired")
    inv = db.donor_inventories.get(res["inventory_id"])
    if inv is None or inv["hold_status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Inventory hold not OPEN")
    res["status"] = "CONFIRMED"
    touch(db, res)
    # counts unchanged (HELD and CONFIRMED both count in reserved) but committed view changes
    domain.recompute_inventory(inv, bump=True)
    return ok_object(res)


@bp.post("/vial-reservations/<i>/cancel")
def cancel(i):
    uid, role = get_auth()
    require_role(role, {"CatalogManager", "Recipient"})
    res = get_reservation(i)
    if role == "Recipient" and res["recipient_id"] != uid:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Recipient may only cancel own reservation")
    if res["status"] not in ("HELD", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "Reservation not cancellable")
    was_confirmed = res["status"] == "CONFIRMED"
    res["status"] = "CANCELLED"
    touch(db, res)
    if was_confirmed:
        for sh in db.shipments.values():
            if sh["reservation_id"] == res["id"]:
                domain.cancel_shipment_cascade(sh)
    inv = db.donor_inventories.get(res["inventory_id"])
    if inv is not None:
        domain.recompute_inventory(inv, bump=True)
    return ok_object(res)


@bp.post("/vial-reservations/<i>/expire")
def expire(i):
    _uid, role = get_auth()
    require_role(role, {"CatalogManager"})
    res = get_reservation(i)
    if res["status"] != "HELD":
        raise err(errors.ERR_INVALID_STATE, "Reservation not in HELD")
    from clock import parse_iso
    if db.now() < parse_iso(res["hold_expiry"]):
        raise err(errors.ERR_INVALID_STATE, "Hold not yet expired")
    res["status"] = "EXPIRED"
    touch(db, res)
    inv = db.donor_inventories.get(res["inventory_id"])
    if inv is not None:
        domain.recompute_inventory(inv, bump=True)
    return ok_object(res)
