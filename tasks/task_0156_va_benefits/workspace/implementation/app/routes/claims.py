"""Claim routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import ApiError
from ..serializers import serialize_claim
from ..services.claims import (
    appeal_claim,
    deny_claim,
    file_claim,
    grant_claim,
    reopen_claim,
    start_review,
)
from ._common import get_json_body, get_store, respond_object

bp = Blueprint("claims", __name__)


@bp.route("/claims", methods=["POST"])
@require_auth(["Veteran", "VAClerk"])
def post_claim():
    body = get_json_body()
    store = get_store()
    with store.lock:
        c = file_claim(store, body, caller_id=g.user_id, caller_role=g.user_role)
    return respond_object(serialize_claim(c), status=201)


@bp.route("/claims/<cid>", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "Rater", "PlatformAdmin"])
def get_claim(cid: str):
    store = get_store()
    c = store.claims.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "claim not found")
    if g.user_role == "Veteran" and g.user_id != c["veteran_id"]:
        raise ApiError("ERR_FORBIDDEN", "veteran can only read own claim")
    return respond_object(serialize_claim(c))


@bp.route("/claims/<cid>/start-review", methods=["POST"])
@require_auth(["Rater"])
def post_start_review(cid: str):
    store = get_store()
    with store.lock:
        if cid not in store.claims:
            raise ApiError("ERR_NOT_FOUND", "claim not found")
        c = start_review(store, cid, rater_id=g.user_id)
    return respond_object(serialize_claim(c))


@bp.route("/claims/<cid>/grant", methods=["POST"])
@require_auth(["Rater"])
def post_grant(cid: str):
    body = get_json_body()
    store = get_store()
    with store.lock:
        if cid not in store.claims:
            raise ApiError("ERR_NOT_FOUND", "claim not found")
        c = grant_claim(store, cid, body, rater_id=g.user_id)
    return respond_object(serialize_claim(c))


@bp.route("/claims/<cid>/deny", methods=["POST"])
@require_auth(["Rater"])
def post_deny(cid: str):
    store = get_store()
    with store.lock:
        if cid not in store.claims:
            raise ApiError("ERR_NOT_FOUND", "claim not found")
        c = deny_claim(store, cid, rater_id=g.user_id)
    return respond_object(serialize_claim(c))


@bp.route("/claims/<cid>/appeal", methods=["POST"])
@require_auth(["Veteran"])
def post_appeal(cid: str):
    store = get_store()
    with store.lock:
        if cid not in store.claims:
            raise ApiError("ERR_NOT_FOUND", "claim not found")
        c = appeal_claim(store, cid, caller_id=g.user_id)
    return respond_object(serialize_claim(c))


@bp.route("/claims/<cid>/reopen", methods=["POST"])
@require_auth(["Rater"])
def post_reopen(cid: str):
    store = get_store()
    with store.lock:
        if cid not in store.claims:
            raise ApiError("ERR_NOT_FOUND", "claim not found")
        c = reopen_claim(store, cid, rater_id=g.user_id)
    return respond_object(serialize_claim(c))
