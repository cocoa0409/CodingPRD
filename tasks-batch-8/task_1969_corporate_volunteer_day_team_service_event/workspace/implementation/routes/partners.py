"""NonprofitPartner endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err, ERR_NONPROFIT_NOT_FOUND
from middleware import authenticate, body
from response import success_object, success_list
from services.core import mint, ser_partner, sort_entities
from validate import req_string

bp = Blueprint("partners", __name__)


@bp.post("/nonprofit-partners")
def create_partner():
    authenticate(["CommunityEngagementManager"])
    data = body()
    name = req_string(data, "name")
    contact_email = req_string(data, "contact_email")
    p = mint()
    p.update({"name": name, "contact_email": contact_email, "status": "ACTIVE"})
    db.partners[p["id"]] = p
    return success_object(ser_partner(p), 201)


@bp.get("/nonprofit-partners")
def list_partners():
    authenticate(["Any"])
    items = list(db.partners.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return success_list([ser_partner(p) for p in sort_entities(items)])


@bp.get("/nonprofit-partners/<partnerId>")
def get_partner(partnerId):
    authenticate(["Any"])
    p = db.partners.get(partnerId)
    if p is None:
        raise_err(ERR_NONPROFIT_NOT_FOUND, "nonprofit partner not found")
    return success_object(ser_partner(p))
