"""Boarding agreement routes & lifecycle state machine (PRD §3.5, §3.6)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from clock import parse_iso, whole_days_between, format_iso
from services.common import new_common, touch, require_str
from services.serialize import view
from services.lookups import get_horse, get_stall, get_agreement, owner_has_active_waiver
from services.boarding_charge import provisional_charge, final_charge
from services.cascades import suspend_agreement_cascade, end_releases_turnouts_cascade
from services.standing import SUSPEND_SCORE

bp = Blueprint("boarding_agreements", __name__)


@bp.route("/boarding-agreements", methods=["POST"])
def create_agreement():
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    body = request.get_json(silent=True) or {}
    horse_id = require_str(body, "horse_id")
    stall_id = require_str(body, "stall_id")
    start_date = require_str(body, "start_date")
    # body-FK resolution (PRD §2.5)
    horse = get_horse(horse_id)
    stall = get_stall(stall_id)
    # validate start_date shape
    try:
        parse_iso(start_date)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "start_date must be ISO-8601 UTC")
    agreement = new_common()
    agreement.update({
        "horse_id": horse["id"],
        "stall_id": stall["id"],
        "start_date": format_iso(parse_iso(start_date)),
        "end_date": None,
        "suspended_days": 0,
        "provisional_charge_cents": 0,
        "final_charge_cents": 0,
        "suspended_at": None,
        "invoiced": False,
        "status": "DRAFT",
    })
    db.agreements[agreement["id"]] = agreement
    return success(view(agreement), 201)


def _owner_id_of_agreement(agreement):
    horse = db.horses.get(agreement["horse_id"])
    return horse["owner_id"] if horse else None


@bp.route("/boarding-agreements/<agreement_id>/transition", methods=["POST"])
def transition_agreement(agreement_id):
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    agreement = get_agreement(agreement_id)
    body = request.get_json(silent=True) or {}
    target = body.get("target_status")
    if target not in ("ACTIVE", "SUSPENDED", "ENDED"):
        raise err("ERR_INVALID_STATE", "Unknown or illegal target_status")

    if target == "ACTIVE":
        return _to_active(agreement)
    if target == "SUSPENDED":
        return _to_suspended(agreement)
    return _to_ended(agreement)


def _to_active(agreement):
    """DRAFT->ACTIVE (activate) or SUSPENDED->ACTIVE (reinstate)."""
    owner_id = _owner_id_of_agreement(agreement)
    if agreement["status"] == "DRAFT":
        # waiver-active guard (priority 8) then stall-full (priority 13)
        if not owner_has_active_waiver(owner_id):
            raise err("ERR_WAIVER_NOT_ACTIVE", "Owner has no SIGNED non-expired waiver")
        stall = db.stalls[agreement["stall_id"]]
        if stall["occupied_count"] >= stall["capacity"]:
            raise err("ERR_STALL_FULL", "Stall occupied_count >= capacity")
        agreement["status"] = "ACTIVE"
        stall["occupied_count"] += 1
        touch(stall)
        agreement["provisional_charge_cents"] = provisional_charge(stall, agreement)
        touch(agreement)
        return success(view(agreement), 200)

    if agreement["status"] == "SUSPENDED":
        owner = db.owners.get(owner_id)
        # waiver-active guard then owner-standing guard (priority 8, 15)
        if not owner_has_active_waiver(owner_id):
            raise err("ERR_WAIVER_NOT_ACTIVE", "Owner has no SIGNED non-expired waiver")
        if owner is None or owner["standing_score"] >= SUSPEND_SCORE:
            raise err("ERR_OWNER_DELINQUENT", "Owner standing_score >= SUSPEND_SCORE")
        now = db.clock.now
        if agreement["suspended_at"]:
            suspended = parse_iso(agreement["suspended_at"])
            agreement["suspended_days"] += whole_days_between(suspended, now)
        agreement["suspended_at"] = None
        agreement["status"] = "ACTIVE"
        touch(agreement)
        return success(view(agreement), 200)

    raise err("ERR_INVALID_STATE", "Agreement not in DRAFT or SUSPENDED")


def _to_suspended(agreement):
    """ACTIVE->SUSPENDED."""
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")
    now = db.clock.now
    agreement["status"] = "SUSPENDED"
    agreement["suspended_at"] = format_iso(now)
    touch(agreement)
    suspend_agreement_cascade(agreement)
    return success(view(agreement), 200)


def _to_ended(agreement):
    """{ACTIVE,SUSPENDED}->ENDED."""
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Agreement not in ACTIVE or SUSPENDED")
    now = db.clock.now
    was_suspended = agreement["status"] == "SUSPENDED"
    if was_suspended and agreement["suspended_at"]:
        suspended = parse_iso(agreement["suspended_at"])
        agreement["suspended_days"] += whole_days_between(suspended, now)
    agreement["status"] = "ENDED"
    agreement["end_date"] = format_iso(now)
    stall = db.stalls[agreement["stall_id"]]
    agreement["final_charge_cents"] = final_charge(stall, agreement)
    stall["occupied_count"] -= 1
    touch(stall)
    touch(agreement)
    end_releases_turnouts_cascade(agreement)
    return success(view(agreement), 200)
