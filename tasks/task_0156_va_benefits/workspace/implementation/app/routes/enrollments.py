"""Enrollment routes."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..errors import ApiError
from ..serializers import (
    serialize_enrollment,
    serialize_housing_payment,
    serialize_yellow_ribbon,
)
from ..services.enrollments import (
    cancel_enrollment,
    certify_enrollment,
    complete_enrollment,
    post_housing_payment,
    submit_enrollment,
    update_enrollment,
    withdraw_enrollment,
)
from ..util import paginate, parse_pagination
from ._common import get_json_body, get_store, respond_array, respond_object

bp = Blueprint("enrollments", __name__)


def _owner_check(store, enrollment_id: str) -> dict:
    e = store.enrollments.get(enrollment_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "enrollment not found")
    if g.user_role == "Veteran" and g.user_id != e["veteran_id"]:
        raise ApiError("ERR_FORBIDDEN", "veteran can only access own enrollment")
    return e


@bp.route("/enrollments", methods=["POST"])
@require_auth(["Veteran", "VAClerk"])
def post_enrollment():
    body = get_json_body()
    store = get_store()
    with store.lock:
        e = submit_enrollment(store, body, caller_id=g.user_id, caller_role=g.user_role)
    return respond_object(serialize_enrollment(e), status=201)


@bp.route("/enrollments/<eid>", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "PlatformAdmin"])
def get_enrollment(eid: str):
    store = get_store()
    e = _owner_check(store, eid)
    return respond_object(serialize_enrollment(e))


@bp.route("/enrollments/<eid>", methods=["PATCH"])
@require_auth(["VAClerk", "PlatformAdmin"])
def patch_enrollment(eid: str):
    body = get_json_body()
    store = get_store()
    with store.lock:
        if eid not in store.enrollments:
            raise ApiError("ERR_NOT_FOUND", "enrollment not found")
        e = update_enrollment(store, eid, body)
    return respond_object(serialize_enrollment(e))


@bp.route("/enrollments/<eid>/certify", methods=["POST"])
@require_auth(["VAClerk"])
def post_certify(eid: str):
    store = get_store()
    with store.lock:
        if eid not in store.enrollments:
            raise ApiError("ERR_NOT_FOUND", "enrollment not found")
        e = certify_enrollment(store, eid)
    return respond_object(serialize_enrollment(e))


@bp.route("/enrollments/<eid>/cancel", methods=["POST"])
@require_auth(["VAClerk"])
def post_cancel(eid: str):
    store = get_store()
    with store.lock:
        if eid not in store.enrollments:
            raise ApiError("ERR_NOT_FOUND", "enrollment not found")
        e = cancel_enrollment(store, eid)
    return respond_object(serialize_enrollment(e))


@bp.route("/enrollments/<eid>/complete", methods=["POST"])
@require_auth(["VAClerk"])
def post_complete(eid: str):
    store = get_store()
    with store.lock:
        if eid not in store.enrollments:
            raise ApiError("ERR_NOT_FOUND", "enrollment not found")
        e = complete_enrollment(store, eid)
    return respond_object(serialize_enrollment(e))


@bp.route("/enrollments/<eid>/withdraw", methods=["POST"])
@require_auth(["Veteran"])
def post_withdraw(eid: str):
    store = get_store()
    with store.lock:
        if eid not in store.enrollments:
            raise ApiError("ERR_NOT_FOUND", "enrollment not found")
        e = withdraw_enrollment(store, eid, caller_id=g.user_id)
    return respond_object(serialize_enrollment(e))


@bp.route("/enrollments/<eid>/housing-payments", methods=["POST"])
@require_auth(["VAClerk"])
def post_housing(eid: str):
    body = get_json_body()
    store = get_store()
    with store.lock:
        if eid not in store.enrollments:
            raise ApiError("ERR_NOT_FOUND", "enrollment not found")
        hp = post_housing_payment(store, eid, body)
    return respond_object(serialize_housing_payment(hp), status=201)


@bp.route("/enrollments/<eid>/housing-payments", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "PlatformAdmin"])
def list_housing(eid: str):
    store = get_store()
    e = _owner_check(store, eid)
    limit, offset = parse_pagination(request.args)
    items = [h for h in store.housing_payments.values() if h["enrollment_id"] == eid]
    items.sort(key=lambda h: h["created_at"])
    page, total = paginate(items, limit, offset)
    return respond_array(
        [serialize_housing_payment(h) for h in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


@bp.route("/enrollments/<eid>/yellow-ribbon", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "PlatformAdmin"])
def get_yr(eid: str):
    store = get_store()
    e = _owner_check(store, eid)
    yr = None
    for cand in store.yellow_ribbon_contributions.values():
        if cand["enrollment_id"] == eid:
            yr = cand
            break
    if yr is None:
        raise ApiError("ERR_NOT_FOUND", "no yellow ribbon contribution for this enrollment")
    return respond_object(serialize_yellow_ribbon(yr))
