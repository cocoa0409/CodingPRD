"""Notice-of-intent endpoints."""
from flask import Blueprint

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object
from serializers import ser_notice
from services import core
from validation import get_body, req_string

bp = Blueprint("notices", __name__)


@bp.route("/enrollments/<enrollment_id>/notices", methods=["POST"])
@route(["Parent"], ownership=("enrollment", "enrollment_id"),
       parent_chain=(("enrollment", "enrollment_id", db.enrollments),))
def create_notice(enrollment_id):
    body = get_body()
    district_code = req_string(body, "district_code")
    for n in db.notices.values():
        if n["enrollment_id"] == enrollment_id and n["status"] in ("DRAFT", "FILED", "RETURNED"):
            raise_err("ERR_NOTICE_ALREADY_OPEN",
                      "Enrollment already has a notice in DRAFT, FILED, or RETURNED")
    rec = core.make_record({
        "enrollment_id": enrollment_id,
        "district_code": district_code,
        "status": "DRAFT",
        "filed_at": None,
        "acknowledged_at": None,
        "returned_reason": None,
        "refile_count": 0,
    })
    db.notices[rec["id"]] = rec
    return success_object(ser_notice(rec), status=201)


@bp.route("/notices/<notice_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("notice", "notice_id"),
       parent_chain=(("notice", "notice_id", db.notices),))
def get_notice(notice_id):
    return success_object(ser_notice(db.notices[notice_id]))


@bp.route("/notices/<notice_id>/file", methods=["POST"])
@route(["Parent"], ownership=("notice", "notice_id"),
       parent_chain=(("notice", "notice_id", db.notices),))
def file_notice(notice_id):
    n = db.notices[notice_id]
    if n["status"] not in ("DRAFT", "RETURNED"):
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only DRAFT or RETURNED notices may be filed")
    if n["status"] == "RETURNED":
        n["refile_count"] += 1
        n["returned_reason"] = None
    n["status"] = "FILED"
    n["filed_at"] = clock.now_iso()
    core.touch(n)
    return success_object(ser_notice(n))


@bp.route("/notices/<notice_id>/acknowledge", methods=["POST"])
@route(["Registrar"], parent_chain=(("notice", "notice_id", db.notices),))
def acknowledge_notice(notice_id):
    n = db.notices[notice_id]
    if n["status"] != "FILED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only FILED notices may be acknowledged")
    n["status"] = "ACKNOWLEDGED"
    n["acknowledged_at"] = clock.now_iso()
    core.touch(n)
    return success_object(ser_notice(n))


@bp.route("/notices/<notice_id>/return", methods=["POST"])
@route(["Registrar"], parent_chain=(("notice", "notice_id", db.notices),))
def return_notice(notice_id):
    n = db.notices[notice_id]
    body = get_body()
    reason = req_string(body, "returned_reason")
    if n["status"] != "FILED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only FILED notices may be returned")
    n["status"] = "RETURNED"
    n["returned_reason"] = reason
    core.touch(n)
    return success_object(ser_notice(n))
