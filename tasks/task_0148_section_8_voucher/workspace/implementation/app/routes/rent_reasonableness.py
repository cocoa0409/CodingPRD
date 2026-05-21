"""/rent-reasonableness-records routes."""

from flask import Blueprint

from app import store
from app.envelope import success_response
from app.routes._helpers import get_json_body, with_auth
from app.serializers import serialize_rent_reasonableness
from app.services import rent_reasonableness as svc


bp = Blueprint("rent_reasonableness", __name__)


@bp.post("/rent-reasonableness-records")
@with_auth("CaseWorker")
def create_record(caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.create_record(body)
    return success_response(serialize_rent_reasonableness(record), status=201)
