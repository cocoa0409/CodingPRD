"""Interdisciplinary and family conferences (PRD 3.7)."""

from flask import Blueprint

import cascades
import config
from envelope import created, listing, ok
from errors import (
    ERR_ATTESTATION_WINDOW_EXPIRED, ERR_NOT_AUTHORIZED_DECISION_MAKER,
    ERR_QUORUM_NOT_MET, ERR_SCHEDULE_CONFLICT, ERR_SURROGATE_HIERARCHY_EMPTY,
    ERR_VALIDATION, api_error,
)
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, pagination, paginate,
    path_row, query_filters, raw_body, require_order, state, touch, validate,
)
from store import hours, minutes, ordered, store

bp = Blueprint("conferences", __name__)

BUFFER = minutes(config.CONFERENCE_BUFFER_MINUTES)


@bp.post("/palliative/conferences")
def create_conference():
    auth([config.ROLE_SOCIAL, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("conference_type", "enum", required=True, enum=config.CONFERENCE_TYPES),
        field("modality", "enum", required=True, enum=config.MODALITIES),
        field("scheduled_start", "datetime", required=True),
        field("scheduled_end", "datetime", required=True),
    ])
    require_order(data["scheduled_start"], data["scheduled_end"],
                  "scheduled_start", "scheduled_end")
    patient = fk(store.patients, data["patient_id"])
    freeze_gate(patient)

    new_start, new_end = data["scheduled_start"], data["scheduled_end"]
    for other in cascades.rows_for_patient(store.conferences, patient["id"]):
        if other["status"] not in ("SCHEDULED", "HELD", "ATTESTED"):
            continue
        if new_start < other["scheduled_end"] + BUFFER and other["scheduled_start"] < new_end + BUFFER:
            raise api_error(ERR_SCHEDULE_CONFLICT)

    row = store.new_row({
        "patient_id": patient["id"],
        "conference_type": data["conference_type"],
        "modality": data["modality"],
        "scheduled_start": new_start,
        "scheduled_end": new_end,
        "decision_maker_id": None,
        "decision_maker_kind": None,
        "disciplines_present": [],
        "quorum_met": False,
        "documented_minutes": 0,
        "held_at": None,
        "attestation_due_at": None,
        "attested_disciplines": [],
        "attestation_complete": False,
        "consent_recorded": False,
        "status": "SCHEDULED",
    })
    store.conferences[row["id"]] = row
    return created(row)


@bp.post("/palliative/conferences/<cid>/hold")
def hold_conference(cid):
    auth([config.ROLE_SOCIAL, config.ROLE_ADMIN])
    conf = path_row(store.conferences, cid)
    body = raw_body()
    data = validate(body, [
        field("documented_minutes", "integer", required=True),
        field("disciplines_present", "array", item_kind="enum", item_enum=config.DISCIPLINES),
        field("decision_maker_id", "string"),
    ])
    decision_maker = fk(store.surrogates, data["decision_maker_id"])
    patient = store.patients.get(conf["patient_id"])
    freeze_gate(patient)
    state(conf["status"] in ("SCHEDULED", "QUORUM_FAILED"))

    if conf["conference_type"] == "FAMILY":
        lawful = cascades.lawful_surrogate(patient["id"])
        if decision_maker is None:
            if patient["capacity_status"] == "LACKS_CAPACITY" and lawful is None:
                raise api_error(ERR_SURROGATE_HIERARCHY_EMPTY)
        else:
            if patient["capacity_status"] != "LACKS_CAPACITY":
                raise api_error(ERR_NOT_AUTHORIZED_DECISION_MAKER)
            if lawful is None or decision_maker["id"] != lawful["id"]:
                raise api_error(ERR_NOT_AUTHORIZED_DECISION_MAKER)

    if data["disciplines_present"] is not None:
        conf["disciplines_present"] = list(data["disciplines_present"])
    conf["documented_minutes"] = data["documented_minutes"]

    if conf["conference_type"] == "IDT":
        present = set(conf["disciplines_present"])
        if all(d in present for d in config.IDT_REQUIRED_DISCIPLINES):
            conf["status"] = "HELD"
            conf["held_at"] = store.now()
            conf["attestation_due_at"] = conf["held_at"] + hours(config.ATTESTATION_WINDOW_HOURS)
            conf["quorum_met"] = True
        else:
            conf["status"] = "QUORUM_FAILED"
            conf["quorum_met"] = False
    else:
        conf["status"] = "HELD"
        conf["held_at"] = store.now()
        conf["attestation_due_at"] = conf["held_at"] + hours(config.ATTESTATION_WINDOW_HOURS)
        conf["consent_recorded"] = True
        if patient["capacity_status"] == "HAS_CAPACITY":
            conf["decision_maker_kind"] = "PATIENT"
        else:
            conf["decision_maker_kind"] = "SURROGATE"
        if decision_maker is not None:
            conf["decision_maker_id"] = decision_maker["id"]
    touch(conf)
    return ok(conf)


@bp.post("/palliative/conferences/<cid>/attestations")
def attest_conference(cid):
    auth([config.ROLE_PHYSICIAN, config.ROLE_NURSE, config.ROLE_SOCIAL,
          config.ROLE_CHAPLAIN, config.ROLE_ADMIN])
    conf = path_row(store.conferences, cid)
    body = raw_body()
    data = validate(body, [
        field("discipline", "enum", required=True, enum=config.DISCIPLINES),
        field("note_text", "string", required=True),
    ])
    # Permitted after a patient's death — no records-freeze gate here.
    state(conf["status"] in ("HELD", "QUORUM_FAILED"))
    if conf["status"] == "QUORUM_FAILED":
        raise api_error(ERR_QUORUM_NOT_MET)
    if conf["attestation_due_at"] is None or store.now() > conf["attestation_due_at"]:
        raise api_error(ERR_ATTESTATION_WINDOW_EXPIRED)
    discipline = data["discipline"]
    if discipline not in conf["disciplines_present"]:
        raise api_error(ERR_VALIDATION, "discipline was not recorded present at this conference.")
    if discipline in conf["attested_disciplines"]:
        raise api_error(ERR_VALIDATION, "discipline has already attested this conference.")

    conf["attested_disciplines"].append(discipline)
    complete = all(d in conf["attested_disciplines"] for d in conf["disciplines_present"])
    conf["attestation_complete"] = complete
    if complete:
        conf["status"] = "ATTESTED"
    touch(conf)
    return ok(conf)


@bp.get("/palliative/conferences/<cid>")
def read_conference(cid):
    auth([config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_NURSE,
          config.ROLE_CHAPLAIN, config.ROLE_BILLING, config.ROLE_ADMIN])
    return ok(path_row(store.conferences, cid))


@bp.get("/palliative/conferences")
def list_conferences():
    auth([config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_NURSE,
          config.ROLE_CHAPLAIN, config.ROLE_BILLING, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(
        ordered(store.conferences.values()),
        query_filters(["patient_id", "decision_maker_id", "conference_type", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
