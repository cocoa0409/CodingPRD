"""Query routes."""

from flask import Blueprint

from common import get_json_body
from middleware import require_roles
from response import success
from services import query as svc


bp = Blueprint("queries", __name__, url_prefix="/procurement")


@bp.post("/projects/<pid>/queries")
@require_roles("Supplier")
def submit_query(pid):
    body = get_json_body()
    q = svc.submit_query(pid, body)
    return success(q, 201)


@bp.post("/queries/<qid>/respond")
@require_roles("ProcurementOfficer")
def respond(qid):
    body = get_json_body()
    return success(svc.respond_to_query(qid, body), 200)
