"""Exceedance endpoints (notification dimension)."""

from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_EXCEEDANCE_NOT_FOUND,
    ERR_INVALID_NOTIFICATION_STATE,
    ERR_EXCEEDANCE_NOT_CLOSABLE,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields
from services.core import (
    touch,
    append_audit,
    serialize_exceedance,
    paginate,
    recompute_permit_rollup,
    permit_for_exceedance,
)

bp = Blueprint("exceedances", __name__)


@bp.route("/npdes/exceedances", methods=["GET"])
def list_exceedances():
    require_roles(["Any"])
    items = list(db.exceedances.values())
    for param in ("outfall_id", "lab_result_id", "effluent_limit_id", "corrective_action_id", "notification_status"):
        v = request.args.get(param)
        if v:
            items = [e for e in items if e.get(param) == v]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_exceedance(e) for e in page], total, limit, offset)


@bp.route("/npdes/exceedances/<eid>", methods=["GET"])
def get_exceedance(eid):
    require_roles(["Any"])
    exc = db.exceedances.get(eid)
    if exc is None:
        raise err(ERR_EXCEEDANCE_NOT_FOUND, 404, "Exceedance not found")
    return success(serialize_exceedance(exc), 200)


@bp.route("/npdes/exceedances/<eid>/notify", methods=["POST"])
def notify_exceedance(eid):
    user_id, role = require_roles(["ComplianceOfficer"])
    exc = db.exceedances.get(eid)
    if exc is None:
        raise err(ERR_EXCEEDANCE_NOT_FOUND, 404, "Exceedance not found")
    if exc["notification_status"] not in ("PENDING_ORAL", "ORAL_OVERDUE"):
        raise err(ERR_INVALID_NOTIFICATION_STATE, 409, "Notify requires PENDING_ORAL or ORAL_OVERDUE")
    exc["notification_status"] = "ORAL_NOTIFIED"
    exc["oral_notified_at"] = db.clock.now()
    touch(exc)
    append_audit("Exceedance", exc["id"], "EXCEEDANCE_ORAL_NOTIFIED", user_id, role)
    return success(serialize_exceedance(exc), 200)


@bp.route("/npdes/exceedances/<eid>/file-report", methods=["POST"])
def file_report(eid):
    user_id, role = require_roles(["ComplianceOfficer"])
    exc = db.exceedances.get(eid)
    if exc is None:
        raise err(ERR_EXCEEDANCE_NOT_FOUND, 404, "Exceedance not found")
    body = get_body()
    require_fields(body, ["report_summary"])
    if exc["notification_status"] not in ("ORAL_NOTIFIED", "WRITTEN_OVERDUE"):
        raise err(ERR_INVALID_NOTIFICATION_STATE, 409, "File-report requires ORAL_NOTIFIED or WRITTEN_OVERDUE")
    exc["notification_status"] = "WRITTEN_FILED"
    exc["written_filed_at"] = db.clock.now()
    touch(exc)
    append_audit("Exceedance", exc["id"], "EXCEEDANCE_WRITTEN_FILED", user_id, role)
    return success(serialize_exceedance(exc), 200)


@bp.route("/npdes/exceedances/<eid>/close", methods=["POST"])
def close_exceedance(eid):
    user_id, role = require_roles(["ComplianceOfficer"])
    exc = db.exceedances.get(eid)
    if exc is None:
        raise err(ERR_EXCEEDANCE_NOT_FOUND, 404, "Exceedance not found")
    if exc["notification_status"] != "WRITTEN_FILED":
        raise err(ERR_INVALID_NOTIFICATION_STATE, 409, "Close requires WRITTEN_FILED")
    ca = db.corrective_actions.get(exc.get("corrective_action_id") or "")
    if ca is None or ca["status"] not in ("VERIFIED", "CLOSED"):
        raise err(ERR_EXCEEDANCE_NOT_CLOSABLE, 409, "Linked corrective action is not VERIFIED or CLOSED")
    exc["notification_status"] = "CLOSED"
    touch(exc)
    permit = permit_for_exceedance(exc)
    if permit is not None:
        recompute_permit_rollup(permit["id"])
    append_audit("Exceedance", exc["id"], "EXCEEDANCE_CLOSED", user_id, role)
    return success(serialize_exceedance(exc), 200)
