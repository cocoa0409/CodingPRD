"""Principal endpoints."""
from flask import Blueprint, request

from errors import invalid_request, invalid_state, not_found
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import is_int, new_entity, paginate, pagination_args, sort_created, touch

bp = Blueprint("principals", __name__)


@bp.post("/principals")
def create_principal():
    require_roles(["AgencyAdmin"])
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    contact_email = body.get("contact_email")
    credit_limit = body.get("credit_limit_cents")
    if (not isinstance(name, str) or not name
            or not isinstance(contact_email, str) or not contact_email
            or not is_int(credit_limit) or credit_limit < 0):
        invalid_request("name, contact_email and a non-negative integer credit_limit_cents are required")
    ent = new_entity("principals", {
        "name": name,
        "contact_email": contact_email,
        "credit_limit_cents": credit_limit,
        "status": "ACTIVE",
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/principals")
def list_principals():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("principals"))
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/principals/<pid>")
def get_principal(pid):
    require_roles(ANY_ROLE)
    ent = domain.get("principals", pid)
    if ent is None:
        not_found("principal")
    return ok_object(serialize(ent))


@bp.post("/principals/<pid>/suspend")
def suspend_principal(pid):
    require_roles(["AgencyAdmin"])
    ent = domain.get("principals", pid)
    if ent is None:
        not_found("principal")
    if ent["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE principal can be suspended")
    ent["status"] = "SUSPENDED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/principals/<pid>/reinstate")
def reinstate_principal(pid):
    require_roles(["AgencyAdmin"])
    ent = domain.get("principals", pid)
    if ent is None:
        not_found("principal")
    if ent["status"] != "SUSPENDED":
        invalid_state("Only a SUSPENDED principal can be reinstated")
    ent["status"] = "ACTIVE"
    touch(ent)
    return ok_object(serialize(ent))


@bp.get("/principals/<pid>/exposure")
def principal_exposure(pid):
    require_roles(ANY_ROLE)
    ent = domain.get("principals", pid)
    if ent is None:
        not_found("principal")
    forward, cash = domain.principal_exposure(pid)
    limit = ent["credit_limit_cents"]
    headroom = None if limit == 0 else limit - forward
    return ok_object({
        "forward_exposure_cents": forward,
        "cash_basis_exposure_cents": cash,
        "credit_limit_cents": limit,
        "credit_headroom_cents": headroom,
    })
