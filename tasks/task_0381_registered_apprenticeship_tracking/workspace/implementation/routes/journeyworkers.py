"""Journeyworker endpoints + qualify/deactivate (PRD §3.2)."""
from flask import Blueprint, request

import db
from common import (
    get_json_body,
    parse_pagination,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from errors import err
from lookups import get_journeyworker, get_sponsor
from middleware import require_roles
from response import success_array, success_object
from services.calc import recompute_available_slots

bp = Blueprint("journeyworkers", __name__)


def _recompute_sponsor_program_slots(sponsor_id):
    for p in db.programs.values():
        if p["sponsor_id"] == sponsor_id:
            recompute_available_slots(p)


@bp.route("/apprenticeship/journeyworkers", methods=["POST"])
@require_roles("Sponsor")
def create_journeyworker():
    body = get_json_body()
    sponsor_id = require_str(body, "sponsor_id")
    full_name = require_str(body, "full_name")

    get_sponsor(sponsor_id)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "sponsor_id": sponsor_id,
            "full_name": full_name,
            "active_apprentice_count": 0,
            "status": "PROBATIONARY",
        }
    )
    db.journeyworkers[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/journeyworkers", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_journeyworkers():
    limit, offset = parse_pagination()
    items = list(db.journeyworkers.values())
    sponsor_id = request.args.get("sponsor_id")
    if sponsor_id is not None:
        items = [j for j in items if j["sponsor_id"] == sponsor_id]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/journeyworkers/<jid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_journeyworker_route(jid):
    rec = get_journeyworker(jid)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/journeyworkers/<jid>/qualify", methods=["POST"])
@require_roles("Sponsor")
def qualify_journeyworker(jid):
    rec = get_journeyworker(jid)
    if rec["status"] != "PROBATIONARY":
        raise err(
            "ERR_JOURNEYWORKER_NOT_PROBATIONARY",
            "Journeyworker must be PROBATIONARY to qualify.",
        )
    rec["status"] = "QUALIFIED"
    db.touch(rec, bump_version=True)
    _recompute_sponsor_program_slots(rec["sponsor_id"])
    return success_object(serialize(rec))


@bp.route("/apprenticeship/journeyworkers/<jid>/deactivate", methods=["POST"])
@require_roles("Sponsor")
def deactivate_journeyworker(jid):
    rec = get_journeyworker(jid)
    # From QUALIFIED: must be QUALIFIED and have no active apprentices.
    # From PROBATIONARY: must have no active apprentices.
    if rec["status"] == "QUALIFIED":
        if rec["active_apprentice_count"] != 0:
            raise err(
                "ERR_JOURNEYWORKER_HAS_APPRENTICES",
                "Journeyworker still supervises open agreements.",
            )
    elif rec["status"] == "PROBATIONARY":
        if rec["active_apprentice_count"] != 0:
            raise err(
                "ERR_JOURNEYWORKER_HAS_APPRENTICES",
                "Journeyworker still supervises open agreements.",
            )
    else:
        # Already INACTIVE: not QUALIFIED.
        raise err(
            "ERR_JOURNEYWORKER_NOT_QUALIFIED",
            "Journeyworker must be QUALIFIED or PROBATIONARY to deactivate.",
        )
    rec["status"] = "INACTIVE"
    db.touch(rec, bump_version=True)
    _recompute_sponsor_program_slots(rec["sponsor_id"])
    return success_object(serialize(rec))
