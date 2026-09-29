"""Punch list endpoints (PRD §3.9)."""
from flask import Blueprint

import db
import guards
import repo
import response
import tx
import validate as v
from db import db as store
from errors import ApiError
from middleware import ALL_ROLES, actor, require
from services import derive

bp = Blueprint("punchlist", __name__)


@bp.post("/pre-opening/punch-list-items")
@require("ConstructionManager", "QualityInspector")
def create_item():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    description = v.req_str(body, "description", 1, 200)
    severity = v.req_enum(body, "severity", repo.SEVERITIES)
    milestone_id = v.opt_id(body, "milestone_id")

    program = repo.get_program(program_id)
    if milestone_id is not None:
        milestone = repo.get_milestone(milestone_id)
        if milestone["program_id"] != program_id:
            raise ApiError("ERR_CROSS_PROGRAM_REFERENCE",
                           "The milestone belongs to another program.")
    guards.ensure_not_stabilized(program)

    ts = db.stamp()
    item = {
        "id": db.new_id(),
        "program_id": program_id,
        "milestone_id": milestone_id,
        "description": description,
        "severity": severity,
        "state": "OPEN",
        "submitted_by_user_id": None,
        "verified_by_user_id": None,
        "rejection_count": 0,
        "blocks_certificate_of_occupancy": severity == "CRITICAL",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.punch_items[item["id"]] = item
    derive.refresh(program)
    tx.commit()
    return response.created(repo.serialize(item))


@bp.get("/pre-opening/punch-list-items")
@require(*ALL_ROLES)
def list_items():
    program_id = v.q_str("program_id")
    milestone_id = v.q_str("milestone_id")
    severity = v.q_enum("severity", repo.SEVERITIES)
    state = v.q_enum("state", repo.PUNCH_STATES)
    items = db.sort_created(list(store.punch_items.values()))
    if program_id:
        items = [i for i in items if i["program_id"] == program_id]
    if milestone_id:
        items = [i for i in items if i["milestone_id"] == milestone_id]
    if severity:
        items = [i for i in items if i["severity"] == severity]
    if state:
        items = [i for i in items if i["state"] == state]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.get("/pre-opening/punch-list-items/<item_id>")
@require(*ALL_ROLES)
def read_item(item_id):
    return response.ok(repo.serialize(repo.get_punch(item_id)))


@bp.post("/pre-opening/punch-list-items/<item_id>/submit-verification")
@require("ConstructionManager")
def submit_verification(item_id):
    item = repo.get_punch(item_id)
    program = repo.get_program(item["program_id"])
    guards.ensure_not_stabilized(program)
    if item["state"] not in ("OPEN", "REJECTED"):
        raise ApiError("ERR_INVALID_PUNCH_ITEM_STATE",
                       "An item in state %s may not be submitted for verification."
                       % item["state"])

    item["state"] = "READY_FOR_VERIFICATION"
    item["submitted_by_user_id"] = actor()
    tx.commit()
    return response.ok(repo.serialize(item))


@bp.post("/pre-opening/punch-list-items/<item_id>/verify")
@require("QualityInspector")
def verify_item(item_id):
    body = v.body()
    decision = v.req_enum(body, "decision", ("VERIFY", "REJECT"))
    item = repo.get_punch(item_id)
    program = repo.get_program(item["program_id"])

    # tier 6 -- segregation of duties precedes state admissibility (PRD §2.10)
    if item["submitted_by_user_id"] and item["submitted_by_user_id"] == actor():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The submitter of a punch item may not verify it.")
    guards.ensure_not_stabilized(program)
    if item["state"] != "READY_FOR_VERIFICATION":
        raise ApiError("ERR_INVALID_PUNCH_ITEM_STATE",
                       "Only a READY_FOR_VERIFICATION item may be verified or rejected.")

    if decision == "VERIFY":
        item["state"] = "VERIFIED"
        item["verified_by_user_id"] = actor()
    else:
        item["state"] = "REJECTED"
        item["rejection_count"] = item["rejection_count"] + 1
    derive.refresh(program)
    tx.commit()
    return response.ok(repo.serialize(item))


@bp.post("/pre-opening/punch-list-items/<item_id>/reopen")
@require("QualityInspector")
def reopen_item(item_id):
    body = v.body()
    v.opt_str(body, "reason", 1, 500)
    item = repo.get_punch(item_id)
    program = repo.get_program(item["program_id"])
    guards.ensure_not_stabilized(program)
    if item["state"] != "VERIFIED":
        raise ApiError("ERR_INVALID_PUNCH_ITEM_STATE",
                       "Only a VERIFIED item may be reopened.")

    item["state"] = "OPEN"
    item["verified_by_user_id"] = None
    item["submitted_by_user_id"] = None
    derive.refresh(program)
    tx.commit()
    return response.ok(repo.serialize(item))
