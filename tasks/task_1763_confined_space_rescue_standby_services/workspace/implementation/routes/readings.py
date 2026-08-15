"""Atmospheric readings, the continuous log, and the alarm cascade (PRD 3.6)."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_READING_KIND_NOT_ALLOWED, ERR_READING_NOT_FOUND,
    ERR_READING_OUT_OF_RANGE, raise_error,
)
from helpers import (
    body, iso_z, list_response, now_dt, reject_unknown, req_enum, req_number,
    stamp_append_only, stamp_new,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.permits import get_permit
from services import emergency_suspend, recompute_entry_exposure

bp = Blueprint("readings", __name__)

READING_KINDS = ("PRE_ENTRY", "CONTINUOUS")

# Plausibility ranges (inclusive): o2 0-30, lel 0-100, h2s 0-500, co 0-2000.
RANGES = (("o2_pct", 0.0, 30.0), ("lel_pct", 0.0, 100.0),
          ("h2s_ppm", 0.0, 500.0), ("co_ppm", 0.0, 2000.0))


def get_reading(reading_id):
    r = db.atmospheric_readings.get(reading_id)
    if r is None:
        raise_error(ERR_READING_NOT_FOUND, "Atmospheric reading not found")
    return r


@bp.route("/rescue-ops/entry-permits/<permit_id>/atmospheric-readings", methods=["POST"])
def create_reading(permit_id):
    user_id, _, _ = require_auth(("Attendant",))
    permit = get_permit(permit_id)
    data = body()
    reject_unknown(data, {"reading_kind", "o2_pct", "lel_pct", "h2s_ppm", "co_ppm"})
    reading_kind = req_enum(data, "reading_kind", READING_KINDS)
    values = {field: req_number(data, field) for field, _, _ in RANGES}
    # State gate (priority 7): kind allowed in the permit's current state
    allowed_states = ("ISSUED", "SUSPENDED") if reading_kind == "PRE_ENTRY" else ("ACTIVE",)
    if permit["status"] not in allowed_states:
        raise_error(ERR_READING_KIND_NOT_ALLOWED,
                    f"{reading_kind} readings are not allowed while the permit is {permit['status']}")
    # Plausibility gate (priority 8)
    for field, low, high in RANGES:
        value = values[field]
        if value < low or value > high:
            raise_error(ERR_READING_OUT_OF_RANGE,
                        f"Field '{field}' outside plausibility range {low}..{high}")
    o2, lel, h2s, co = values["o2_pct"], values["lel_pct"], values["h2s_ppm"], values["co_ppm"]
    within_limits = (19.5 <= o2 <= 23.5) and lel <= 10 and h2s <= 10 and co <= 35
    now = now_dt()
    reading = {
        "permit_id": permit["id"],
        "recorded_by": user_id,
        "reading_kind": reading_kind,
        "o2_pct": o2,
        "lel_pct": lel,
        "h2s_ppm": h2s,
        "co_ppm": co,
        "recorded_at": iso_z(now),
        "within_limits": within_limits,
    }
    stamp_append_only(reading)
    db.atmospheric_readings[reading["id"]] = reading
    if reading_kind == "CONTINUOUS":
        # Exposure recompute for every ON_DUTY entry of the permit (may
        # auto-relieve entries whose class becomes EXCEEDANCE).
        for entry in list(db.roster_entries.values()):
            if entry["permit_id"] == permit["id"] and entry["status"] == "ON_DUTY":
                recompute_entry_exposure(entry, now)
        if not within_limits and permit["status"] == "ACTIVE":
            # Alarm cascade: suspend, evacuate, deploy, auto-create incident.
            emergency_suspend(permit, now)
            critical = (o2 < 16 or o2 > 25 or lel >= 25 or h2s >= 20 or co >= 100)
            incident = {
                "permit_id": permit["id"],
                "reported_by": user_id,
                "severity": "CRITICAL" if critical else "SERIOUS",
                "kind": "ATMOSPHERE",
                "description": "Automatic alarm: out-of-limits CONTINUOUS reading",
                "triaged_by": None,
                "resolved_by": None,
                "resolution_notes": None,
                "escalation_level": 0,
                "status": "REPORTED",
            }
            from helpers import stamp_new as _stamp_new
            _stamp_new(incident)
            db.incidents[incident["id"]] = incident
    return success_object(serializers.atmospheric_reading(reading), 201)


@bp.route("/rescue-ops/atmospheric-readings", methods=["GET"])
def list_readings():
    require_auth(ALL_ROLES)
    return list_response(list(db.atmospheric_readings.values()),
                         serializers.atmospheric_reading, {
                             "permit_id": request.args.get("permit_id"),
                             "reading_kind": request.args.get("reading_kind"),
                             "within_limits": request.args.get("within_limits"),
                             "recorded_by": request.args.get("recorded_by"),
                         })


@bp.route("/rescue-ops/atmospheric-readings/<reading_id>", methods=["GET"])
def get_one_reading(reading_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.atmospheric_reading(get_reading(reading_id)))
