"""Consumer routes: create, get, risk."""
from __future__ import annotations

import re

from flask import Blueprint

from ..auth import enforce_consumer_ownership, require_auth
from ..calculations import compute_dispute_risk_score
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create, store
from ..utils import parse_json_body, require_field


bp_consumers = Blueprint("consumers", __name__)


def _validate_consumer_create(body: dict) -> tuple[str, str, str]:
    full_name = require_field(body, "full_name", types=[str])
    ssn_last4 = require_field(body, "ssn_last4", types=[str])
    email = require_field(body, "email", types=[str])
    if not full_name.strip():
        raise ApiError("ERR_INVALID_REQUEST", "full_name must be non-empty.", 400)
    if not re.fullmatch(r"\d{4}", ssn_last4):
        raise ApiError("ERR_INVALID_REQUEST", "ssn_last4 must be exactly 4 digits.", 400)
    if "@" not in email or not email.strip():
        raise ApiError("ERR_INVALID_REQUEST", "email must be a valid address.", 400)
    return full_name, ssn_last4, email


@bp_consumers.route("/consumers", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_consumer():
    body = parse_json_body()
    full_name, ssn_last4, email = _validate_consumer_create(body)
    with store.lock:
        for existing in store.consumers.values():
            if existing["email"] == email:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "email must be unique across all consumers.",
                    400,
                )
        consumer = stamp_create(
            {
                "full_name": full_name,
                "ssn_last4": ssn_last4,
                "email": email,
                "free_reports_remaining": 1,
                "freeze_pin": None,
            }
        )
        store.consumers[consumer["id"]] = consumer
    return json_object(consumer, 201)


@bp_consumers.route("/consumers/<consumer_id>", methods=["GET"])
@require_auth(["Consumer", "PlatformAdmin"])
def get_consumer(consumer_id: str):
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    enforce_consumer_ownership(consumer_id)
    return json_object(consumer, 200)


@bp_consumers.route("/consumers/<consumer_id>/risk", methods=["GET"])
@require_auth(["Consumer", "PlatformAdmin"])
def get_consumer_risk(consumer_id: str):
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    enforce_consumer_ownership(consumer_id)
    # PRD §3.6: 'The final variant is computed on each subsequent
    # transition of the now-committed dispute and is what surfaces on
    # the consumer-risk retrieval endpoint.' The 'dispute in question'
    # for has_supporting_docs is the most recently committed dispute
    # for the consumer.
    latest_dispute = None
    for d in store.disputes.values():
        if d["consumer_id"] != consumer_id:
            continue
        if latest_dispute is None or d.get("submitted_day", 0) > latest_dispute.get("submitted_day", 0):
            latest_dispute = d
        elif d.get("submitted_day", 0) == latest_dispute.get("submitted_day", 0):
            # Tie-break by created_at if available, else by id.
            if d.get("created_at", "") > latest_dispute.get("created_at", ""):
                latest_dispute = d
    has_supporting_docs = bool(
        latest_dispute and latest_dispute.get("supporting_documents")
    )
    risk = compute_dispute_risk_score(
        consumer_id, has_supporting_docs=has_supporting_docs,
    )
    return json_object({"consumer_id": consumer_id, "dispute_risk_score": risk}, 200)
