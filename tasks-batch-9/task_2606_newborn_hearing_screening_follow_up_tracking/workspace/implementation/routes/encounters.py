"""Screening encounters: the pass / refer fork and the surveillance discharge."""
from flask import Blueprint, request

import calc
import db
import resolve
import response
import serialize
import services
import validate
from db import store
from errors import ApiError
from middleware import (ALL_ROLES, AUDIOLOGIST, FACILITY_SCREENER, endpoint,
                        identity)

bp = Blueprint("encounters", __name__)

ENCOUNTER_PROVIDER_TYPES = ("SCREENER", "AUDIOLOGIST")


@bp.post("/screening-encounters")
@endpoint([FACILITY_SCREENER, AUDIOLOGIST])
def create_encounter():
    body = validate.body()
    infant_id = validate.id_field(body, "infant_id")
    facility_id = validate.id_field(body, "facility_id")
    performed_by_provider_id = validate.id_field(body, "performed_by_provider_id")
    encounter_type = validate.enum_field(body, "encounter_type",
                                         validate.ENCOUNTER_TYPES)
    method = validate.enum_field(body, "method", validate.SCREEN_METHODS)
    performed_at = validate.datetime_field(body, "performed_at")
    left = validate.enum_field(body, "left_ear_result", validate.EAR_RESULTS)
    right = validate.enum_field(body, "right_ear_result", validate.EAR_RESULTS)
    episode_id = validate.id_field(body, "episode_id", required=False)
    appointment_id = validate.id_field(body, "appointment_id", required=False)
    prior_encounter_id = validate.id_field(body, "prior_encounter_id", required=False)

    linked = resolve.fks({
        "facility_id": facility_id,
        "performed_by_provider_id": performed_by_provider_id,
        "infant_id": infant_id,
        "episode_id": episode_id,
        "appointment_id": appointment_id,
        "prior_encounter_id": prior_encounter_id,
    })
    facility = linked["facility_id"]
    provider = linked["performed_by_provider_id"]
    infant = linked["infant_id"]
    episode = linked.get("episode_id")
    appointment = linked.get("appointment_id")

    identity(facility_id=facility["id"])

    if episode is not None and episode["status"] not in ("SCHEDULED",
                                                         "ESCALATED_DIAGNOSTIC"):
        raise ApiError("ERR_EPISODE_NOT_SCHEDULABLE")
    if appointment is not None and appointment["status"] != "BOOKED":
        raise ApiError("ERR_APPOINTMENT_NOT_OPEN")
    if calc.facility_posture(facility) == "SUSPENDED":
        raise ApiError("ERR_FACILITY_SUSPENDED")
    if encounter_type == "SURVEILLANCE" and not calc.open_risk_entries(infant["id"]):
        raise ApiError("ERR_NO_OPEN_RISK_FACTOR")
    if provider["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
    if provider["provider_type"] not in ENCOUNTER_PROVIDER_TYPES:
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH")
    if episode is not None and episode["infant_id"] != infant["id"]:
        raise ApiError("ERR_LINKAGE_MISMATCH")
    if appointment is not None and (episode is None
                                    or appointment["episode_id"] != episode["id"]):
        raise ApiError("ERR_LINKAGE_MISMATCH")
    if performed_at < infant["birth_datetime"] or performed_at > db.now():
        raise ApiError("ERR_TIMESTAMP_OUT_OF_RANGE")
    if encounter_type == "BIRTH_ADMISSION":
        existing = [e for e in store.encounters.values()
                    if e["infant_id"] == infant["id"]
                    and e["encounter_type"] == "BIRTH_ADMISSION"]
        if existing:
            raise ApiError("ERR_DUPLICATE_BIRTH_SCREEN")

    overall = calc.overall_result(left, right)
    before_discharge = (
        encounter_type == "BIRTH_ADMISSION"
        and (infant["discharge_datetime"] is None
             or performed_at <= infant["discharge_datetime"]))
    row = db.base_row(with_version=False)
    row.update({
        "infant_id": infant["id"],
        "facility_id": facility["id"],
        "performed_by_provider_id": provider["id"],
        "episode_id": episode["id"] if episode else None,
        "appointment_id": appointment["id"] if appointment else None,
        "prior_encounter_id": prior_encounter_id,
        "encounter_type": encounter_type,
        "method": method,
        "performed_at": performed_at,
        "left_ear_result": left,
        "right_ear_result": right,
        "overall_result": overall,
        "before_discharge": before_discharge,
        "age_days_at_encounter": db.floor_days(performed_at,
                                               infant["birth_datetime"]),
    })
    store.encounters[row["id"]] = row

    if encounter_type in ("BIRTH_ADMISSION", "HOME_VISIT"):
        _birth_or_home_cascade(infant, overall, performed_at)
    if appointment is not None:
        appointment["status"] = "ATTENDED"
        db.touch(appointment)
    if episode is not None:
        _episode_result_cascade(infant, episode, overall, performed_at)
    if encounter_type == "SURVEILLANCE":
        _surveillance_cascade(infant, overall)
    return response.single(row, serialize.encounter, 201)


def _birth_or_home_cascade(infant, overall, performed_at):
    if infant["screening_status"] != "NOT_SCREENED":
        return
    if overall == "PASS":
        infant["screening_status"] = "PASSED"
        db.touch(infant)
        for episode in db.sort_rows(calc.infant_episodes(infant["id"])):
            if (episode["episode_type"] == "INITIAL_SCREEN"
                    and episode["status"] in ("PENDING_SCHEDULING", "SCHEDULED")):
                services.close_episode(episode, "RESOLVED_PASS", "RESCREEN_PASSED",
                                       infant=infant, instant=performed_at,
                                       write_timeliness=True)
        services.recompute_risk(infant)
        return
    # CASCADE C3 -- a birth-admission or home-visit REFER / INCOMPLETE.
    infant["screening_status"] = "REFERRED"
    db.touch(infant)
    new_episode = None
    if not calc.open_episodes(infant["id"]):
        new_episode = services.create_episode(infant, "RESCREEN")
    band = services.recompute_risk(infant)
    if band == "CRITICAL":
        services.mint_cascade_task(
            infant, "OUTREACH_CALL",
            episode_id=new_episode["id"] if new_episode else None)
        services.recompute_risk(infant)


def _episode_result_cascade(infant, episode, overall, performed_at):
    if episode["status"] != "SCHEDULED":
        return
    if overall == "PASS":
        services.close_episode(episode, "RESOLVED_PASS", "RESCREEN_PASSED",
                               infant=infant, instant=performed_at,
                               write_timeliness=True)
        if infant["screening_status"] == "REFERRED":
            infant["screening_status"] = "PASSED"
            db.touch(infant)
        services.recompute_risk(infant)
        return
    if episode["episode_type"] in ("INITIAL_SCREEN", "RESCREEN"):
        episode["status"] = "ESCALATED_DIAGNOSTIC"
        db.touch(episode)
        if infant["screening_status"] == "REFERRED":
            infant["screening_status"] = "DIAGNOSTIC_IN_PROGRESS"
            db.touch(infant)
        services.recompute_risk(infant)


def _surveillance_cascade(infant, overall):
    entries = db.sort_rows(calc.open_risk_entries(infant["id"]))
    if overall == "PASS":
        for entry in entries:
            entry["status"] = "CLEARED"
            entry["surveillance_result"] = "PASS"
            entry["surveillance_recorded_at"] = db.now()
            db.touch(entry)
        services.recompute_risk(infant)
        return
    for entry in entries:
        entry["status"] = "LOSS_IDENTIFIED"
        entry["surveillance_result"] = "REFER"
        entry["surveillance_recorded_at"] = db.now()
        db.touch(entry)
    if infant["screening_status"] in ("PASSED", "DIAGNOSED_NO_LOSS",
                                      "LOST_TO_FOLLOW_UP"):
        infant["screening_status"] = "REFERRED"
        db.touch(infant)
    services.create_episode(infant, "DIAGNOSTIC")
    services.recompute_risk(infant)


@bp.get("/screening-encounters/<encounter_id>")
@endpoint(ALL_ROLES)
def get_encounter(encounter_id):
    row = resolve.one("encounter", encounter_id)
    identity()
    return response.single(row, serialize.encounter)


@bp.get("/screening-encounters")
@endpoint(ALL_ROLES)
def list_encounters():
    limit, offset = response.pagination()
    identity()
    rows = list(store.encounters.values())
    for field in ("infant_id", "facility_id", "performed_by_provider_id",
                  "episode_id", "appointment_id", "prior_encounter_id",
                  "encounter_type", "overall_result"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return response.listing(db.sort_rows(rows), serialize.encounter, limit, offset)
