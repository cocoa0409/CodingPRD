"""Dependent routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..errors import ApiError
from ..serializers import serialize_dependent
from ..services.dependents import create_dependent, remove_dependent, update_dependent
from ._common import get_json_body, get_store, respond_object

bp = Blueprint("dependents", __name__)


@bp.route("/dependents", methods=["POST"])
@require_auth(["VAClerk", "PlatformAdmin"])
def post_dependent():
    body = get_json_body()
    store = get_store()
    with store.lock:
        d = create_dependent(store, body)
    return respond_object(serialize_dependent(d), status=201)


@bp.route("/dependents/<did>", methods=["PATCH"])
@require_auth(["VAClerk", "PlatformAdmin"])
def patch_dependent(did: str):
    body = get_json_body()
    store = get_store()
    with store.lock:
        if did not in store.dependents:
            raise ApiError("ERR_NOT_FOUND", "dependent not found")
        d = update_dependent(store, did, body)
    return respond_object(serialize_dependent(d))


@bp.route("/dependents/<did>", methods=["DELETE"])
@require_auth(["VAClerk", "PlatformAdmin"])
def delete_dependent(did: str):
    store = get_store()
    with store.lock:
        if did not in store.dependents:
            raise ApiError("ERR_NOT_FOUND", "dependent not found")
        d = remove_dependent(store, did)
    return respond_object(serialize_dependent(d))
