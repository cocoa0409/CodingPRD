"""Temperature reading endpoints (PRD 3.2): ingestion recomputes the bin's
risk score from the latest reading by recorded_at, raises hotspot alerts, and
fires the posture recompute."""
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services import core
from util import (as_bool, as_decimal, as_dt, as_str, body, paginate_sorted,
                  query_str, required, resolve_body_fk, resolve_path)

bp = Blueprint("readings", __name__)


@bp.route("/grain/temperature-readings", methods=["POST"])
def create_reading():
    require_roles("SiteManager")
    data = body()
    # existence (4)
    bin_rec = resolve_body_fk(db.bins, data, "bin_id", "bin")
    # shape (6)
    bin_id = as_str(required(data, "bin_id"), "bin_id")
    recorded_at = as_dt(required(data, "recorded_at"), "recorded_at")
    ambient = core.q1(as_decimal(required(data, "ambient_temp_f"), "ambient_temp_f"))
    if ambient < Decimal("-40") or ambient > Decimal("140"):
        raise ApiError("ERR_VALIDATION", 400,
                       "ambient_temp_f must be between -40 and 140 inclusive")
    raw_cables = required(data, "cable_temps_f")
    if not isinstance(raw_cables, list):
        raise ApiError("ERR_VALIDATION", 400, "cable_temps_f must be an array")
    if len(raw_cables) < 1 or len(raw_cables) > 12:
        raise ApiError("ERR_VALIDATION", 400,
                       "cable_temps_f must have between 1 and 12 entries")
    cables = [core.q1(as_decimal(v, "cable_temps_f")) for v in raw_cables]
    insect = as_bool(required(data, "insect_activity"), "insect_activity")

    max_cable = max(cables)
    delta = core.q1(max_cable - ambient)
    hotspot = (delta >= core.HOTSPOT_DELTA_F) or (max_cable >= core.HOTSPOT_ABS_F)

    rec = core.new_event()
    rec.update({
        "bin_id": bin_id,
        "recorded_at": recorded_at,
        "ambient_temp_f": ambient,
        "cable_temps_f": cables,
        "insect_activity": insect,
        "max_cable_temp_f": max_cable,
        "temp_delta_f": delta,
        "hotspot_triggered": hotspot,
        "score_after": Decimal("0.00"),
    })
    db.readings[rec["id"]] = rec

    # Recompute from the bin's latest reading by recorded_at (out-of-order safe).
    snap = core.bin_snap(bin_rec)
    score = core.recompute_risk(bin_rec)
    rec["score_after"] = score

    if hotspot:
        alert = core.new_common()
        alert.update({
            "bin_id": bin_id,
            "reading_id": rec["id"],
            "source": "AUTO_HOTSPOT",
            "status": "OPEN",
            "loss_bu": None,
            "closed_at": None,
        })
        db.alerts[alert["id"]] = alert

    core.recompute_posture(bin_rec)
    core.finalize_bin(bin_rec, snap)
    return ok(core.reading_view(rec), 201)


@bp.route("/grain/temperature-readings/<rid>", methods=["GET"])
def get_reading(rid):
    require_roles(*ALL_ROLES)
    return ok(core.reading_view(resolve_path(db.readings, rid, "reading")))


@bp.route("/grain/temperature-readings", methods=["GET"])
def list_readings():
    require_roles(*ALL_ROLES)
    f_bin = query_str("bin_id")
    items = list(db.readings.values())
    if f_bin is not None:
        items = [r for r in items if r["bin_id"] == f_bin]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.reading_view(r) for r in page], total, limit, offset)
