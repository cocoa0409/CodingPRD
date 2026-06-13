"""AssembledClause read routes (created only as a side effect of assemble)."""

from flask import Blueprint, request

from common import get_or_404, list_collection, serialize
from db import store
from middleware import parse_pagination, roles
from response import array_response, object_response

bp = Blueprint("assembled_clauses", __name__)


@bp.route("/legal/assembled-clauses/<cid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_assembled_clause(cid):
    ent = get_or_404(store.assembled_clauses, cid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/assembled-clauses", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def list_assembled_clauses():
    limit, offset = parse_pagination()
    project_id = request.args.get("document_project_id")

    def predicate(e):
        if project_id is not None and e["document_project_id"] != project_id:
            return False
        return True

    page, total = list_collection(store.assembled_clauses, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)
