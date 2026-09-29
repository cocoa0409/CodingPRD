"""Volunteer companions, training, certification and matching (§3.6)."""

from flask import Blueprint, request

from core import calc
from core.auth import authenticate, own_match, own_volunteer_path
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import (DECISIONS, END_REASONS, LOSS_TYPES, body, opt_array, opt_int,
                        req_enum, req_number, req_str)
from core.store import add_days, public, store
from services import cascade, derive
from services.state import must_exist, require_participant_active, transition

bp = Blueprint("volunteers", __name__)

REQUIRED_TRAINING_HOURS = 16
CORE_MODULES = ("CORE_LISTENING", "CORE_SAFETY")
CERT_VALID_DAYS = 365
HIGH_TIER_TRAINING_HOURS = 24


@bp.route("/bereavement/volunteer-companions", methods=["POST"])
def create_volunteer():
    authenticate(["ProgramDirector"])
    data = body()
    full_name = req_str(data, "full_name")
    endorsed = opt_array(data, "endorsed_loss_types", [], LOSS_TYPES)
    max_matches = opt_int(data, "max_concurrent_matches", 3, 1)
    rec = store.create("VolunteerCompanion", {
        "full_name": full_name,
        "endorsed_loss_types": endorsed,
        "max_concurrent_matches": max_matches,
        "training_hours": 0,
        "modules_completed": [],
        "certified_on": None,
        "certification_expires_on": None,
        "active_match_count": 0,
        "status": "APPLIED",
    })
    return created(public(rec))


@bp.route("/bereavement/volunteer-companions/<vid>", methods=["GET"])
def read_volunteer(vid):
    ctx = authenticate(["ProgramDirector", "IntakeCoordinator", "VolunteerCompanion"])
    volunteer = must_exist("VolunteerCompanion", vid)
    own_volunteer_path(ctx, volunteer)
    return ok(public(volunteer))


@bp.route("/bereavement/volunteer-companions/<vid>/training-records", methods=["POST"])
def record_training(vid):
    ctx = authenticate(["ProgramDirector", "VolunteerCompanion"])
    volunteer = must_exist("VolunteerCompanion", vid)
    own_volunteer_path(ctx, volunteer)
    data = body()
    module_code = req_str(data, "module_code")
    hours = req_number(data, "hours", 0)
    transition(volunteer, {"APPLIED", "IN_TRAINING", "LAPSED"})

    volunteer["training_hours"] = calc.num(calc.dec(volunteer["training_hours"]) + calc.dec(hours), 2)
    volunteer["modules_completed"] = list(volunteer["modules_completed"]) + [module_code]

    cleared_hours = calc.dec(volunteer["training_hours"]) >= calc.dec(REQUIRED_TRAINING_HOURS)
    cleared_modules = all(code in volunteer["modules_completed"] for code in CORE_MODULES)
    if cleared_hours and cleared_modules:
        volunteer["status"] = "CERTIFIED"
        certified_on = store.today()
        volunteer["certified_on"] = certified_on.isoformat()
        volunteer["certification_expires_on"] = add_days(certified_on, CERT_VALID_DAYS).isoformat()
    else:
        volunteer["status"] = "IN_TRAINING"
    store.touch(volunteer)
    return ok(public(volunteer))


@bp.route("/bereavement/volunteer-companions/<vid>/suspend", methods=["POST"])
def suspend_volunteer(vid):
    authenticate(["ProgramDirector"])
    volunteer = must_exist("VolunteerCompanion", vid)
    body()
    transition(volunteer, {"CERTIFIED"})
    volunteer["status"] = "SUSPENDED"
    for match in store.find("CompanionMatch", companion_id=vid):
        if match["status"] == "PROPOSED":
            match["status"] = "DECLINED"
            store.touch(match)
    store.touch(volunteer)
    return ok(public(volunteer))


@bp.route("/bereavement/volunteer-companions/<vid>/reinstate", methods=["POST"])
def reinstate_volunteer(vid):
    authenticate(["ProgramDirector"])
    volunteer = must_exist("VolunteerCompanion", vid)
    body()
    transition(volunteer, {"SUSPENDED"})
    expires = volunteer.get("certification_expires_on")
    if expires is not None and store.today().isoformat() > expires:
        raise ApiError("ERR_INVALID_STATE", "The certification expired while suspended.")
    volunteer["status"] = "CERTIFIED"
    store.touch(volunteer)
    return ok(public(volunteer))


