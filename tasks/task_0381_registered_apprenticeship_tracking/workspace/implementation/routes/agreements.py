"""Apprentice agreement endpoints + lifecycle transitions (PRD §3.3, §3.7)."""
from flask import Blueprint, g, request

import db
from common import (
    get_json_body,
    parse_pagination,
    require_int,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from errors import err
from lookups import (
    get_agreement,
    get_apprentice,
    get_journeyworker,
    get_program,
)
from middleware import require_roles
from response import success_array, success_object
from response import now_iso
from services.calc import recompute_agreement_derived, recompute_available_slots

bp = Blueprint("agreements", __name__)

OPEN_STATUSES = {"REGISTERED", "ACTIVE", "SUSPENDED"}


@bp.route("/apprenticeship/agreements", methods=["POST"])
@require_roles("Sponsor")
def create_agreement():
    body = get_json_body()
    program_id = require_str(body, "program_id")
    apprentice_id = require_str(body, "apprentice_id")
    journeyworker_id = require_str(body, "journeyworker_id")
    start_date = require_str(body, "start_date")

    # FK existence (priority 4).
    program = get_program(program_id)
    apprentice = get_apprentice(apprentice_id)
    journeyworker = get_journeyworker(journeyworker_id)

    # Sponsor scoping (priority 7).
    if (
        journeyworker["sponsor_id"] != program["sponsor_id"]
        or apprentice["sponsor_id"] != program["sponsor_id"]
    ):
        raise err(
            "ERR_SPONSOR_MISMATCH",
            "Apprentice or journeyworker does not belong to the program's sponsor.",
        )

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "program_id": program_id,
            "apprentice_id": apprentice_id,
            "journeyworker_id": journeyworker_id,
            "start_date": start_date,
            "ojt_hours_completed": 0,
            "rti_hours_completed": 0,
            "milestones_attained_count": 0,
            "current_wage_step": 1,
            "current_hourly_wage_cents": 0,
            "completion_eligible": False,
            "end_date": None,
            "status": "DRAFT",
        }
    )
    db.agreements[rec["id"]] = rec
    # Derived fields are always kept consistent: a fresh agreement sits at wage
    # step 1, so its wage snapshot reflects the program's base step (threshold 0)
    # immediately, not 0. completion_eligible recomputes to its true initial value.
    recompute_agreement_derived(rec)
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/agreements", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_agreements():
    limit, offset = parse_pagination()
    items = list(db.agreements.values())
    for key in ("program_id", "apprentice_id", "journeyworker_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/agreements/<aid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_agreement_route(aid):
    rec = get_agreement(aid)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/agreements/<aid>/register", methods=["POST"])
@require_roles("Sponsor")
def register_agreement(aid):
    rec = get_agreement(aid)
    body = get_json_body()
    # expected_program_version is a non-optional field (PRD §2.9).
    expected_version = require_int(body, "expected_program_version", minimum=0)

    program = db.programs[rec["program_id"]]
    journeyworker = db.journeyworkers[rec["journeyworker_id"]]

    # Priority 6: legal state.
    if rec["status"] != "DRAFT":
        raise err("ERR_AGREEMENT_NOT_DRAFT", "Agreement must be DRAFT to register.")

    # Business rules, in PRD §3.3 order:
    # program ACTIVE -> journeyworker QUALIFIED -> OCC -> slot.
    if program["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Parent program must be ACTIVE to register.")
    if journeyworker["status"] != "QUALIFIED":
        raise err(
            "ERR_JOURNEYWORKER_NOT_QUALIFIED",
            "Supervising journeyworker must be QUALIFIED.",
        )
    if expected_version != program["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_program_version does not match the program's current version.",
        )
    # Recompute slots against current capacity before the ratio check.
    recompute_available_slots(program)
    if program["available_apprentice_slots"] < 1:
        raise err(
            "ERR_JOURNEYMAN_RATIO_EXCEEDED",
            "No available apprentice slots; journeyman ratio would be exceeded.",
        )

    # Commit.
    rec["status"] = "REGISTERED"
    program["active_agreement_count"] += 1
    journeyworker["active_apprentice_count"] += 1
    recompute_available_slots(program)
    db.touch(rec, bump_version=True)
    db.touch(journeyworker, bump_version=True)
    db.touch(program, bump_version=True)  # version bump invalidates stale callers
    return success_object(serialize(rec))


@bp.route("/apprenticeship/agreements/<aid>/activate", methods=["POST"])
@require_roles("Sponsor")
def activate_agreement(aid):
    rec = get_agreement(aid)
    if rec["status"] != "REGISTERED":
        raise err("ERR_AGREEMENT_NOT_REGISTERED", "Agreement must be REGISTERED to activate.")
    rec["status"] = "ACTIVE"
    db.touch(rec, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/agreements/<aid>/suspend", methods=["POST"])
@require_roles("Sponsor")
def suspend_agreement(aid):
    rec = get_agreement(aid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE to suspend.")
    rec["status"] = "SUSPENDED"
    db.touch(rec, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/agreements/<aid>/reinstate", methods=["POST"])
@require_roles("Sponsor")
def reinstate_agreement(aid):
    rec = get_agreement(aid)
    if rec["status"] != "SUSPENDED":
        raise err("ERR_AGREEMENT_NOT_SUSPENDED", "Agreement must be SUSPENDED to reinstate.")
    rec["status"] = "ACTIVE"
    db.touch(rec, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/agreements/<aid>/complete", methods=["POST"])
@require_roles("RegistrationAgency")
def complete_agreement(aid):
    rec = get_agreement(aid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE to complete.")
    if not rec["completion_eligible"]:
        raise err(
            "ERR_COMPLETION_REQUIREMENTS_NOT_MET",
            "Agreement does not meet completion requirements.",
        )
    program = db.programs[rec["program_id"]]
    journeyworker = db.journeyworkers[rec["journeyworker_id"]]

    rec["status"] = "COMPLETED"
    rec["end_date"] = now_iso()
    program["active_agreement_count"] -= 1
    journeyworker["active_apprentice_count"] -= 1
    recompute_available_slots(program)

    # Cascade: create the completion certificate exactly once.
    cert = db.base_record(common_fields=False)
    cert.update(
        {
            "agreement_id": rec["id"],
            "program_id": program["id"],
            "occupation_code": program["occupation_code"],
            "certified_ojt_hours": rec["ojt_hours_completed"],
            "certified_rti_hours": rec["rti_hours_completed"],
            "issued_by_user_id": g.user_id,
        }
    )
    db.certificates[cert["id"]] = cert

    db.touch(rec, bump_version=True)
    db.touch(journeyworker, bump_version=True)
    db.touch(program, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/agreements/<aid>/cancel", methods=["POST"])
@require_roles("Sponsor")
def cancel_agreement(aid):
    rec = get_agreement(aid)
    if rec["status"] not in OPEN_STATUSES:
        raise err("ERR_AGREEMENT_NOT_CANCELLABLE", "Agreement must be REGISTERED/ACTIVE/SUSPENDED to cancel.")
    program = db.programs[rec["program_id"]]
    journeyworker = db.journeyworkers[rec["journeyworker_id"]]

    rec["status"] = "CANCELLED"
    rec["end_date"] = now_iso()
    program["active_agreement_count"] -= 1
    journeyworker["active_apprentice_count"] -= 1
    recompute_available_slots(program)

    db.touch(rec, bump_version=True)
    db.touch(journeyworker, bump_version=True)
    db.touch(program, bump_version=True)
    return success_object(serialize(rec))
