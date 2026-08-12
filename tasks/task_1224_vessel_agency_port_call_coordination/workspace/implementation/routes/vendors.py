"""Vendor endpoints."""
from flask import Blueprint, request

from errors import invalid_request, invalid_state, not_found
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import new_entity, paginate, pagination_args, sort_created, touch

bp = Blueprint("vendors", __name__)

CATEGORIES = {"PROVISIONS", "BUNKERS", "REPAIRS", "STORES"}


def _get_or_404(vid):
    ent = domain.get("vendors", vid)
    if ent is None:
        not_found("vendor")
    return ent


@bp.post("/vendors")
def create_vendor():
    require_roles(["AgencyAdmin"])
    body = request.get_json(silent=True) or {}
    categories = body.get("categories")
    if (not isinstance(body.get("name"), str) or not body.get("name")
            or not isinstance(categories, list) or not categories
            or any(c not in CATEGORIES for c in categories)
            or not isinstance(body.get("contact_email"), str) or not body.get("contact_email")):
        invalid_request("name, a non-empty valid categories list and contact_email are required")
    ent = new_entity("vendors", {
        "name": body["name"],
        "categories": list(categories),
        "contact_email": body["contact_email"],
        "status": "ACTIVE",
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/vendors")
def list_vendors():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("vendors"))
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/vendors/<vid>")
def get_vendor(vid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(vid)))


@bp.post("/vendors/<vid>/suspend")
def suspend_vendor(vid):
    require_roles(["AgencyAdmin"])
    ent = _get_or_404(vid)
    if ent["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE vendor can be suspended")
    ent["status"] = "SUSPENDED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/vendors/<vid>/reinstate")
def reinstate_vendor(vid):
    require_roles(["AgencyAdmin"])
    ent = _get_or_404(vid)
    if ent["status"] != "SUSPENDED":
        invalid_state("Only a SUSPENDED vendor can be reinstated")
    ent["status"] = "ACTIVE"
    touch(ent)
    return ok_object(serialize(ent))
