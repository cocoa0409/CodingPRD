"""Thirty-day readmission tracking, its cascade and retraction (PRD 3.9).

Recording and retracting are the two mutating capabilities exempt from the
global write gate.
"""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("readmissions", __name__)


@bp.post("/tcm/episodes/<episode_id>/readmissions")
def record_readmission(episode_id):
    user_id, _role = G.auth(["ProgramAdmin"])
    data = G.body()
    readmission_date = G.req_date(data, "readmission_date")
    classification = G.req_string(data, "classification")
    G.enum(classification, C.READMISSION_CLASSIFICATIONS, "classification")

    episode = G.get_episode(episode_id)

    day_index = store.day_diff(readmission_date, episode["discharge_date"])
    if day_index < 1 or day_index > C.READMISSION_WINDOW_DAYS:
        raise ApiError("ERR_READMISSION_OUT_OF_WINDOW")

    event = domain.create_readmission_event(episode, readmission_date, classification, user_id)
    claim = domain.episode_claim(episode)

    if classification == "UNPLANNED_INPATIENT":
        episode["billing_eligible"] = False
        if episode["status"] in ("ACTIVE", "SERVICE_PERIOD_CLOSED"):
            episode["pre_readmission_status"] = episode["status"]
            episode["status"] = "CLOSED_READMITTED"
        if claim is not None:
            if claim["status"] in C.NON_TERMINAL_CLAIM_STATUSES:
                domain.void_claim(claim)
            elif claim["status"] == "PAID":
                episode["recoupment_required"] = True
        store.touch(episode)
        domain.recompute_navigator(episode["navigator_id"])
        domain.recompute_patient(episode["patient_id"])
        domain.evaluate_freeze(episode)
    elif classification in C.READMISSION_FLAGGING_CLASSES:
        if claim is not None and not claim["readmission_flagged"]:
            claim["readmission_flagged"] = True
            store.touch(claim)

    return envelope.created(serialize(event))


@bp.get("/tcm/readmissions/<readmission_id>")
def read_readmission(readmission_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("readmissions", readmission_id)))


@bp.get("/tcm/readmissions")
def list_readmissions():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "source_red_flag_id", "classification", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("readmissions", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


@bp.post("/tcm/readmissions/<readmission_id>/retract")
def retract_readmission(readmission_id):
    G.auth(["ProgramAdmin"])
    data = G.body()
    retraction_reason = G.req_string(data, "retraction_reason")

    event = G.get_row("readmissions", readmission_id)
    episode = DB["episodes"][event["episode_id"]]

    if event["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECORDED event may be retracted.")

    event["status"] = "RETRACTED"
    event["retraction_reason"] = retraction_reason
    store.touch(event)

    domain.recompute_episode_readmission_counters(episode)

    if event["classification"] == "UNPLANNED_INPATIENT":
        if episode["pre_readmission_status"] is not None:
            episode["status"] = episode["pre_readmission_status"]
            episode["pre_readmission_status"] = None
        episode["billing_eligible"] = True
        store.touch(episode)
    elif event["classification"] in C.READMISSION_FLAGGING_CLASSES:
        remaining = [
            e
            for e in DB["readmissions"].values()
            if e["episode_id"] == episode["id"]
            and e["status"] == "RECORDED"
            and e["classification"] in C.READMISSION_FLAGGING_CLASSES
        ]
        if not remaining:
            claim = domain.episode_claim(episode)
            if claim is not None and claim["readmission_flagged"]:
                claim["readmission_flagged"] = False
                store.touch(claim)

    domain.recompute_navigator(episode["navigator_id"])
    domain.recompute_patient(episode["patient_id"])
    domain.evaluate_freeze(episode)

    return envelope.ok(serialize(event))
