"""ScoreReport read routes + ScoreSend routes."""
from flask import Blueprint, request

from db import store, stamp_create
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles
from response import object_response, array_response
from services import lookups, serializers
from services.common import (get_json_body, require_fields, parse_pagination,
                             paginate, sort_by_created_at)

bp = Blueprint("scores", __name__)


# ---------------------------------------------------------------------------
# ScoreReport reads
# ---------------------------------------------------------------------------
@bp.route("/score-reports/<srid>", methods=["GET"])
@require_roles("Candidate", "ScoreOps")
def get_score_report(srid):
    sr = lookups.score_report(srid)
    return object_response(serializers.score_report(sr), 200)


@bp.route("/score-reports", methods=["GET"])
@require_roles("Candidate", "ScoreOps")
def list_score_reports():
    limit, offset = parse_pagination()
    registration_id = request.args.get("registration_id")
    candidate_id = request.args.get("candidate_id")

    items = list(store.score_reports.values())
    if registration_id is not None:
        items = [s for s in items if s["registration_id"] == registration_id]
    if candidate_id is not None:
        items = [s for s in items if s["candidate_id"] == candidate_id]

    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.score_report(s) for s in page],
                          limit, offset, total, 200)


# ---------------------------------------------------------------------------
# ScoreSend
# ---------------------------------------------------------------------------
@bp.route("/score-sends", methods=["POST"])
@require_roles("Candidate")
def create_score_send():
    body = get_json_body()
    require_fields(body, ["registration_id", "recipient_code"])

    reg = lookups.registration(body["registration_id"])

    recipient_code = body["recipient_code"]
    if not isinstance(recipient_code, str):
        raise err(ERR_INVALID_REQUEST, "recipient_code must be a string")

    use_super = body.get("use_super_score", False)
    if use_super is None:
        use_super = False
    if not isinstance(use_super, bool):
        raise err(ERR_INVALID_REQUEST, "use_super_score must be a boolean")

    # Requires Registration.score_status == RELEASED (cross-entity dependency).
    if reg["score_status"] != "RELEASED":
        raise err(ERR_INVALID_STATE, "Registration score has not been RELEASED")

    # Freeze the composite at send time.
    sr = _score_report_for_reg(reg["id"])
    if use_super:
        sent_composite = sr["super_composite"] if sr else None
    else:
        sent_composite = sr["sitting_composite"] if sr else None

    send = {
        "registration_id": reg["id"],
        "recipient_code": recipient_code,
        "use_super_score": use_super,
        "sent_composite": sent_composite,
        "status": "QUEUED",
    }
    stamp_create(send)
    store.score_sends[send["id"]] = send
    return object_response(serializers.score_send(send), 201)


def _score_report_for_reg(registration_id):
    for sr in store.score_reports.values():
        if sr["registration_id"] == registration_id:
            return sr
    return None
