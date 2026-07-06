from flask import Blueprint, request

from db import db, base_fields
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, paginate
from routes.common import get_recipient

bp = Blueprint("recipients", __name__)


@bp.post("/recipients")
def create_recipient():
    _uid, role = get_auth()
    require_role(role, {"CatalogManager", "Recipient"})
    data = body()
    family_name = require_str(data, "family_name")
    contact_email = require_str(data, "contact_email")
    r = base_fields(db)
    r.update({
        "family_name": family_name,
        "contact_email": contact_email,
        "consent_on_file": False,
        "status": "REGISTERED",
    })
    db.recipients[r["id"]] = r
    return ok_object(r, 201)


@bp.get("/recipients/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, {"CatalogManager", "Recipient", "ComplianceOfficer", "BillingClerk"})
    return ok_object(get_recipient(i))


@bp.get("/recipients")
def list_recipients():
    _uid, role = get_auth()
    require_role(role, {"CatalogManager", "ComplianceOfficer", "BillingClerk"})
    items = list(db.recipients.values())
    status_f = request.args.get("status")
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)
