"""Spoilage alert endpoints (PRD 3.2). Alerts are system-raised only; the
SiteManager closes them as RESOLVED or CONFIRMED_LOSS."""
from decimal import Decimal

from flask import Blueprint

import db
from clock import CLOCK
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services import core
from util import (as_bu, as_enum, body, paginate_sorted, present, query_enum,
                  query_str, required, resolve_path)

bp = Blueprint("alerts", __name__)


@bp.route("/grain/spoilage-alerts/<aid>", methods=["GET"])
def get_alert(aid):
    require_roles(*ALL_ROLES)
    return ok(core.alert_view(resolve_path(db.alerts, aid, "alert")))


@bp.route("/grain/spoilage-alerts", methods=["GET"])
def list_alerts():
    require_roles(*ALL_ROLES)
    f_bin = query_str("bin_id")
    f_reading = query_str("reading_id")
    f_status = query_enum("status", core.ALERT_STATUSES)
    items = list(db.alerts.values())
    if f_bin is not None:
        items = [a for a in items if a["bin_id"] == f_bin]
    if f_reading is not None:
        items = [a for a in items if a["reading_id"] == f_reading]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.alert_view(a) for a in page], total, limit, offset)


@bp.route("/grain/spoilage-alerts/<aid>/close", methods=["POST"])
def close_alert(aid):
    require_roles("SiteManager")
    # existence (4): path id
    alert = resolve_path(db.alerts, aid, "alert")
    # shape (6): conditional loss_bu fires before the state check
    data = body()
    outcome = as_enum(required(data, "outcome"), "outcome", core.ALERT_OUTCOMES)
    loss = None
    if outcome == "CONFIRMED_LOSS":
        if not present(data, "loss_bu"):
            raise ApiError("ERR_VALIDATION", 400,
                           "loss_bu is required when outcome is CONFIRMED_LOSS")
        loss = as_bu(data["loss_bu"], "loss_bu")
        if loss <= 0:
            raise ApiError("ERR_VALIDATION", 400, "loss_bu must be > 0")
    else:
        if present(data, "loss_bu"):
            raise ApiError("ERR_VALIDATION", 400,
                           "loss_bu is forbidden when outcome is RESOLVED")
    # state (9)
    if alert["status"] != "OPEN":
        raise ApiError("ERR_ALERT_NOT_OPEN", 409, "alert is not OPEN")

    alert["status"] = outcome
    alert["closed_at"] = CLOCK.now()
    alert["loss_bu"] = loss if outcome == "CONFIRMED_LOSS" else None
    core.touch(alert)

    bin_rec = db.bins.get(alert["bin_id"])
    if bin_rec is not None:
        snap = core.bin_snap(bin_rec)
        core.recompute_posture(bin_rec)
        core.finalize_bin(bin_rec, snap)
    return ok(core.alert_view(alert))
