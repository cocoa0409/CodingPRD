"""Test-only system clock endpoints."""

from datetime import timedelta
from flask import Blueprint

from db import db, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success
from util import get_json_body, require_nonempty_str


bp = Blueprint("system_clock", __name__)


def _maybe_advance_deferred():
    """When the clock advances, fire deferred system transitions:
      - SUBMITTED Applications whose applied_at + 30d <= current_utc -> EXPIRED;
        household -> TERMINATED
      - ACTIVE EmergencyAllotmentProclamations whose benefit_month has fully passed -> EXPIRED
    """
    now_dt = db.current_utc_dt()
    now_iso = db.current_utc_iso()

    # Applications: SUBMITTED -> EXPIRED at applied_at + 30d
    for a in db.applications.values():
        if a["status"] != "SUBMITTED":
            continue
        if not a.get("applied_at"):
            continue
        applied_dt = parse_iso(a["applied_at"])
        if now_dt >= applied_dt + timedelta(days=30):
            a["status"] = "EXPIRED"
            a["updated_at"] = now_iso
            a["version"] = int(a.get("version", 1)) + 1
            hh = db.households.get(a["household_id"])
            if hh is not None:
                hh["status"] = "TERMINATED"
                hh["updated_at"] = now_iso
                hh["version"] = int(hh.get("version", 1)) + 1

    # Proclamations: ACTIVE -> EXPIRED once current_utc is past end of benefit_month
    current_month = now_iso[:7]
    for p in db.emergency_proclamations.values():
        if p["status"] != "ACTIVE":
            continue
        # "past the end of benefit_month": current_month > p['benefit_month']
        if current_month > p["benefit_month"]:
            p["status"] = "EXPIRED"
            p["updated_at"] = now_iso
            p["version"] = int(p.get("version", 1)) + 1


@bp.route("/snap/_clock/set_current_utc", methods=["POST"])
@require_roles("PolicyAdmin")
def set_clock(**_):
    body = get_json_body()
    iso_value = require_nonempty_str(body, "to_iso8601")
    try:
        snapshot = db.clock_set(iso_value)
    except ValueError as e:
        raise_api("ERR_INVALID_REQUEST", str(e))
    _maybe_advance_deferred()
    return success(snapshot)


@bp.route("/snap/_clock", methods=["GET"])
@require_roles("PolicyAdmin", "Caseworker", "BenefitIssuer", "FraudInvestigator")
def get_clock(**_):
    return success(db.clock_get())
