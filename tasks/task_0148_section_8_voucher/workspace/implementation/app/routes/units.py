"""/units routes."""

from flask import Blueprint, request

from app import store
from app.envelope import list_response, success_response
from app.errors import forbidden_role, not_found
from app.routes._helpers import get_json_body, query_int, with_auth
from app.serializers import serialize_unit
from app.services import units as svc
from app.services.common import parse_pagination, paginate, sort_by_created_at


bp = Blueprint("units", __name__)


@bp.post("/units")
@with_auth("Landlord")
def create_unit(caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.create_unit(caller.user_id, body)
    return success_response(serialize_unit(record), status=201)


@bp.get("/units/<unit_id>")
@with_auth("Landlord", "CaseWorker", "Inspector")
def get_unit(unit_id, caller=None):
    record = store.units.get(unit_id)
    if record is None:
        raise not_found("Unit not found")
    if caller.role == "Landlord" and record.get("landlord_id") != caller.user_id:
        raise forbidden_role("Landlord may only read own units")
    return success_response(serialize_unit(record))


@bp.get("/units")
@with_auth("Landlord", "CaseWorker")
def list_units(caller=None):
    limit, offset = parse_pagination(request.args)
    zone = request.args.get("zone")
    bedroom_count = query_int("bedroom_count")
    occupancy_status = request.args.get("occupancy_status")
    landlord_filter = caller.user_id if caller.role == "Landlord" else None
    rows = svc.list_units(zone=zone, bedroom_count=bedroom_count, occupancy_status=occupancy_status, landlord_id_filter=landlord_filter)
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response((serialize_unit(u) for u in page), limit=limit, offset=offset, total=total)
