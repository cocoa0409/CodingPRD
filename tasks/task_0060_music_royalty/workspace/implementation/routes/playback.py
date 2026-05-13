"""Playback routes."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response, list_response
from services import playback as svc

bp = Blueprint("playback", __name__)


@bp.route("/playback-batches", methods=["POST"])
def ingest():
    require_role("PlaybackSource")
    body = request.get_json(silent=True) or {}
    data = svc.ingest_batch(body)
    return success_response(data, status_code=201)


@bp.route("/playback-batches/<batch_id>", methods=["GET"])
def get(batch_id):
    require_role("PlatformAdmin", "FinanceOps", "PlaybackSource")
    data = svc.get_batch(batch_id)
    return success_response(data)


@bp.route("/playback-batches/<batch_id>/events", methods=["GET"])
def list_events(batch_id):
    require_role("PlatformAdmin", "FinanceOps")
    items, total, limit, offset = svc.list_batch_events(batch_id, request.args)
    return list_response(items, total, limit, offset)
