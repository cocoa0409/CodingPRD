from flask import request

from core import (store, authorize, respond_object, respond_list, serialize,
                  serialize_many, sort_by_created, paginate)
from lookups import get_seal

READ_ROLES = ["ProgramAdmin", "Inspector", "Establishment"]


def register(app):

    @app.route("/seals/<sid>", methods=["GET"])
    def get_seal_route(sid):
        authorize(READ_ROLES)
        seal = get_seal(sid)
        return respond_object(serialize(seal), 200)

    @app.route("/seals", methods=["GET"])
    def list_seals():
        authorize(READ_ROLES)
        device_id = request.args.get("device_id")
        inspection_id = request.args.get("inspection_id")
        status = request.args.get("status")
        items = list(store.seals.values())
        if device_id is not None:
            items = [s for s in items if s["device_id"] == device_id]
        if inspection_id is not None:
            items = [s for s in items if s["inspection_id"] == inspection_id]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)
