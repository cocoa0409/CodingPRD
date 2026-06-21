"""SplitRequest / SplitParticipant endpoints: create, fetch, list, participants,
pay/forgive, cancel.
"""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import split as split_svc
from services import transfer as transfer_svc

bp = Blueprint("split_requests", __name__)


@bp.route("/split-requests", methods=["POST"])
def create_split_request():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        body = validate.get_json_body()
        organizer_id = validate.require_str(body, "organizer_account_id")
        total = validate.require_int(body, "total_amount_cents", minimum=1)
        split_mode = validate.require_enum(body, "split_mode", {"EVEN", "WEIGHTED"})
        participants_in = validate.require(body, "participants")
        if not isinstance(participants_in, list):
            raise err("ERR_INVALID_REQUEST", "participants must be a list.")
        organizer = db.accounts.get(organizer_id)
        if not organizer:
            raise err("ERR_NOT_FOUND", "Organizer account not found.")
        if p.user_id != organizer_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the organizer account owner.")

        # parse participant entries
        parsed = []
        for entry in participants_in:
            if not isinstance(entry, dict):
                raise err("ERR_INVALID_REQUEST", "Each participant must be an object.")
            pa_id = entry.get("participant_account_id")
            if not isinstance(pa_id, str) or pa_id.strip() == "":
                raise err("ERR_INVALID_REQUEST", "participant_account_id required.")
            weight = entry.get("weight", 1)
            if weight is None:
                weight = 1
            if isinstance(weight, bool) or not isinstance(weight, int):
                raise err("ERR_INVALID_REQUEST", "weight must be an integer.")
            parsed.append({"participant_account_id": pa_id, "weight": weight})

        # existence of every participant account (FK existence before business rules)
        for entry in parsed:
            if not db.accounts.get(entry["participant_account_id"]):
                raise err("ERR_NOT_FOUND", "Participant account not found.")

        # split-participant validity (priority 17)
        if len(parsed) < 2:
            raise err("ERR_SPLIT_PARTICIPANT_INVALID", "Split needs >= 2 participants.")
        if total < len(parsed):
            raise err("ERR_SPLIT_PARTICIPANT_INVALID",
                      "total_amount_cents must be >= participant count.")
        seen = set()
        for entry in parsed:
            if entry["participant_account_id"] in seen:
                raise err("ERR_SPLIT_PARTICIPANT_INVALID", "Duplicate participant.")
            seen.add(entry["participant_account_id"])
        if split_mode == "WEIGHTED":
            for entry in parsed:
                if entry["weight"] < 1:
                    raise err("ERR_SPLIT_PARTICIPANT_INVALID", "weight must be >= 1.")

        sr = {
            "organizer_account_id": organizer_id,
            "total_amount_cents": total,
            "split_mode": split_mode,
            "status": "OPEN",
            "collected_amount_cents": 0,
        }
        models._stamp_create(sr)
        db.split_requests[sr["id"]] = sr

        # create participants in declared order (created_at ASC == insertion order)
        part_objs = []
        for entry in parsed:
            sp = {
                "split_request_id": sr["id"],
                "participant_account_id": entry["participant_account_id"],
                "weight": entry["weight"],
                "share_amount_cents": 0,
                "status": "OWED",
                "settled_transfer_id": None,
            }
            models._stamp_create(sp)
            db.split_participants[sp["id"]] = sp
            part_objs.append(sp)

        split_svc.allocate_shares(total, split_mode, part_objs)
        return response.ok(models.serialize(sr), 201)


@bp.route("/split-requests/<sr_id>", methods=["GET"])
def get_split_request(sr_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        sr = db.split_requests.get(sr_id)
        if not sr:
            raise err("ERR_NOT_FOUND", "Split request not found.")
        return response.ok(models.serialize(sr))


@bp.route("/split-requests", methods=["GET"])
def list_split_requests():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.split_requests.values())
        for key in ("organizer_account_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [s for s in items if s.get(key) == val]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/split-requests/<sr_id>/participants", methods=["GET"])
def list_participants(sr_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        sr = db.split_requests.get(sr_id)
        if not sr:
            raise err("ERR_NOT_FOUND", "Split request not found.")
        limit, offset = parse_pagination()
        items = [sp for sp in db.split_participants.values()
                 if sp["split_request_id"] == sr_id]
        pa_filter = request.args.get("participant_account_id")
        if pa_filter is not None:
            items = [sp for sp in items if sp["participant_account_id"] == pa_filter]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


def _resolve_participant(sr_id, pid):
    sr = db.split_requests.get(sr_id)
    if not sr:
        raise err("ERR_NOT_FOUND", "Split request not found.")
    sp = db.split_participants.get(pid)
    if not sp or sp["split_request_id"] != sr_id:
        raise err("ERR_NOT_FOUND", "Participant not found.")
    return sr, sp


@bp.route("/split-requests/<sr_id>/participants/<pid>/pay", methods=["POST"])
def pay_participant(sr_id, pid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        sr, sp = _resolve_participant(sr_id, pid)
        if p.user_id != sp["participant_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the participant may pay.")
        if sp["status"] != "OWED" or sr["status"] not in ("OPEN", "PARTIALLY_SETTLED"):
            raise err("ERR_INVALID_STATE", "Share not payable in current state.")
        body = validate.get_json_body()
        memo = validate.optional_str(body, "memo", "")
        participant = db.accounts[sp["participant_account_id"]]
        organizer = db.accounts[sr["organizer_account_id"]]
        if participant["status"] == "FROZEN" or organizer["status"] == "FROZEN":
            raise err("ERR_ACCOUNT_FROZEN", "An account in this payment is frozen.")
        t = transfer_svc.create_transfer(participant, organizer, sp["share_amount_cents"],
                                         memo=memo)
        sp["settled_transfer_id"] = t["id"]
        sp["status"] = "PAID"
        models.touch(sp)
        split_svc.rollup(sr)
        return response.ok(models.serialize(sp))


@bp.route("/split-requests/<sr_id>/participants/<pid>/forgive", methods=["POST"])
def forgive_participant(sr_id, pid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        sr, sp = _resolve_participant(sr_id, pid)
        if p.user_id != sr["organizer_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the organizer may forgive.")
        if sp["status"] != "OWED":
            raise err("ERR_INVALID_STATE", "Share is not OWED.")
        sp["status"] = "FORGIVEN"
        models.touch(sp)
        split_svc.rollup(sr)
        return response.ok(models.serialize(sp))


@bp.route("/split-requests/<sr_id>/cancel", methods=["POST"])
def cancel_split_request(sr_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        sr = db.split_requests.get(sr_id)
        if not sr:
            raise err("ERR_NOT_FOUND", "Split request not found.")
        if p.user_id != sr["organizer_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the organizer may cancel.")
        parts = [sp for sp in db.split_participants.values()
                 if sp["split_request_id"] == sr_id]
        if sr["status"] != "OPEN" or any(sp["status"] == "PAID" for sp in parts):
            raise err("ERR_INVALID_STATE", "Split cannot be cancelled.")
        sr["status"] = "CANCELLED"
        models.touch(sr)
        for sp in parts:
            if sp["status"] == "OWED":
                sp["status"] = "FORGIVEN"
                models.touch(sp)
        return response.ok(models.serialize(sr))
