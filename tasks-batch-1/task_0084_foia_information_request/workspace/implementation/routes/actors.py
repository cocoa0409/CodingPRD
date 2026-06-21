"""Actor registration + fetch: Requester, FoiaOfficer, AppealAuthority, Submitter."""

from flask import Blueprint

import db
from errors import api_error, ERR_INVALID_REQUEST
from helpers import (
    get_json_body, require_str, opt_str, require_bool, require_enum,
    get_or_404, serialize,
)
from middleware import require_roles
from response import ok_object

bp = Blueprint("actors", __name__)

REQUESTER_CATEGORIES = {"COMMERCIAL", "EDUCATIONAL", "NEWS_MEDIA", "OTHER"}


@bp.post("/requesters")
def register_requester():
    require_roles("Requester", "FoiaOfficer")
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    declared_category = require_enum(body, "declared_category", REQUESTER_CATEGORIES)
    organization = opt_str(body, "organization")

    # email unique across requesters
    for r in db.requesters.values():
        if r["email"] == email:
            raise api_error(ERR_INVALID_REQUEST, "email must be unique across requesters.")

    obj = {
        "full_name": full_name,
        "email": email,
        "organization": organization,
        "declared_category": declared_category,
        "outstanding_balance_cents": 0,
    }
    db.stamp_create(obj)
    db.requesters[obj["id"]] = obj
    return ok_object(serialize("Requester", obj), status=201)


@bp.get("/requesters/<rid>")
def get_requester(rid):
    require_roles("Requester", "FoiaOfficer")
    obj = get_or_404(db.requesters, rid)
    return ok_object(serialize("Requester", obj), status=200)


@bp.post("/officers")
def register_officer():
    require_roles("FoiaOfficer")
    body = get_json_body()
    full_name = require_str(body, "full_name")
    badge_id = require_str(body, "badge_id")
    can_invoke_glomar = require_bool(body, "can_invoke_glomar", default=False)

    for o in db.officers.values():
        if o["badge_id"] == badge_id:
            raise api_error(ERR_INVALID_REQUEST, "badge_id must be unique.")

    obj = {
        "full_name": full_name,
        "badge_id": badge_id,
        "can_invoke_glomar": can_invoke_glomar,
    }
    db.stamp_create(obj)
    db.officers[obj["id"]] = obj
    return ok_object(serialize("FoiaOfficer", obj), status=201)


@bp.post("/appeal-authorities")
def register_authority():
    require_roles("FoiaOfficer")
    body = get_json_body()
    full_name = require_str(body, "full_name")
    badge_id = require_str(body, "badge_id")

    for a in db.appeal_authorities.values():
        if a["badge_id"] == badge_id:
            raise api_error(ERR_INVALID_REQUEST, "badge_id must be unique.")

    obj = {"full_name": full_name, "badge_id": badge_id}
    db.stamp_create(obj)
    db.appeal_authorities[obj["id"]] = obj
    return ok_object(serialize("AppealAuthority", obj), status=201)


@bp.post("/submitters")
def register_submitter():
    require_roles("FoiaOfficer")
    body = get_json_body()
    company_name = require_str(body, "company_name")
    contact_email = require_str(body, "contact_email")

    for s in db.submitters.values():
        if s["contact_email"] == contact_email:
            raise api_error(ERR_INVALID_REQUEST, "contact_email must be unique.")

    obj = {"company_name": company_name, "contact_email": contact_email}
    db.stamp_create(obj)
    db.submitters[obj["id"]] = obj
    return ok_object(serialize("Submitter", obj), status=201)