@bp.route("/bereavement/companion-matches", methods=["POST"])
def create_match():
    authenticate(["IntakeCoordinator"])
    data = body()
    companion_id = req_str(data, "companion_id")
    participant_id = req_str(data, "participant_id")

    volunteer = must_exist("VolunteerCompanion", companion_id)
    participant = must_exist("Participant", participant_id)

    if volunteer["status"] != "CERTIFIED":
        raise ApiError("ERR_COMPANION_NOT_CERTIFIED", "The volunteer is not CERTIFIED.")
    require_participant_active(participant)

    if participant["risk_tier"] == "HIGH":
        if calc.dec(volunteer["training_hours"]) < calc.dec(HIGH_TIER_TRAINING_HOURS):
            raise ApiError("ERR_COMPANION_TRAINING_INSUFFICIENT",
                           "A HIGH-tier participant requires at least 24 training hours.")

    endorsed = participant["loss_type"] in volunteer["endorsed_loss_types"]
    if not endorsed:
        raise ApiError("ERR_LOSS_TYPE_NOT_ENDORSED", "The volunteer is not endorsed for this loss type.")

    for other in store.find("CompanionMatch", companion_id=companion_id,
                            participant_id=participant_id):
        if other["status"] in ("PROPOSED", "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_MATCH", "This pairing already exists.")

    rec = store.create("CompanionMatch", {
        "companion_id": companion_id,
        "participant_id": participant_id,
        "status": "PROPOSED",
        "match_score": calc.match_score(endorsed, volunteer["training_hours"],
                                        volunteer["active_match_count"],
                                        volunteer["max_concurrent_matches"]),
        "started_on": None,
        "ended_on": None,
        "end_reason": None,
    })
    return created(public(rec))


@bp.route("/bereavement/companion-matches/<mid>", methods=["GET"])
def read_match(mid):
    ctx = authenticate(["IntakeCoordinator", "ProgramDirector", "VolunteerCompanion"])
    match = must_exist("CompanionMatch", mid)
    own_match(ctx, match)
    return ok(public(match))


@bp.route("/bereavement/companion-matches", methods=["GET"])
def list_matches():
    authenticate(["IntakeCoordinator", "ProgramDirector", "VolunteerCompanion"])
    rows = store.all("CompanionMatch")
    for key in ("participant_id", "companion_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


@bp.route("/bereavement/companion-matches/<mid>/respond", methods=["POST"])
def respond_match(mid):
    ctx = authenticate(["VolunteerCompanion"])
    match = must_exist("CompanionMatch", mid)
    own_match(ctx, match)
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    transition(match, {"PROPOSED"})
    volunteer = store.get("VolunteerCompanion", match["companion_id"])
    if decision == "DECLINE":
        match["status"] = "DECLINED"
        store.touch(match)
        return ok(public(match))

    if volunteer is None or volunteer["status"] != "CERTIFIED":
        raise ApiError("ERR_COMPANION_NOT_CERTIFIED", "The volunteer is not CERTIFIED.")
    if volunteer["active_match_count"] + 1 > volunteer["max_concurrent_matches"]:
        raise ApiError("ERR_MATCH_LIMIT_REACHED", "The concurrent-match ceiling would be exceeded.")

    match["status"] = "ACTIVE"
    match["started_on"] = store.today().isoformat()
    store.touch(match)
    derive.recompute_volunteer(volunteer)
    store.touch(volunteer)
    participant = store.get("Participant", match["participant_id"])
    if participant is not None:
        participant["has_active_companion"] = True
        store.touch(participant)
    return ok(public(match))


@bp.route("/bereavement/companion-matches/<mid>/end", methods=["POST"])
def end_match_route(mid):
    ctx = authenticate(["IntakeCoordinator", "VolunteerCompanion"])
    match = must_exist("CompanionMatch", mid)
    own_match(ctx, match)
    data = body()
    reason = req_enum(data, "end_reason", END_REASONS)
    transition(match, {"ACTIVE"})
    cascade.end_match(match, reason)
    return ok(public(match))
