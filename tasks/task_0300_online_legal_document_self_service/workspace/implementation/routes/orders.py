"""Order read routes (1:1 with project; created as a side effect)."""

from flask import Blueprint, request

from common import get_or_404, list_collection, serialize
from db import store
from middleware import parse_pagination, roles
from response import array_response, object_response

bp = Blueprint("orders", __name__)


@bp.route("/legal/orders/<oid>", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def get_order(oid):
    ent = get_or_404(store.orders, oid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/orders", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def list_orders():
    limit, offset = parse_pagination()
    project_id = request.args.get("document_project_id")

    def predicate(e):
        if project_id is not None and e["document_project_id"] != project_id:
            return False
        return True

    page, total = list_collection(store.orders, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)
