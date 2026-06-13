"""DryAgeLocker: create, fetch, temp-readings (quarantine cascade), release
(PRD §3.3, §2.7, §2.9)."""
from flask import request

import db
import errors
import response
import serializers
import validation as v
from middleware import authenticate, require_role
from routes._helpers import list_response
from services import common


def register(app):
    @app.route("/dry-age-lockers", methods=["POST"])
    def create_locker():
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        body = v.get_body()
        name = v.as_str(v.require(body, "name"), "name")
        capacity = v.as_int(v.require(body, "capacity_g"), "capacity_g", minimum=1)
        min_temp = v.as_number(v.require(body, "min_temp_c"), "min_temp_c")
        max_temp = v.as_number(v.require(body, "max_temp_c"), "max_temp_c")
        if max_temp < min_temp:
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "max_temp_c must be >= min_temp_c.")
        # name uniqueness (PRD §3.2)
        for lk in db.dry_age_lockers.values():
            if lk["name"] == name:
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "Locker name must be unique: %s" % name)

        record = {
            "name": name,
            "capacity_g": capacity,
            "occupied_g": 0,
            "min_temp_c": min_temp,
            "max_temp_c": max_temp,
            "locker_status": "OPERATIONAL",
            "last_excursion_at": None,
        }
        db.stamp_create(record)
        db.dry_age_lockers[record["id"]] = record
        return response.object_response(serializers.dry_age_locker(record), 201)

    @app.route("/dry-age-lockers/<rid>", methods=["GET"])
    def get_locker(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager", "SafetyOfficer"})
        record = common.get_or_404(db.dry_age_lockers, rid)
        return response.object_response(serializers.dry_age_locker(record))

    @app.route("/dry-age-lockers/<rid>/temp-readings", methods=["POST"])
    def create_temp_reading(rid):
        _uid, role = authenticate()
        require_role(role, {"SafetyOfficer"})
        locker = common.get_or_404(db.dry_age_lockers, rid)
        body = v.get_body()
        temp_c = v.as_number(v.require(body, "temp_c"), "temp_c")
        reading_at_raw = v.require(body, "reading_at")
        common.parse_iso(reading_at_raw, "reading_at")  # validate format

        in_band = locker["min_temp_c"] <= temp_c <= locker["max_temp_c"]
        triggered = False
        # Out-of-band reading drives the cascade (PRD §3.3).
        if not in_band and locker["locker_status"] == "OPERATIONAL":
            locker["locker_status"] = "QUARANTINED"
            locker["last_excursion_at"] = reading_at_raw
            db.touch(locker)
            triggered = True
            # Cascade hop 2: AGING lots in this locker -> ON_HOLD.
            for lot in db.inventory_lots.values():
                if lot.get("locker_id") == locker["id"] and \
                        lot["lot_status"] == "AGING":
                    lot["lot_status"] = "ON_HOLD"
                    db.touch(lot)

        reading = {
            "locker_id": locker["id"],
            "temp_c": temp_c,
            "reading_at": reading_at_raw,
            "in_band": in_band,
            "triggered_quarantine": triggered,
        }
        db.stamp_create(reading, with_version=False)  # append-only log
        db.temp_readings[reading["id"]] = reading
        return response.object_response(serializers.temp_reading(reading), 201)

    @app.route("/dry-age-lockers/<rid>/temp-readings", methods=["GET"])
    def list_temp_readings(rid):
        _uid, role = authenticate()
        require_role(role, {"SafetyOfficer", "ShiftManager", "Butcher"})
        common.get_or_404(db.dry_age_lockers, rid)
        records = [t for t in db.temp_readings.values()
                   if t["locker_id"] == rid]
        in_band = request.args.get("in_band")
        if in_band is not None:
            want = in_band.lower() in ("true", "1")
            records = [r for r in records if r["in_band"] == want]
        return list_response(records, request.args, serializers.temp_reading)

    @app.route("/dry-age-lockers/<rid>/release", methods=["POST"])
    def release_locker(rid):
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        locker = common.get_or_404(db.dry_age_lockers, rid)
        body = v.get_body()
        expected = v.as_int(
            v.require(body, "expected_dry_age_locker_version"),
            "expected_dry_age_locker_version")

        if locker["locker_status"] != "QUARANTINED":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Locker is not QUARANTINED; cannot release.")
        # OCC check (PRD §2.9) -> ERR_STALE_LOCKER_VERSION.
        if expected != locker["version"]:
            errors.fail(errors.ERR_STALE_LOCKER_VERSION,
                        "Stale locker version.")

        locker["locker_status"] = "OPERATIONAL"
        db.touch(locker)  # increment version by one (PRD §3.3)
        # Release cascade: ON_HOLD lots in this locker -> AGING (preserve
        # aging_started_at).
        for lot in db.inventory_lots.values():
            if lot.get("locker_id") == locker["id"] and \
                    lot["lot_status"] == "ON_HOLD":
                lot["lot_status"] = "AGING"
                db.touch(lot)
        return response.object_response(serializers.dry_age_locker(locker))
