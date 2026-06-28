from flask import Blueprint, request

from db import db, stamp_create
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from validate import get_body, req_str, req_enum, opt_bool, pagination_params

bp = Blueprint("technicians", __name__)

CERTIFICATIONS = {"WRT", "ASD", "AMRT"}


@bp.route("/restoration/technicians", methods=["POST"])
def create_technician():
    auth(["PlatformAdmin", "Dispatcher"])
    body = get_body()
    full_name = req_str(body, "full_name")
    certification = req_enum(body, "certification", CERTIFICATIONS)
    active = opt_bool(body, "active", default=True)

    entity = {
        "full_name": full_name,
        "certification": certification,
        "active": active,
    }
    # Technician is immutable: only id + created_at (PRD §2.4).
    stamp_create(entity, with_version=False)
    db.technicians[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/restoration/technicians/<technician_id>", methods=["GET"])
def get_technician(technician_id):
    auth(["PlatformAdmin", "Dispatcher", "Technician"])
    return object_response(get_or_404(db.technicians, technician_id))


@bp.route("/restoration/technicians", methods=["GET"])
def list_technicians():
    auth(["PlatformAdmin", "Dispatcher", "Technician"])
    certification = request.args.get("certification")
    active = request.args.get("active")
    limit, offset = pagination_params()

    items = list(db.technicians.values())
    if certification is not None:
        items = [t for t in items if t["certification"] == certification]
    if active is not None:
        want = active.lower() in ("true", "1")
        items = [t for t in items if t["active"] == want]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
