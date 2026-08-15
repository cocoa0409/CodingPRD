"""Landowner endpoints."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("landowners", __name__)


def get_landowner_or_404(landowner_id):
    r = db.landowners.get(landowner_id)
    if r is None:
        raise ApiError("ERR_LANDOWNER_NOT_FOUND", "Landowner id does not exist.", 404)
    return r


@bp.route("/stewardship/landowners", methods=["POST"])
@require_roles("TrustAdmin")
def create_landowner():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    easement = db.easements.get(easement_id)
    # Uniqueness / slot rule (priority 8): initial landowner only while DRAFT and none exists.
    if easement is not None:
        exists = any(r["easement_id"] == easement_id for r in db.landowners.values())
        if easement["status"] != "DRAFT" or exists:
            raise ApiError(
                "ERR_OPEN_OBLIGATIONS_EXIST",
                "Initial landowner creation requires a DRAFT easement with no landowner yet.",
                409,
            )
    owner_name = b.get("owner_name")
    contact_email = b.get("contact_email")
    if easement is None or not isinstance(owner_name, str) or not isinstance(contact_email, str):
        raise ApiError(
            "ERR_INVALID_REQUEST", "easement_id, owner_name and contact_email are required.", 400
        )
    now = utils.now_iso()
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "predecessor_landowner_id": None,
        "owner_name": owner_name,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "acquired_on": utils.today(),
    }
    db.landowners[r["id"]] = r
    easement["current_landowner_id"] = r["id"]
    domain.bump(easement)
    return ok(domain.landowner_json(r), 201)


@bp.route("/stewardship/landowners", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_landowners():
    from flask import request

    filters = {}
    for key in ("easement_id", "predecessor_landowner_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.landowners.values()), domain.landowner_json, filters)


@bp.route("/stewardship/landowners/<landownerId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_landowner(landownerId):
    return ok(domain.landowner_json(get_landowner_or_404(landownerId)))
