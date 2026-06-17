"""Zones, Stages, ParkingLots, CampingAreas, Performances."""
from flask import request
from db import db, insert, touch
from errors import err
from response import ok_object, ok_array
import serialize as S
from common import (
    body, pagination, paginate, find, auth,
    as_str, as_int, as_number,
)
from datetime import datetime


def _parse_instant(s, field):
    """Parse an ISO 8601 instant into an aware/naive-comparable datetime."""
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field)
    try:
        txt = s.replace("Z", "+00:00")
        return datetime.fromisoformat(txt)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "%s must be a valid ISO 8601 instant" % field)


def register(app):

    # ===================== Zones =====================
    @app.route("/festivals/<fid>/zones", methods=["POST"])
    def create_zone(fid):
        auth(["FestivalDirector"])
        fest = find(db.festivals, fid)
        data = body()
        code = as_str(data, "code")
        if code not in ("A", "B", "C"):
            raise err("ERR_INVALID_REQUEST", "code must be one of A, B, C")
        slot_capacity = as_int(data, "slot_capacity")
        if slot_capacity < 1:
            raise err("ERR_INVALID_REQUEST", "slot_capacity must be >= 1")
        rec = insert(db.zones, {
            "festival_id": fid,
            "code": code,
            "slot_capacity": slot_capacity,
            "allocated_count": 0,
        })
        return ok_object(S.zone(rec), 201)

    @app.route("/festivals/<fid>/zones", methods=["GET"])
    def list_zones(fid):
        auth(["FestivalDirector", "VendorManager", "Vendor"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [z for z in db.zones.values() if z["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.zone(r) for r in page], limit, offset, total)

    @app.route("/zones/<zid>", methods=["GET"])
    def get_zone(zid):
        auth(["FestivalDirector", "VendorManager", "Vendor"])
        return ok_object(S.zone(find(db.zones, zid)))

    # ===================== Stages =====================
    @app.route("/festivals/<fid>/stages", methods=["POST"])
    def create_stage(fid):
        auth(["FestivalDirector"])
        find(db.festivals, fid)
        data = body()
        name = as_str(data, "name")
        changeover = as_int(data, "changeover_minutes", required=False)
        if changeover is None:
            changeover = 30
        if changeover < 0:
            raise err("ERR_INVALID_REQUEST", "changeover_minutes must be >= 0")
        rec = insert(db.stages, {
            "festival_id": fid,
            "name": name,
            "changeover_minutes": changeover,
        })
        return ok_object(S.stage(rec), 201)

    @app.route("/festivals/<fid>/stages", methods=["GET"])
    def list_stages(fid):
        auth(["FestivalDirector", "VendorManager", "GateAttendant"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [s for s in db.stages.values() if s["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.stage(r) for r in page], limit, offset, total)

    @app.route("/stages/<sid>", methods=["GET"])
    def get_stage(sid):
        auth(["FestivalDirector", "VendorManager"])
        return ok_object(S.stage(find(db.stages, sid)))

    # ===================== Parking Lots =====================
    @app.route("/festivals/<fid>/parking-lots", methods=["POST"])
    def create_parking_lot(fid):
        auth(["FestivalDirector"])
        find(db.festivals, fid)
        data = body()
        name = as_str(data, "name")
        capacity = as_int(data, "capacity")
        if capacity < 1:
            raise err("ERR_INVALID_REQUEST", "capacity must be >= 1")
        price = as_number(data, "price_per_pass")
        rec = insert(db.parking_lots, {
            "festival_id": fid,
            "name": name,
            "capacity": capacity,
            "sold_count": 0,
            "price_per_pass": price,
        })
        return ok_object(S.parking_lot(rec), 201)

    @app.route("/festivals/<fid>/parking-lots", methods=["GET"])
    def list_parking_lots(fid):
        auth(["FestivalDirector", "BoxOffice"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [p for p in db.parking_lots.values() if p["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.parking_lot(r) for r in page], limit, offset, total)

    @app.route("/parking-lots/<pid>", methods=["GET"])
    def get_parking_lot(pid):
        auth(["FestivalDirector", "BoxOffice"])
        return ok_object(S.parking_lot(find(db.parking_lots, pid)))

    # ===================== Camping Areas =====================
    @app.route("/festivals/<fid>/camping-areas", methods=["POST"])
    def create_camping_area(fid):
        auth(["FestivalDirector"])
        find(db.festivals, fid)
        data = body()
        name = as_str(data, "name")
        capacity = as_int(data, "capacity")
        if capacity < 1:
            raise err("ERR_INVALID_REQUEST", "capacity must be >= 1")
        price = as_number(data, "price_per_night")
        rec = insert(db.camping_areas, {
            "festival_id": fid,
            "name": name,
            "capacity": capacity,
            "sold_count": 0,
            "price_per_night": price,
        })
        return ok_object(S.camping_area(rec), 201)

    @app.route("/festivals/<fid>/camping-areas", methods=["GET"])
    def list_camping_areas(fid):
        auth(["FestivalDirector", "BoxOffice"])
        find(db.festivals, fid)
        limit, offset = pagination()
        rows = [c for c in db.camping_areas.values() if c["festival_id"] == fid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.camping_area(r) for r in page], limit, offset, total)

    @app.route("/camping-areas/<cid>", methods=["GET"])
    def get_camping_area(cid):
        auth(["FestivalDirector", "BoxOffice"])
        return ok_object(S.camping_area(find(db.camping_areas, cid)))

    # ===================== Performances =====================
    @app.route("/stages/<sid>/performances", methods=["POST"])
    def create_performance(sid):
        auth(["FestivalDirector"])
        stage = find(db.stages, sid)
        fid = stage["festival_id"]
        data = body()
        artist_name = as_str(data, "artist_name")
        starts_raw = as_str(data, "starts_at")
        ends_raw = as_str(data, "ends_at")
        starts_dt = _parse_instant(starts_raw, "starts_at")
        ends_dt = _parse_instant(ends_raw, "ends_at")

        changeover = stage["changeover_minutes"]
        buffer = changeover * 60  # seconds

        # Priority 12: per-stage conflict (buffered, half-open)
        for p in db.performances.values():
            if p["stage_id"] != sid or p["status"] != "SCHEDULED":
                continue
            e_start = _parse_instant(p["starts_at"], "starts_at")
            e_end = _parse_instant(p["ends_at"], "ends_at")
            # reject when starts_at < existing.ends_at + buffer
            #   AND ends_at + buffer > existing.starts_at
            if (starts_dt < _add_seconds(e_end, buffer) and
                    _add_seconds(ends_dt, buffer) > e_start):
                raise err("ERR_STAGE_CONFLICT",
                          "performance collides with another on this stage")

        # Priority 13: artist double-booking festival-wide (no buffer, half-open;
        # exact adjacency allowed)
        for p in db.performances.values():
            if p["festival_id"] != fid or p["status"] != "SCHEDULED":
                continue
            if p["artist_name"] != artist_name:
                continue
            e_start = _parse_instant(p["starts_at"], "starts_at")
            e_end = _parse_instant(p["ends_at"], "ends_at")
            if starts_dt < e_end and ends_dt > e_start:
                raise err("ERR_ARTIST_DOUBLE_BOOKED",
                          "artist already booked over this interval")

        # Priority 14: well-formed interval
        if not (ends_dt > starts_dt):
            raise err("ERR_INVALID_INTERVAL", "ends_at must be after starts_at")

        rec = insert(db.performances, {
            "stage_id": sid,
            "festival_id": fid,
            "artist_name": artist_name,
            "starts_at": starts_raw,
            "ends_at": ends_raw,
            "status": "SCHEDULED",
        })
        return ok_object(S.performance(rec), 201)

    @app.route("/stages/<sid>/performances", methods=["GET"])
    def list_stage_performances(sid):
        auth(["FestivalDirector", "GateAttendant"])
        find(db.stages, sid)
        limit, offset = pagination()
        rows = [p for p in db.performances.values() if p["stage_id"] == sid]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.performance(r) for r in page], limit, offset, total)

    @app.route("/performances", methods=["GET"])
    def list_performances():
        auth(["FestivalDirector", "GateAttendant"])
        limit, offset = pagination()
        fest_id = request.args.get("festival_id")
        rows = list(db.performances.values())
        if fest_id is not None:
            rows = [p for p in rows if p["festival_id"] == fest_id]
        page, total = paginate(rows, limit, offset)
        return ok_array([S.performance(r) for r in page], limit, offset, total)

    @app.route("/performances/<pid>", methods=["GET"])
    def get_performance(pid):
        auth(["FestivalDirector", "GateAttendant"])
        return ok_object(S.performance(find(db.performances, pid)))


def _add_seconds(dt, seconds):
    from datetime import timedelta
    return dt + timedelta(seconds=seconds)
