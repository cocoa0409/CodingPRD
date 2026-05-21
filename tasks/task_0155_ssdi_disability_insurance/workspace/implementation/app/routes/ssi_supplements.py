"""SSISupplement routes."""

from __future__ import annotations

from flask import Blueprint

from app.envelope import success_response
from app.routes._helpers import get_json_body, with_auth
from app.serializers import serialize_ssi_supplement
from app.services import ssi_supplements as service


bp = Blueprint("ssi_supplements", __name__)


@bp.route("/ssi-supplements", methods=["POST"])
@with_auth("Claimant", "DDS_Examiner")
def create_supplement(caller):
    body = get_json_body()
    record = service.create_supplement(body)
    return success_response(serialize_ssi_supplement(record), status=201)


@bp.route("/ssi-supplements/<supplement_id>/activate", methods=["POST"])
@with_auth("DDS_Examiner")
def activate(caller, supplement_id: str):
    record = service.activate_supplement(supplement_id)
    return success_response(serialize_ssi_supplement(record))


@bp.route("/ssi-supplements/<supplement_id>", methods=["PATCH"])
@with_auth("DDS_Examiner", "Claimant")
def patch_supplement(caller, supplement_id: str):
    body = get_json_body()
    record = service.patch_supplement(supplement_id, body)
    return success_response(serialize_ssi_supplement(record))
