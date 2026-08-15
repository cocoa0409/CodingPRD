"""Bypass event ingestion (PRD 3.5). Immutable audit records computed by the
decision engine; the (vehicle, station, approach_at) triple is unique."""
from datetime import timedelta

from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import body_json, ctx, list_response, need_str, opt_bool, opt_int, require_role
from response import ok
from services.decision import evaluate_event
from util import fmt_ts, parse_datetime

bp = Blueprint("events", __name__)

CREDENTIAL_SETS = ("IFTA", "IRP", "UCR", "HOS_LOG")
STALE_WINDOW = timedelta(hours=48)


@bp.post("/api/bypass-events")
def create_event():
    _uid, role = ctx()
    require_role(role, ("TelematicsGateway",))
    body = body_json()
    vid = body.get("vehicle_id")
    sid = body.get("station_id")
    # Rung 4: existence, resource-type order — station before vehicle (PRD 2.10)
    station = store.stations.get(sid) if isinstance(sid, str) else None
    if isinstance(sid, str) and station is None:
        raise ApiError("ERR_STATION_NOT_FOUND", 404, "station id does not exist")
    vehicle = store.vehicles.get(vid) if isinstance(vid, str) else None
    if isinstance(vid, str) and vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "vehicle id does not exist")
    # Rung 9: feed timeliness bounds (future first, then stale)
    ap = parse_datetime(body.get("approach_at"))
    if ap is not None:
        now = db.now()
        if ap > now:
            raise ApiError(
                "ERR_FUTURE_APPROACH", 400, "approach_at is after the logical now"
            )
        if ap < now - STALE_WINDOW:
            raise ApiError(
                "ERR_STALE_APPROACH",
                422,
                "approach_at is older than the 48h late-arriving limit",
            )
    # Rung 12: fields
    vid = need_str(body, "vehicle_id")
    sid = need_str(body, "station_id")
    if ap is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "approach_at must be an ISO-8601 timestamp"
        )
    measured = opt_int(body, "measured_weight_lbs")
    creds = body.get("credentials_presented", [])
    if not isinstance(creds, list) or any(
        not isinstance(x, str) or x not in CREDENTIAL_SETS for x in creds
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "credentials_presented must be a list drawn from IFTA, IRP, UCR, HOS_LOG",
        )
    hazmat = opt_bool(body, "hazmat_load", False)
    # Rung 13: feed idempotency on the (vehicle, station, approach_at) triple
    for e in store.events.values():
        if (
            e["vehicle_id"] == vid
            and e["station_id"] == sid
            and e["_approach_dt"] == ap
        ):
            raise ApiError(
                "ERR_DUPLICATE_BYPASS_EVENT", 409, "approach triple already recorded"
            )
    carrier = store.carriers.get(vehicle["carrier_id"])
    config = store.configs.get(station["state_program_config_id"])
    result = evaluate_event(
        vehicle, station, config, carrier, ap, measured, creds, hazmat
    )
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "vehicle_id": vid,
        "station_id": sid,
        "carrier_id": vehicle["carrier_id"],
        "approach_at": fmt_ts(ap),
        "_approach_dt": ap,
        "measured_weight_lbs": measured,
        "credentials_presented": list(creds),
        "hazmat_load": hazmat,
        **result,
    }
    db.stamp_feed(rec)
    store.events[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/bypass-events")
def list_events():
    return list_response(
        store.events.values(),
        [
            ("carrier_id", "carrier_id"),
            ("vehicle_id", "vehicle_id"),
            ("station_id", "station_id"),
            ("decision", "decision"),
        ],
    )


@bp.get("/api/bypass-events/<eventId>")
def get_event(eventId):
    ctx()
    ev = store.events.get(eventId)
    if ev is None:
        raise ApiError("ERR_BYPASS_EVENT_NOT_FOUND", 404, "bypass event id does not exist")
    return ok(db.public(ev), 200)
