"""Airports, hazard-preview, trends, training-compliance, logical clock."""
from datetime import timedelta
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, ALL_ROLES
from constants import ICAO_RE, HAZARD_LEVELS
from db import store
from services import window_counts, compute_level, species_seasonal_trend, training_compliance, tick
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, parse_datetime, now, fmt_dt)

bp = Blueprint("airports", __name__, url_prefix="/wildlife")

READ_ROLES = ALL_ROLES
ANALYST_ROLES = ("WildlifeBiologist", "AirportAdmin")


@bp.post("/airports")
def create_airport():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin",))
    data = validate_payload(body(), [
        ("icao_code", "pattern", True, {"regex": ICAO_RE}),
        ("name", "str", True),
        ("annual_plan_cycle_year", "int", True, {"min": 2000, "max": 2100}),
    ])
    for ap in store.airports.values():
        if ap["icao_code"] == data["icao_code"]:
            raise E.invalid_request("icao_code must be unique")
    rec = new_airport(data)
    return ok_object(_ser(rec), 201)


def new_airport(data):
    from util import new_entity
    return new_entity(store.airports, {
        "icao_code": data["icao_code"],
        "name": data["name"],
        "current_hazard_level": "LOW",
        "hazard_level_updated_at": None,
        "strikes_trailing_12m": 0,
        "strikes_trailing_12m_high_risk": 0,
        "annual_plan_cycle_year": data["annual_plan_cycle_year"],
    })


def _ser(rec):
    from util import serialize
    return serialize(rec)


@bp.get("/airports")
def list_airports():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    icao = request.args.get("icao_code")
    hazard = request.args.get("current_hazard_level")
    if hazard is not None and hazard not in HAZARD_LEVELS:
        raise E.invalid_enum("current_hazard_level", hazard)
    rows = [a for a in store.airports.values()
            if (icao is None or a["icao_code"] == icao)
            and (hazard is None or a["current_hazard_level"] == hazard)]
    return list_response(rows)


@bp.get("/airports/<rid>")
def get_airport(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(_ser(get_or_404(store.airports, rid, "airport")))


@bp.get("/airports/<rid>/hazard-preview")
def hazard_preview(rid):
    uid, role = authenticate()
    require_roles(role, ANALYST_ROLES)
    ap = get_or_404(store.airports, rid, "airport")
    raw = request.args.get("as_of")
    if raw is None:
        raise E.invalid_request("missing required query parameter: 'as_of'")
    try:
        as_of = parse_datetime(raw)
    except Exception:
        raise E.invalid_request("as_of must be an ISO8601 datetime")
    # prospective variant: exclusive window ending at as_of; nothing persisted.
    cnt, high = window_counts(ap["id"], as_of, inclusive=False, upper_bound=True)
    level = compute_level(ap["id"], cnt, high, as_of.date())
    return ok_object({
        "projected_hazard_level": level,
        "projected_strikes_trailing_12m": cnt,
        "projected_strikes_trailing_12m_high_risk": high,
    })


@bp.get("/airports/<rid>/trends/species-seasonal")
def trends(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent"))
    ap = get_or_404(store.airports, rid, "airport")
    raw = request.args.get("lookback_days")
    if raw is None:
        lookback = 365
    else:
        try:
            lookback = int(raw)
        except (TypeError, ValueError):
            raise E.invalid_request("lookback_days must be an integer")
        if lookback < 1:
            raise E.invalid_request("lookback_days must be >= 1")
    return ok_object({"rows": species_seasonal_trend(ap["id"], lookback)})


@bp.get("/airports/<rid>/training-compliance")
def compliance(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent"))
    ap = get_or_404(store.airports, rid, "airport")
    return ok_object(training_compliance(ap["id"]))


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin",))
    data = validate_payload(body(), [("to_iso8601", "datetime", True)])
    store.clock = data["to_iso8601"]
    tick()
    return ok_object({"current_utc": fmt_dt(store.clock)})
