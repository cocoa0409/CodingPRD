from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, get_ref_or_404, paginate
from validate import get_body, req_str, req_int, pagination_params

bp = Blueprint("contents", __name__)


@bp.route("/restoration/contents", methods=["POST"])
def create_contents():
    auth(["Technician"])
    body = get_body()
    job_id = req_str(body, "job_id")
    get_ref_or_404(db.jobs, job_id)
    description = req_str(body, "description")
    declared_value_cents = req_int(body, "declared_value_cents", minimum=0)

    entity = {
        "job_id": job_id,
        "description": description,
        "declared_value_cents": declared_value_cents,
        "allocated_value_cents": 0,
        "status": "PACKED_OUT",
    }
    stamp_create(entity)
    db.contents[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/restoration/contents/<item_id>", methods=["GET"])
def get_contents(item_id):
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    return object_response(get_or_404(db.contents, item_id))


@bp.route("/restoration/contents", methods=["GET"])
def list_contents():
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    limit, offset = pagination_params()

    items = list(db.contents.values())
    if job_id is not None:
        items = [c for c in items if c["job_id"] == job_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/restoration/contents/<item_id>/store", methods=["POST"])
def store_contents(item_id):
    auth(["Technician"])
    item = get_or_404(db.contents, item_id)
    if item["status"] != "PACKED_OUT":
        raise err("ERR_INVALID_STATE", "Only a PACKED_OUT item can be stored.")
    item["status"] = "STORED"
    touch(item)
    return object_response(item)


@bp.route("/restoration/contents/<item_id>/return", methods=["POST"])
def return_contents(item_id):
    auth(["Technician"])
    item = get_or_404(db.contents, item_id)
    # PACKED_OUT -> RETURNED or STORED -> RETURNED are both valid.
    if item["status"] not in ("PACKED_OUT", "STORED"):
        raise err("ERR_INVALID_STATE", "Only a PACKED_OUT or STORED item can be returned.")
    item["status"] = "RETURNED"
    touch(item)
    return object_response(item)
