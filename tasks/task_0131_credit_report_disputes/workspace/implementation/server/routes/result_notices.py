"""ResultNotice retrieval."""
from __future__ import annotations

from flask import Blueprint

from ..auth import enforce_consumer_ownership, require_auth
from ..errors import ApiError
from ..responses import json_object
from ..store import store


bp_result_notices = Blueprint("result_notices", __name__)


@bp_result_notices.route(
    "/consumers/<consumer_id>/disputes/<dispute_id>/result_notice", methods=["GET"]
)
@require_auth(["Consumer", "BureauOperator", "PlatformAdmin"])
def get_result_notice(consumer_id: str, dispute_id: str):
    enforce_consumer_ownership(consumer_id)
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    dispute = store.disputes.get(dispute_id)
    if dispute is None or dispute["consumer_id"] != consumer_id:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found.", 404)
    notice_id = dispute.get("result_notice_id")
    if not notice_id:
        raise ApiError("ERR_NOT_FOUND", "ResultNotice has not been issued.", 404)
    notice = store.result_notices.get(notice_id)
    if notice is None:
        raise ApiError("ERR_NOT_FOUND", "ResultNotice not found.", 404)
    return json_object(notice, 200)
