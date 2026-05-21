"""Application routes including determinations + appeals."""

from __future__ import annotations

from flask import Blueprint

from app.auth import Caller
from app.envelope import list_response, success_response
from app.errors import forbidden
from app.routes._helpers import (
    assert_claimant_self_access,
    fetch_application_under_claimant,
    fetch_claimant,
    get_json_body,
    paginate,
    parse_pagination,
    with_auth,
)
from app.serializers import serialize_application, serialize_determination
from app.services import applications as service


bp = Blueprint("applications", __name__)


@bp.route("/claimants/<claimant_id>/applications", methods=["POST"])
@with_auth("Claimant")
def create_application(caller, claimant_id: str):
    assert_claimant_self_access(caller, claimant_id)
    record = service.create_application(claimant_id)
    return success_response(serialize_application(record), status=201)


@bp.route("/claimants/<claimant_id>/applications/<app_id>/submit", methods=["POST"])
@with_auth("Claimant")
def submit_application(caller, claimant_id: str, app_id: str):
    assert_claimant_self_access(caller, claimant_id)
    record = service.submit_application(claimant_id, app_id)
    return success_response(serialize_application(record))


@bp.route("/claimants/<claimant_id>/applications/<app_id>/determinations", methods=["POST"])
@with_auth("DDS_Examiner", "ALJ", "AppealsCouncil")
def post_determination(caller, claimant_id: str, app_id: str):
    body = get_json_body()
    # Existence check first (priority 5/6 per scaffold).
    fetch_claimant(claimant_id)
    fetch_application_under_claimant(claimant_id, app_id)
    record = service.post_determination(claimant_id, app_id, body, caller)
    return success_response(serialize_determination(record), status=201)


@bp.route("/claimants/<claimant_id>/applications/<app_id>/appeal", methods=["POST"])
@with_auth("Claimant")
def appeal(caller, claimant_id: str, app_id: str):
    assert_claimant_self_access(caller, claimant_id)
    body = get_json_body()
    record = service.appeal_application(claimant_id, app_id, body)
    return success_response(serialize_application(record))


@bp.route("/claimants/<claimant_id>/applications/<app_id>", methods=["GET"])
@with_auth("Claimant", "DDS_Examiner", "ALJ", "AppealsCouncil", "CDR_Reviewer", "PlatformAdmin")
def get_application(caller, claimant_id: str, app_id: str):
    assert_claimant_self_access(caller, claimant_id)
    record = service.get_application(claimant_id, app_id)
    return success_response(serialize_application(record))


@bp.route("/claimants/<claimant_id>/applications/<app_id>/determinations", methods=["GET"])
@with_auth("Claimant", "DDS_Examiner", "ALJ", "AppealsCouncil", "PlatformAdmin")
def list_determinations(caller, claimant_id: str, app_id: str):
    assert_claimant_self_access(caller, claimant_id)
    limit, offset = parse_pagination()
    rows = service.list_determinations(claimant_id, app_id)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serialize_determination(r) for r in page],
        limit=limit,
        offset=offset,
        total=total,
    )
