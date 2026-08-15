"""Escape report endpoints."""

from flask import Blueprint, request

from db import db, public, touch
from errors import (
    ApiError,
    ERR_ESCAPE_REPORT_NOT_FOUND,
    ERR_ESCAPE_WINDOW_EXCEEDED,
    ERR_INVALID_STATE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from validate import json_body, no_unknown, paginate, req_str

bp = Blueprint("escapes", __name__)

QM = "QualityManager"
CQR = "CustomerQualityRep"


def get_escape(er_id):
    e = db.escape_reports.get(er_id)
    if e is None:
        raise ApiError(ERR_ESCAPE_REPORT_NOT_FOUND, 404, "Escape report %s not found" % er_id)
    return e


@bp.route("/api/escape-reports", methods=["GET"])
def list_escapes():
    require_roles(*ALL_ROLES)
    items = list(db.escape_reports.values())
    ncr_id = request.args.get("ncr_id")
    status = request.args.get("status")
    if ncr_id is not None:
        items = [e for e in items if e["ncr_id"] == ncr_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/escape-reports/<erId>", methods=["GET"])
def get_one_escape(erId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_escape(erId)))


@bp.route("/api/escape-reports/<erId>/submit", methods=["POST"])
def submit_escape(erId):
    require_roles(QM)
    data = json_body()
    no_unknown(data, set())
    er = get_escape(erId)
    if er["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Escape submit requires DRAFT")
    # 48-hour window; the due_at boundary is inclusive
    if db.now() > er["_due_dt"]:
        raise ApiError(ERR_ESCAPE_WINDOW_EXCEEDED, 422, "Escape window has been exceeded")
    er["status"] = "SUBMITTED"
    er["submitted_at"] = db.now_iso()
    touch(er)
    return success_object(public(er))


@bp.route("/api/escape-reports/<erId>/acknowledge", methods=["POST"])
def acknowledge_escape(erId):
    require_roles(CQR)
    data = json_body()
    no_unknown(data, {"acknowledgement_reference"})
    req_str(data, "acknowledgement_reference")
    er = get_escape(erId)
    if er["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Escape acknowledge requires SUBMITTED")
    er["status"] = "ACKNOWLEDGED"
    touch(er)
    return success_object(public(er))
