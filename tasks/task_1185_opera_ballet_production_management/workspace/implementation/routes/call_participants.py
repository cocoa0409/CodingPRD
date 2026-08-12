"""CallParticipant routes (PRD 3.6) — rest floor, waivers, segregation of duties."""

from flask import Blueprint

from db import store
from errors import (ApiError, ERR_CALL_NOT_OPEN, ERR_CONTRACT_NOT_ACTIVE,
                    ERR_DUP_PARTICIPANT, ERR_INVALID_STATE, ERR_REST_FLOOR,
                    ERR_SOD, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import recompute_headcount, rest_floor_violation
from util import json_body, new_record, opt_bool, req_enum, req_str, to_public, touch

bp = Blueprint("call_participants", __name__)

TARGET_STATES = ("CONFIRMED", "DECLINED", "CHECKED_IN", "REMOVED")
OPEN_CALL_STATES = ("DRAFT", "PUBLISHED")
NON_TERMINAL = ("INVITED", "WAIVER_PENDING", "CONFIRMED", "CHECKED_IN")


@bp.post("/opera/call-participants")
def create_participant():
    require_roles("ContractsOfficer")
    body = json_body()
    call_id = req_str(body, "call_id")
    contract_id = req_str(body, "contract_id")
    waive = opt_bool(body, "waive_rest_floor", default=False)
    call = get_or_404(store.rehearsal_calls, call_id, "RehearsalCall")
    contract = get_or_404(store.contracts, contract_id, "Contract")
    # State guards in PRD 3.6 order: call open, contract active.
    if call["status"] not in OPEN_CALL_STATES:
        raise conflict(ERR_CALL_NOT_OPEN,
                       "Participant operations require the call in DRAFT or PUBLISHED")
    if contract["status"] != "ACTIVE":
        raise conflict(ERR_CONTRACT_NOT_ACTIVE, "Contract must be ACTIVE")
    for p in store.call_participants.values():
        if (p["call_id"] == call["id"] and p["contract_id"] == contract["id"]
                and p["status"] in NON_TERMINAL):
            raise conflict(ERR_DUP_PARTICIPANT,
                           "A non-terminal participant already exists for this "
                           "call and contract")
    status = "INVITED"
    if rest_floor_violation(contract, call):
        if waive:
            status = "WAIVER_PENDING"
        else:
            raise ApiError(ERR_REST_FLOOR, 422,
                           "Gap between committed calls is below the contract "
                           "rest floor")
    rec = new_record(
        call_id=call["id"],
        contract_id=contract["id"],
        waive_rest_floor=waive,
        status=status,
    )
    store.call_participants[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/call-participants")
def list_participants():
    require_roles("Any")
    return list_response(
        store.call_participants.values(),
        [("call_id", "call_id"), ("contract_id", "contract_id"),
         ("status", "status")],
    )


@bp.get("/opera/call-participants/<pid>")
def get_participant(pid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.call_participants, pid,
                                          "CallParticipant")))


def _require_call_open(participant):
    call = store.rehearsal_calls[participant["call_id"]]
    if call["status"] not in OPEN_CALL_STATES:
        raise conflict(ERR_CALL_NOT_OPEN,
                       "Participant operations require the call in DRAFT or PUBLISHED")
    return call


@bp.post("/opera/call-participants/<pid>/transition")
def transition_participant(pid):
    require_roles("ContractsOfficer")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    part = get_or_404(store.call_participants, pid, "CallParticipant")
    call = _require_call_open(part)
    cur = part["status"]

    if cur == "INVITED" and to_state == "CONFIRMED":
        pass
    elif cur == "INVITED" and to_state == "DECLINED":
        pass
    elif cur == "CONFIRMED" and to_state == "CHECKED_IN":
        pass
    elif cur == "CONFIRMED" and to_state == "REMOVED":
        pass
    else:
        raise conflict(ERR_INVALID_STATE,
                       f"CallParticipant cannot transition {cur} -> {to_state}")

    part["status"] = to_state
    touch(part)
    recompute_headcount(call)
    return ok_object(to_public(part))


@bp.post("/opera/call-participants/<pid>/approve-waiver")
def approve_waiver(pid):
    uid, _ = require_roles("ContractsOfficer")
    part = get_or_404(store.call_participants, pid, "CallParticipant")
    call = _require_call_open(part)
    if part["status"] != "WAIVER_PENDING":
        raise conflict(ERR_INVALID_STATE,
                       f"CallParticipant in {part['status']} has no waiver to approve")
    # Segregation of duties (PRD 2.10): approver must differ from the
    # contract's creator.
    contract = store.contracts[part["contract_id"]]
    if uid == contract["created_by_user_id"]:
        raise ApiError(ERR_SOD, 403,
                       "Waiver approver must differ from the contract creator")
    part["status"] = "CONFIRMED"
    touch(part)
    recompute_headcount(call)
    return ok_object(to_public(part))
