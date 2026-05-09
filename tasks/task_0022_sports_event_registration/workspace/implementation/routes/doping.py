"""Doping sample, sanction, appeal endpoints."""
from flask import Blueprint, g

import db
from clock import now, parse_iso, iso
from errors import err
from middleware import require_auth
from response import success
from services import doping as doping_svc
from services.validation import (
    get_body, require_field, require_str, require_bool, check_version,
)


bp = Blueprint("doping", __name__)


@bp.route("/events/<event_id>/doping-samples", methods=["POST"])
@require_auth(roles={"DopingOfficer"})
def create_sample(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    body = get_body()
    require_field(body, "participant_id")
    require_field(body, "collected_at")
    pid = body["participant_id"]
    if not isinstance(pid, str):
        raise err("ERR_VALIDATION", "participant_id must be string")
    p = db.participants.get(pid)
    if not p or p["event_id"] != event_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "participant not in event")
    try:
        parse_iso(body["collected_at"])
    except ValueError:
        raise err("ERR_VALIDATION", "collected_at must be ISO 8601")

    sample = {
        "event_id": event_id,
        "participant_id": pid,
        "collected_at": body["collected_at"],
        "chain_log": [],
        "status": "COLLECTED",
        "result_text": None,
    }
    db.stamp_create(sample, common_fields=True)
    db.doping_samples[sample["id"]] = sample
    return success(db.public(sample), 201)


@bp.route("/doping-samples/<sample_id>/custody", methods=["POST"])
@require_auth(roles={"DopingOfficer"})
def append_custody(sample_id):
    sample = db.doping_samples.get(sample_id)
    if not sample:
        raise err("ERR_NOT_FOUND", "sample not found")
    body = get_body()
    require_field(body, "action")
    require_field(body, "at")
    action = body["action"]
    if action not in ("DISPATCH", "RECEIVE"):
        raise err("ERR_VALIDATION", "action must be DISPATCH or RECEIVE")
    try:
        at_dt = parse_iso(body["at"])
    except ValueError:
        raise err("ERR_VALIDATION", "at must be ISO 8601")

    # Strict monotonicity FIRST (PRD §2.13: serialization rule for races on
    # this endpoint pins the loser's error to ERR_CHAIN_OF_CUSTODY_BROKEN —
    # so monotonicity must be evaluated before the source-state check that
    # would otherwise mask the race loser's error as ERR_INVALID_STATE).
    chain = sample.get("chain_log", [])
    if chain:
        last_at = parse_iso(chain[-1]["at"])
        if at_dt <= last_at:
            raise err("ERR_CHAIN_OF_CUSTODY_BROKEN", "at must be strictly later than last entry")

    # State: must be COLLECTED for DISPATCH or IN_TRANSIT for RECEIVE
    if action == "DISPATCH" and sample["status"] != "COLLECTED":
        raise err("ERR_INVALID_STATE", "sample not in COLLECTED for DISPATCH")
    if action == "RECEIVE" and sample["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "sample not in IN_TRANSIT for RECEIVE")

    check_version(sample, body)

    chain.append({
        "actor_user_id": g.user_id,
        "action": action,
        "at": body["at"],
    })
    sample["chain_log"] = chain
    if action == "DISPATCH":
        sample["status"] = "IN_TRANSIT"
    elif action == "RECEIVE":
        sample["status"] = "RECEIVED"
    db.stamp_update(sample)
    return success(db.public(sample), 200)


@bp.route("/doping-samples/<sample_id>/result", methods=["POST"])
@require_auth(roles={"DopingOfficer"})
def submit_result(sample_id):
    sample = db.doping_samples.get(sample_id)
    if not sample:
        raise err("ERR_NOT_FOUND", "sample not found")
    body = get_body()
    if sample["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "sample not in RECEIVED")
    # Segregation of duties: same DopingOfficer who appended the RECEIVE custody cannot submit result.
    receive_actor = None
    for entry in reversed(sample.get("chain_log", [])):
        if entry["action"] == "RECEIVE":
            receive_actor = entry["actor_user_id"]
            break
    if receive_actor and receive_actor == g.user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "DopingOfficer who recorded RECEIVE cannot submit result")
    positive = require_bool(body, "positive")
    result_text = body.get("result_text")
    if result_text is not None and not isinstance(result_text, str):
        raise err("ERR_VALIDATION", "result_text must be string or null")
    check_version(sample, body)
    sample["result_text"] = result_text
    sample["status"] = "POSITIVE" if positive else "NEGATIVE"
    db.stamp_update(sample)
    if positive:
        doping_svc.issue_sanction_from_positive_sample(sample, g.user_id, g.user_role)
    return success(db.public(sample), 200)


@bp.route("/doping-samples/<sample_id>/void", methods=["POST"])
@require_auth(roles={"DopingOfficer"})
def void_sample(sample_id):
    sample = db.doping_samples.get(sample_id)
    if not sample:
        raise err("ERR_NOT_FOUND", "sample not found")
    body = get_body()
    if sample["status"] != "COLLECTED":
        raise err("ERR_INVALID_STATE", "sample not in COLLECTED")
    check_version(sample, body)
    sample["status"] = "VOIDED"
    db.stamp_update(sample)
    return success(db.public(sample), 200)
