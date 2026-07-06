from flask import Blueprint, request

import errors
from errors import err
from db import db, base_fields, touch
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, require_bool, paginate
from routes.common import get_consent, get_recipient, get_donor

bp = Blueprint("consents", __name__)


def _recompute_consent_on_file(recipient):
    has_signed = any(
        c["recipient_id"] == recipient["id"] and c["status"] == "SIGNED"
        for c in db.recipient_consents.values()
    )
    recipient["consent_on_file"] = has_signed
    touch(db, recipient)


@bp.post("/recipient-consents")
def create_consent():
    _uid, role = get_auth()
    require_role(role, {"Recipient", "CatalogManager"})
    data = body()
    recipient_id = require_str(data, "recipient_id")
    donor_id = require_str(data, "donor_id")
    acknowledges_open_id = require_bool(data, "acknowledges_open_id")
    get_recipient(recipient_id)
    get_donor(donor_id)
    c = base_fields(db)
    c.update({
        "recipient_id": recipient_id,
        "donor_id": donor_id,
        "acknowledges_open_id": acknowledges_open_id,
        "status": "DRAFT",
    })
    db.recipient_consents[c["id"]] = c
    return ok_object(c, 201)


@bp.get("/recipient-consents/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, {"Recipient", "CatalogManager", "ComplianceOfficer"})
    return ok_object(get_consent(i))


@bp.get("/recipient-consents")
def list_consents():
    _uid, role = get_auth()
    require_role(role, {"Recipient", "CatalogManager", "ComplianceOfficer"})
    items = list(db.recipient_consents.values())
    recipient_f = request.args.get("recipient_id")
    donor_f = request.args.get("donor_id")
    status_f = request.args.get("status")
    if recipient_f is not None:
        items = [c for c in items if c["recipient_id"] == recipient_f]
    if donor_f is not None:
        items = [c for c in items if c["donor_id"] == donor_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/recipient-consents/<i>/sign")
def sign(i):
    _uid, role = get_auth()
    require_role(role, {"Recipient"})
    c = get_consent(i)
    if c["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Consent not in DRAFT")
    if not c["acknowledges_open_id"]:
        raise err(errors.ERR_CONSENT_NOT_ACKNOWLEDGED, "Open-identity not acknowledged")
    donor = db.donors.get(c["donor_id"])
    if donor is None or donor["status"] not in ("APPROVED", "ACTIVE"):
        raise err(errors.ERR_INVALID_STATE, "Donor not APPROVED/ACTIVE")
    c["status"] = "SIGNED"
    touch(db, c)
    recipient = db.recipients.get(c["recipient_id"])
    if recipient is not None:
        recipient["consent_on_file"] = True
        if recipient["status"] == "REGISTERED":
            recipient["status"] = "ACTIVE"
        touch(db, recipient)
    return ok_object(c)


@bp.post("/recipient-consents/<i>/revoke")
def revoke(i):
    _uid, role = get_auth()
    require_role(role, {"Recipient"})
    c = get_consent(i)
    if c["status"] != "SIGNED":
        raise err(errors.ERR_INVALID_STATE, "Consent not in SIGNED")
    # blocked by active reservation of same recipient+donor in {HELD, CONFIRMED, SHIPPED}
    for r in db.vial_reservations.values():
        if (r["recipient_id"] == c["recipient_id"]
                and r["donor_id"] == c["donor_id"]
                and r["status"] in ("HELD", "CONFIRMED", "SHIPPED")):
            raise err(errors.ERR_ACTIVE_RESERVATION_EXISTS, "Active reservation blocks revocation")
    c["status"] = "REVOKED"
    touch(db, c)
    recipient = db.recipients.get(c["recipient_id"])
    if recipient is not None:
        _recompute_consent_on_file(recipient)
    return ok_object(c)
