from flask import request

from core import (store, authorize, respond_object, respond_list, serialize,
                  serialize_many, sort_by_created, paginate)
from lookups import get_condemnation

READ_ROLES = ["ProgramAdmin", "Inspector", "Establishment"]


def register(app):

    @app.route("/condemnations/<coid>", methods=["GET"])
    def get_condemnation_route(coid):
        authorize(READ_ROLES)
        order = get_condemnation(coid)
        return respond_object(serialize(order), 200)

    @app.route("/condemnations", methods=["GET"])
    def list_condemnations():
        authorize(READ_ROLES)
        device_id = request.args.get("device_id")
        inspection_id = request.args.get("inspection_id")
        status = request.args.get("status")
        items = list(store.condemnations.values())
        if device_id is not None:
            items = [c for c in items if c["device_id"] == device_id]
        if inspection_id is not None:
            items = [c for c in items if c["inspection_id"] == inspection_id]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)
