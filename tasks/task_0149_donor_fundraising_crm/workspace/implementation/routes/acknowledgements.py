"""Acknowledgement read endpoints (all roles)."""

from flask import Blueprint, request

import db
import lookup
import models
import response
import util
from middleware import authenticate, require_role

bp = Blueprint("acknowledgements", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}


@bp.get("/acknowledgements/<aid>")
def get_acknowledgement(aid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        a = lookup.acknowledgement(aid)
        return response.object_response(models.serialize(a))


@bp.get("/acknowledgements")
def list_acknowledgements():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        donor_id = request.args.get("donor_id")
        kind = request.args.get("kind")
        rows = list(db.acknowledgements.values())
        if donor_id is not None:
            rows = [a for a in rows if a["donor_id"] == donor_id]
        if kind is not None:
            rows = [a for a in rows if a["kind"] == kind]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)
