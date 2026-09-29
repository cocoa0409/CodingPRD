"""Ice-bed readings and cold-chain excursions (PRD 3.7)."""

import calc
import serializers
import services
from auth import counter_scope
from common import base_record, touch
from envelope import obj_result
from errors import fail
from store import db
from validators import opt_id, opt_str, req_datetime, req_enum, req_int, req_number, req_str
from web import listing, route

COLD_ROLES = ("ChainAdmin", "SeafoodManager", "ComplianceOfficer")
RESOLUTIONS = ("RELEASE", "DISPOSE")


# --------------------------------------------------------------------------
# ice-bed readings
# --------------------------------------------------------------------------

@route("/ice-bed-readings", methods=["POST"], roles=("SeafoodManager",))
def submit_reading(body):
    raw_counter = opt_id(body, "counter_id")
    counter_scope(raw_counter)

    counter = None
    if raw_counter is not None:
        counter = db.counters.get(raw_counter)
        if counter is None:
            fail("ERR_COUNTER_NOT_FOUND")

    counter_id = req_str(body, "counter_id")
    case_slot = req_int(body, "case_slot")
    reading_at = req_datetime(body, "reading_at")
    temperature_c = req_number(body, "temperature_c", 1)
    taken_by_user_id = req_str(body, "taken_by_user_id")

    if counter["posture"] == "SUSPENDED":
        fail("ERR_COUNTER_SUSPENDED")
    if case_slot < 1 or case_slot > counter["case_slot_count"]:
        fail("ERR_CASE_SLOT_OUT_OF_RANGE")
    if reading_at > db.clock:
        fail("ERR_READING_IN_FUTURE")

    record = base_record("reading", versioned=False)
    record.update(
        {
            "counter_id": counter_id,
            "case_slot": case_slot,
            "reading_at": reading_at,
            "temperature_c": temperature_c,
            "taken_by_user_id": taken_by_user_id,
            "breach": temperature_c > calc.ICE_BED_LIMIT_C,
        }
    )
    db.readings[record["id"]] = record

    services.replay_slot_exposure(counter, case_slot)
    return obj_result(serializers.reading, record, 201)


@route("/ice-bed-readings/<reading_id>", methods=["GET"], roles=COLD_ROLES)
def get_reading(body, reading_id):
    record = db.readings.get(reading_id)
    if record is not None:
        counter_scope(record["counter_id"])
    else:
        fail("ERR_READING_NOT_FOUND")
    return obj_result(serializers.reading, record)


@route("/ice-bed-readings", methods=["GET"], roles=COLD_ROLES)
def list_readings(body):
    return listing(
        serializers.reading,
        list(db.readings.values()),
        string_fields=("counter_id",),
        int_fields=("case_slot",),
        bool_fields=("breach",),
    )


# --------------------------------------------------------------------------
# excursions
# --------------------------------------------------------------------------

@route("/excursions/<excursion_id>", methods=["GET"], roles=COLD_ROLES)
def get_excursion(body, excursion_id):
    record = db.excursions.get(excursion_id)
    if record is None:
        fail("ERR_EXCURSION_NOT_FOUND")
    return obj_result(serializers.excursion, record)


@route("/excursions", methods=["GET"], roles=COLD_ROLES)
def list_excursions(body):
    return listing(
        serializers.excursion,
        list(db.excursions.values()),
        string_fields=("counter_id", "status", "severity"),
        int_fields=("case_slot",),
    )


@route("/excursions/<excursion_id>/resolve", methods=["POST"], roles=("ComplianceOfficer",))
def resolve_excursion(body, excursion_id):
    excursion = db.excursions.get(excursion_id)
    if excursion is None:
        fail("ERR_EXCURSION_NOT_FOUND")

    resolution = req_enum(body, "resolution", RESOLUTIONS)
    note = opt_str(body, "note")

    if excursion["status"] != "OPEN":
        fail("ERR_EXCURSION_STATE_INVALID")
    if resolution == "RELEASE" and excursion["severity"] not in ("MINOR", "MAJOR"):
        fail("ERR_EXCURSION_STATE_INVALID")

    counter = db.counters.get(excursion["counter_id"])
    excursion["resolution"] = resolution
    excursion["resolution_note"] = note
    excursion["status"] = "RESOLVED_RELEASED" if resolution == "RELEASE" else "RESOLVED_DISPOSED"
    touch(excursion)

    if resolution == "RELEASE":
        services.release_slot_lots(counter, excursion["case_slot"])
    else:
        services.dispose_slot_lots(counter, excursion["case_slot"])
    services.derive_posture(counter)
    return obj_result(serializers.excursion, excursion)
