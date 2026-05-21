"""ChildAuxiliary routes."""

from __future__ import annotations

from flask import Blueprint, request

from app.envelope import list_response, success_response
from app.routes._helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    with_auth,
)
from app.serializers import serialize_child_auxiliary
from app.services import child_auxiliaries as service


bp = Blueprint("child_auxiliaries", __name__)


@bp.route("/child-auxiliaries", methods=["POST"])
@with_auth("Claimant", "DDS_Examiner")
def create_child(caller):
    body = get_json_body()
    record = service.create_child(body)
    return success_response(serialize_child_auxiliary(record), status=201)


@bp.route("/child-auxiliaries/<child_id>/entitle", methods=["POST"])
@with_auth("DDS_Examiner", "PlatformAdmin")
def entitle(caller, child_id: str):
    record = service.entitle_child(child_id)
    return success_response(serialize_child_auxiliary(record))


@bp.route("/child-auxiliaries/<child_id>/terminate", methods=["POST"])
@with_auth("DDS_Examiner", "PlatformAdmin")
def terminate(caller, child_id: str):
    body = get_json_body()
    record = service.terminate_child(child_id, body)
    return success_response(serialize_child_auxiliary(record))


@bp.route("/child-auxiliaries", methods=["GET"])
@with_auth("Claimant", "DDS_Examiner", "PlatformAdmin")
def list_children(caller):
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    rows = service.list_children(application_id, status)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serialize_child_auxiliary(r) for r in page],
        limit=limit,
        offset=offset,
        total=total,
    )
