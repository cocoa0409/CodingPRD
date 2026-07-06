from flask import Blueprint, request

import errors
from errors import err
from db import db, base_fields, touch
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, paginate
from routes.common import get_registry, get_donor, get_recipient
from routes.specimens import _validate_dt
import domain

bp = Blueprint("sibling", __name__)


@bp.post("/sibling-registry")
def create_entry():
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer", "Recipient"})
    data = body()
    donor_id = require_str(data, "donor_id")
    recipient_id = require_str(data, "recipient_id")
    birth_reported_date = _validate_dt(data, "birth_reported_date")
    get_donor(donor_id)
    get_recipient(recipient_id)
    e = base_fields(db)
    e.update({
        "donor_id": donor_id,
        "recipient_id": recipient_id,
        "birth_reported_date": birth_reported_date,
        "status": "PENDING",
    })
    db.sibling_registry[e["id"]] = e
    return ok_object(e, 201)


@bp.get("/sibling-registry/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer", "Recipient"})
    return ok_object(get_registry(i))


@bp.get("/sibling-registry")
def list_entries():
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer", "Recipient"})
    items = list(db.sibling_registry.values())
    donor_f = request.args.get("donor_id")
    recipient_f = request.args.get("recipient_id")
    status_f = request.args.get("status")
    if donor_f is not None:
        items = [e for e in items if e["donor_id"] == donor_f]
    if recipient_f is not None:
        items = [e for e in items if e["recipient_id"] == recipient_f]
    if status_f is not None:
        items = [e for e in items if e["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/sibling-registry/<i>/confirm")
def confirm(i):
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    e = get_registry(i)
    if e["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Entry not PENDING")
    has_shipped = any(
        r["recipient_id"] == e["recipient_id"]
        and r["donor_id"] == e["donor_id"]
        and r["status"] == "SHIPPED"
        for r in db.vial_reservations.values()
    )
    if not has_shipped:
        raise err(errors.ERR_REGISTRY_NO_SHIPMENT, "No shipped reservation for recipient+donor")
    e["status"] = "CONFIRMED"
    touch(db, e)
    donor = db.donors.get(e["donor_id"])
    if donor is not None:
        domain.recompute_family_count(donor)
    return ok_object(e)


@bp.post("/sibling-registry/<i>/reject")
def reject(i):
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    e = get_registry(i)
    if e["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Entry not PENDING")
    e["status"] = "REJECTED"
    touch(db, e)
    return ok_object(e)
