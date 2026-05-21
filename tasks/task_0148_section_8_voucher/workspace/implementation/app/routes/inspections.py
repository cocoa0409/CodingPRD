"""/inspections routes."""

from flask import Blueprint

from app import store
from app.envelope import success_response
from app.errors import not_found
from app.routes._helpers import get_json_body, with_auth
from app.serializers import serialize_inspection
from app.services import inspections as svc


bp = Blueprint("inspections", __name__)


@bp.post("/inspections")
@with_auth("Inspector", "CaseWorker")
def schedule_inspection(caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.schedule_inspection(body)
    return success_response(serialize_inspection(record), status=201)


@bp.post("/inspections/<inspection_id>/complete")
@with_auth("Inspector")
def complete_inspection(inspection_id, caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.complete_inspection(
            inspection_id, body, caller_id=caller.user_id if caller else None,
        )
    return success_response(serialize_inspection(record))


@bp.get("/inspections/<inspection_id>")
@with_auth("Inspector", "CaseWorker", "Landlord")
def get_inspection(inspection_id, caller=None):
    record = store.inspections.get(inspection_id)
    if record is None:
        raise not_found("Inspection not found")
    return success_response(serialize_inspection(record))
