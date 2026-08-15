"""Event entries: creation (eligibility gauntlet), payment, withdrawal, and
technical inspections driving the entry tech state machine."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_EVENT_REGISTRATION_CLOSED,
    ERR_DRIVER_NOT_ACTIVE,
    ERR_KART_UNAVAILABLE,
    ERR_CLASS_MISMATCH,
    ERR_RENTAL_NOT_ALLOWED,
    ERR_KART_CLASS_INELIGIBLE,
    ERR_DUPLICATE_ENTRY,
    ERR_FORBIDDEN,
)
from middleware import authorized, check_driver_ownership, ANY_ROLE
from response import success_object, success_array, success_list
from services import core
from services.cascades import disqualify_entry
from util import age_years_at, parse_datetime, parse_date, weight_outcome
from validate import json_body, v_id, v_enum, v_num, v_str

bp = Blueprint("entries", __name__)

ENTRY_TYPES = {"RENTAL", "OWNER_DRIVER"}


@bp.post("/events/<event_id>/entries")
def create_entry(event_id):
    caller = authorized(["LeagueAdmin", "Driver"])
    body = json_body()
    # priority 2 (ownership): a Driver may enter only themselves. Checked as
    # soon as the body's driver_id is readable, ahead of full body validation.
    raw_driver = body.get("driver_id")
    if caller.role == "Driver" and isinstance(raw_driver, str) and raw_driver != caller.user_id:
        raise_error(ERR_FORBIDDEN, "a Driver may only create their own entries")
    # priority 3: body well-formedness
    driver_id = v_id(body, "driver_id")
    class_id = v_id(body, "class_id")
    entry_type = v_enum(body, "entry_type", ENTRY_TYPES)
    kart_id = body.get("kart_id")
    if entry_type == "RENTAL":
        if kart_id is None or not isinstance(kart_id, str):
            raise_error(ERR_INVALID_REQUEST, "RENTAL entry requires kart_id")
    else:  # OWNER_DRIVER
        if kart_id is not None:
            raise_error(ERR_INVALID_REQUEST, "OWNER_DRIVER entry must omit kart_id")

    # priority 4: existence and parent scope (path left-to-right, then FKs)
    event = core.must_find("events", event_id, "event not found")
    driver = core.must_find("drivers", driver_id, "driver not found")
    race_class = core.find("classes", class_id)
    if race_class is None or race_class["season_id"] != event["season_id"]:
        raise_error(ERR_NOT_FOUND, "class not found in the event's season")
    kart = None
    if entry_type == "RENTAL":
        kart = core.must_find("karts", kart_id, "kart not found")

    # priority 6: state preconditions
    if event["status"] != "REGISTRATION_OPEN":
        raise_error(ERR_EVENT_REGISTRATION_CLOSED, "event registration is not open")
    if driver["status"] != "ACTIVE":
        raise_error(ERR_DRIVER_NOT_ACTIVE, "driver is not ACTIVE")
    if kart is not None and kart["status"] != "AVAILABLE":
        raise_error(ERR_KART_UNAVAILABLE, "kart is not AVAILABLE")

    # priority 7: class & equipment eligibility
    event_dt = parse_datetime(event["event_date"])
    dob = parse_date(driver["date_of_birth"])
    age = age_years_at(dob, event_dt) if (event_dt and dob) else -1
    if not (race_class["min_age"] <= age <= race_class["max_age"]):
        raise_error(ERR_CLASS_MISMATCH, "driver age is outside the class window")
    if driver["license_type"] == "RENTAL" and entry_type != "RENTAL":
        raise_error(ERR_CLASS_MISMATCH, "RENTAL-licensed drivers may only file RENTAL entries")
    if entry_type == "OWNER_DRIVER" and driver["license_type"] != "OWNER":
        raise_error(ERR_CLASS_MISMATCH, "OWNER_DRIVER entry requires an OWNER license")
    if entry_type == "RENTAL" and not race_class["rental_kart_allowed"]:
        raise_error(ERR_RENTAL_NOT_ALLOWED, "class does not permit rental entries")
    if kart is not None and race_class["code"] not in kart["eligible_class_codes"]:
        raise_error(ERR_KART_CLASS_INELIGIBLE, "kart is not eligible for this class")

    # priority 9: uniqueness
    for en in core.db["entries"].values():
        if en["event_id"] != event["id"] or en["status"] == "WITHDRAWN":
            continue
        if en["driver_id"] == driver["id"]:
            raise_error(ERR_DUPLICATE_ENTRY, "driver already has a non-WITHDRAWN entry in the event")
        if kart is not None and en.get("kart_id") == kart["id"]:
            raise_error(ERR_KART_UNAVAILABLE, "kart already assigned to an entry of this event")

    entry = core.create_record("entries", {
        "event_id": event["id"],
        "driver_id": driver["id"],
        "class_id": race_class["id"],
        "entry_type": entry_type,
        "kart_id": kart["id"] if kart else None,
        "status": "ENTERED",
        "entry_fee_cents": race_class["entry_fee_cents"],  # snapshot (PRD 2.9)
        "fee_status": "UNPAID",
    })
    return success_object(core.serialize_entry(entry), 201)


@bp.get("/events/<event_id>/entries")
def list_event_entries(event_id):
    authorized(ANY_ROLE)
    event = core.must_find("events", event_id, "event not found")
    items = [en for en in core.db["entries"].values() if en["event_id"] == event["id"]]
    items = core.list_sorted(items)
    page, total, limit, offset = core.paginate(items)
    return success_list([core.serialize_entry(en) for en in page], total, limit, offset)


@bp.get("/entries/<entry_id>")
def get_entry(entry_id):
    authorized(ANY_ROLE)
    entry = core.must_find("entries", entry_id, "entry not found")
    return success_object(core.serialize_entry(entry))


@bp.get("/entries")
def list_entries():
    authorized(ANY_ROLE)
    driver_id = request.args.get("driver_id")
    class_id = request.args.get("class_id")
    kart_id = request.args.get("kart_id")
    items = list(core.db["entries"].values())
    if driver_id is not None:
        items = [en for en in items if en["driver_id"] == driver_id]
    if class_id is not None:
        items = [en for en in items if en["class_id"] == class_id]
    if kart_id is not None:
        items = [en for en in items if en.get("kart_id") == kart_id]
    items = core.list_sorted(items)
    page, total, limit, offset = core.paginate(items)
    return success_list([core.serialize_entry(en) for en in page], total, limit, offset)


@bp.post("/entries/<entry_id>/pay")
def pay_entry(entry_id):
    caller = authorized(["LeagueAdmin", "Driver"])
    entry = core.find("entries", entry_id)
    if entry is not None:
        check_driver_ownership(caller, entry["driver_id"])
    if entry is None:
        raise_error(ERR_NOT_FOUND, "entry not found")
    if entry["fee_status"] != "UNPAID":
        raise_error(ERR_INVALID_STATE, "entry fee is not UNPAID")
    entry["fee_status"] = "PAID"
    core.touch(entry)
    return success_object(core.serialize_entry(entry))


@bp.post("/entries/<entry_id>/withdraw")
def withdraw_entry(entry_id):
    caller = authorized(["LeagueAdmin", "Driver"])
    entry = core.find("entries", entry_id)
    if entry is not None:
        check_driver_ownership(caller, entry["driver_id"])
    if entry is None:
        raise_error(ERR_NOT_FOUND, "entry not found")
    if entry["status"] not in ("ENTERED", "TECH_CHECK", "TECH_FAILED", "TECH_PASSED"):
        raise_error(ERR_INVALID_STATE, "entry cannot withdraw from its current state")
    entry["status"] = "WITHDRAWN"
    if entry["fee_status"] == "PAID":
        entry["fee_status"] = "REFUNDED"
    core.touch(entry)
    return success_object(core.serialize_entry(entry))


# --- technical inspections ------------------------------------------------------

@bp.post("/entries/<entry_id>/inspections")
def create_inspection(entry_id):
    caller = authorized(["RaceDirector"])
    body = json_body()
    measured = v_num(body, "measured_combined_weight_kg", gt=0)
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise_error(ERR_INVALID_REQUEST, "notes must be a string")
    entry = core.must_find("entries", entry_id, "entry not found")
    if entry["status"] not in ("ENTERED", "TECH_FAILED", "TECH_PASSED", "GRID_LOCKED"):
        raise_error(ERR_INVALID_STATE, "entry cannot be inspected in its current state")

    race_class = core.db["classes"].get(entry["class_id"])
    outcome = weight_outcome(measured, race_class["min_combined_weight_kg"]) if race_class else "FAIL"
    inspection = core.create_record("inspections", {
        "entry_id": entry["id"],
        "measured_combined_weight_kg": measured,
        "outcome": outcome,
        "inspector_user_id": caller.user_id,
        "notes": notes,
    }, common=False)

    # entry tech state machine: into TECH_CHECK, immediately resolved by outcome
    prior = entry["status"]
    if outcome == "PASS":
        entry["status"] = "TECH_PASSED"
        core.touch(entry)
    else:
        fail_count = core.entry_tech_fail_count(entry)  # includes this inspection
        if prior == "GRID_LOCKED" or fail_count >= core.TECH_FAIL_DISQUALIFY_THRESHOLD:
            # post-race weight failure, or threshold reached: disqualify outright
            disqualify_entry(entry)
        else:
            entry["status"] = "TECH_FAILED"
            core.touch(entry)
    return success_object(core.serialize_inspection(inspection), 201)


@bp.get("/entries/<entry_id>/inspections")
def list_inspections(entry_id):
    authorized(ANY_ROLE)
    entry = core.must_find("entries", entry_id, "entry not found")
    items = [i for i in core.db["inspections"].values() if i["entry_id"] == entry["id"]]
    return success_array([core.serialize_inspection(i) for i in core.list_sorted(items)])
