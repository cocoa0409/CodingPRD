"""Voc Rehab routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import ApiError
from ..serializers import serialize_voc_rehab_plan
from ..services.voc_rehab import (
    approve_plan,
    complete_plan,
    create_plan,
    resume_plan,
    start_plan,
    suspend_plan,
)
from ._common import get_json_body, get_store, respond_object

bp = Blueprint("voc_rehab", __name__)


@bp.route("/voc-rehab-plans", methods=["POST"])
@require_auth(["Counselor"])
def post_plan():
    body = get_json_body()
    store = get_store()
    with store.lock:
        p = create_plan(store, body)
    return respond_object(serialize_voc_rehab_plan(p), status=201)


@bp.route("/voc-rehab-plans/<pid>", methods=["GET"])
@require_auth(["Veteran", "Counselor", "PlatformAdmin"])
def get_plan(pid: str):
    store = get_store()
    p = store.voc_rehab_plans.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
    if g.user_role == "Veteran" and g.user_id != p["veteran_id"]:
        raise ApiError("ERR_FORBIDDEN", "veteran can only read own plan")
    return respond_object(serialize_voc_rehab_plan(p))


@bp.route("/voc-rehab-plans/<pid>/approve", methods=["POST"])
@require_auth(["Counselor"])
def post_approve(pid: str):
    store = get_store()
    with store.lock:
        if pid not in store.voc_rehab_plans:
            raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
        p = approve_plan(store, pid, counselor_id=g.user_id)
    return respond_object(serialize_voc_rehab_plan(p))


@bp.route("/voc-rehab-plans/<pid>/start", methods=["POST"])
@require_auth(["Counselor"])
def post_start(pid: str):
    store = get_store()
    with store.lock:
        if pid not in store.voc_rehab_plans:
            raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
        p = start_plan(store, pid)
    return respond_object(serialize_voc_rehab_plan(p))


@bp.route("/voc-rehab-plans/<pid>/suspend", methods=["POST"])
@require_auth(["Counselor"])
def post_suspend(pid: str):
    store = get_store()
    with store.lock:
        if pid not in store.voc_rehab_plans:
            raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
        p = suspend_plan(store, pid)
    return respond_object(serialize_voc_rehab_plan(p))


@bp.route("/voc-rehab-plans/<pid>/resume", methods=["POST"])
@require_auth(["Counselor"])
def post_resume(pid: str):
    store = get_store()
    with store.lock:
        if pid not in store.voc_rehab_plans:
            raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
        p = resume_plan(store, pid, counselor_id=g.user_id)
    return respond_object(serialize_voc_rehab_plan(p))


@bp.route("/voc-rehab-plans/<pid>/complete", methods=["POST"])
@require_auth(["Counselor"])
def post_complete(pid: str):
    store = get_store()
    with store.lock:
        if pid not in store.voc_rehab_plans:
            raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
        p = complete_plan(store, pid)
    return respond_object(serialize_voc_rehab_plan(p))
