from decimal import Decimal

from flask import Blueprint, request

from auth import parse_auth, require_role, check_ownership
from db import store
from envelope import ok, paginate
from errors import (not_found, invalid_request, conflict, ApiError,
                    ERR_STALE_ASSET_VERSION, ERR_TELEMETRY_WINDOW_CLOSED)
from routes.generators import get_generator
from routes.operating_days import get_day
from util import (get_body, check_unknown, req_string, req_int, new_record,
                  serialize, sort_key, touch, to_decimal)

bp = Blueprint("telemetry", __name__)


def get_telemetry(tid):
    t = store.telemetry.get(tid)
    if t is None:
        raise not_found("telemetry row not found")
    return t


@bp.post("/market/generators/<generatorId>/telemetry")
def submit_telemetry(generatorId):
    auth = parse_auth()
    require_role(auth, ["Trader"])
    body = get_body()
    check_unknown(body, {"operating_day_id", "readings", "expected_generator_asset_version"})
    day_id = req_string(body, "operating_day_id")
    readings = body.get("readings")
    if not isinstance(readings, list) or len(readings) == 0:
        raise invalid_request("readings must be a non-empty list")
    parsed = []
    for r in readings:
        if not isinstance(r, dict):
            raise invalid_request("each reading must be an object")
        check_unknown(r, {"interval_index", "actual_mw"})
        idx = r.get("interval_index")
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 1 or idx > 24:
            raise invalid_request("interval_index must be an integer in 1..24")
        actual = to_decimal(r.get("actual_mw"))
        if actual is None or actual < 0:
            raise invalid_request("actual_mw must be a non-negative number")
        parsed.append((idx, actual))
    expected = req_int(body, "expected_generator_asset_version")

    gen = get_generator(generatorId)
    day = get_day(day_id)
    check_ownership(auth, gen["market_participant_id"])
    if expected != gen["version"]:
        raise ApiError(ERR_STALE_ASSET_VERSION, 412,
                       "expected_generator_asset_version does not match the generator version")
    if day["status"] != "DA_GATED":
        raise conflict(ERR_TELEMETRY_WINDOW_CLOSED,
                       "telemetry is accepted only while the day is DA_GATED")

    telemetry_ids = []
    for idx, actual in parsed:
        # supersede the prior RECORDED row for this (generator, day, interval)
        for t in store.telemetry.values():
            if (t["generator_asset_id"] == gen["id"]
                    and t["operating_day_id"] == day["id"]
                    and t["interval_index"] == idx
                    and t["status"] == "RECORDED"):
                t["status"] = "SUPERSEDED"
                touch(t)
        rec = new_record()
        rec.update({
            "generator_asset_id": gen["id"],
            "operating_day_id": day["id"],
            "interval_index": idx,
            "actual_mw": actual,
            "status": "RECORDED",
        })
        store.telemetry[rec["id"]] = rec
        telemetry_ids.append(rec["id"])
    touch(gen)  # one version bump per batch
    return ok({"recorded_count": len(telemetry_ids), "telemetry_ids": telemetry_ids},
              status=201)


@bp.get("/market/telemetry/<telemetryId>")
def get_one(telemetryId):
    parse_auth()
    return ok(serialize(get_telemetry(telemetryId)))


@bp.get("/market/telemetry")
def list_telemetry():
    parse_auth()
    rows = sorted(store.telemetry.values(), key=sort_key)
    gen_id = request.args.get("generator_asset_id")
    day_id = request.args.get("operating_day_id")
    interval = request.args.get("interval_index")
    if gen_id is not None:
        rows = [r for r in rows if r["generator_asset_id"] == gen_id]
    if day_id is not None:
        rows = [r for r in rows if r["operating_day_id"] == day_id]
    if interval is not None:
        try:
            interval_int = int(interval)
            rows = [r for r in rows if r["interval_index"] == interval_int]
        except (TypeError, ValueError):
            rows = []
    return paginate([serialize(r) for r in rows])
