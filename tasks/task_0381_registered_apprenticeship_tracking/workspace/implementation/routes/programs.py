"""Apprenticeship program endpoints + activate/archive (PRD §3.1)."""
from flask import Blueprint

import db
from common import (
    get_json_body,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from errors import err
from lookups import get_program, get_sponsor
from middleware import require_roles
from response import success_array, success_object
from services.calc import OPEN_STATUSES, recompute_available_slots

bp = Blueprint("programs", __name__)

COMPLETION_TYPES = {"HOURS_BASED", "COMPETENCY_BASED", "HYBRID"}


@bp.route("/apprenticeship/programs", methods=["POST"])
@require_roles("Sponsor")
def create_program():
    body = get_json_body()
    sponsor_id = require_str(body, "sponsor_id")
    occupation_code = require_str(body, "occupation_code")
    occupation_title = require_str(body, "occupation_title")
    completion_type = require_enum(body, "completion_type", COMPLETION_TYPES)
    ojt_hours_required = require_int(body, "ojt_hours_required", minimum=0)
    rti_hours_required = require_int(body, "rti_hours_required", minimum=0)
    base_wage = require_int(body, "base_journeyworker_wage_cents", minimum=0)
    # PRD §3.1: journeyman_ratio "must be at least 1".
    journeyman_ratio = require_int(body, "journeyman_ratio", minimum=1)

    # FK existence (priority 4).
    get_sponsor(sponsor_id)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "sponsor_id": sponsor_id,
            "occupation_code": occupation_code,
            "occupation_title": occupation_title,
            "completion_type": completion_type,
            "ojt_hours_required": ojt_hours_required,
            "rti_hours_required": rti_hours_required,
            "base_journeyworker_wage_cents": base_wage,
            "journeyman_ratio": journeyman_ratio,
            "active_agreement_count": 0,
            "available_apprentice_slots": 0,
            "status": "DRAFT",
        }
    )
    db.programs[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/programs", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_programs():
    from flask import request

    limit, offset = parse_pagination()
    items = list(db.programs.values())
    sponsor_id = request.args.get("sponsor_id")
    if sponsor_id is not None:
        items = [p for p in items if p["sponsor_id"] == sponsor_id]
    # Reflect current capacity on read.
    for p in items:
        recompute_available_slots(p)
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/programs/<pid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_program_route(pid):
    rec = get_program(pid)
    # GET of a program always reflects current capacity (PRD §2.6).
    recompute_available_slots(rec)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/programs/<pid>/activate", methods=["POST"])
@require_roles("RegistrationAgency")
def activate_program(pid):
    rec = get_program(pid)
    if rec["status"] != "DRAFT":
        raise err("ERR_PROGRAM_NOT_DRAFT", "Program must be DRAFT to activate.")
    steps = [w for w in db.wage_steps.values() if w["program_id"] == pid]
    if not steps:
        raise err("ERR_NO_WAGE_STEPS", "Program has no wage steps.")
    if not any(s["ojt_hours_threshold"] == 0 for s in steps):
        raise err("ERR_NO_BASE_WAGE_STEP", "Program has no base (threshold 0) wage step.")
    rec["status"] = "ACTIVE"
    recompute_available_slots(rec)
    db.touch(rec, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/programs/<pid>/archive", methods=["POST"])
@require_roles("RegistrationAgency")
def archive_program(pid):
    rec = get_program(pid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Program must be ACTIVE to archive.")
    open_agreements = any(
        a["program_id"] == pid and a["status"] in OPEN_STATUSES
        for a in db.agreements.values()
    )
    if open_agreements:
        raise err(
            "ERR_PROGRAM_HAS_OPEN_AGREEMENTS",
            "Program has open agreements and cannot be archived.",
        )
    rec["status"] = "ARCHIVED"
    db.touch(rec, bump_version=True)
    return success_object(serialize(rec))
