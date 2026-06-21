"""RTI record endpoints (PRD §3.5). Records are immutable RECORDED artifacts but
still carry common fields per the entity table (id/created_at/updated_at/version)."""
from flask import Blueprint, request

import db
from common import (
    get_json_body,
    parse_pagination,
    require_number,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from lookups import get_agreement, get_rti_record
from middleware import require_roles
from response import success_array, success_object
from services.calc import recompute_agreement_derived

bp = Blueprint("rti_records", __name__)


@bp.route("/apprenticeship/rti-records", methods=["POST"])
@require_roles("Sponsor", "TrainingCoordinator")
def create_rti_record():
    body = get_json_body()
    agreement_id = require_str(body, "agreement_id")
    course_code = require_str(body, "course_code")
    session_date = require_str(body, "session_date")
    instruction_hours = require_number(body, "instruction_hours")

    agreement = get_agreement(agreement_id)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "agreement_id": agreement_id,
            "course_code": course_code,
            "session_date": session_date,
            "instruction_hours": instruction_hours,
            "status": "RECORDED",
        }
    )
    db.rti_records[rec["id"]] = rec

    # Side effect: add to rti total and recompute completion eligibility (cascade).
    agreement["rti_hours_completed"] += instruction_hours
    recompute_agreement_derived(agreement)
    db.touch(agreement, bump_version=True)

    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/rti-records", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_rti_records():
    limit, offset = parse_pagination()
    items = list(db.rti_records.values())
    agreement_id = request.args.get("agreement_id")
    if agreement_id is not None:
        items = [r for r in items if r["agreement_id"] == agreement_id]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/rti-records/<rid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_rti_record_route(rid):
    rec = get_rti_record(rid)
    return success_object(serialize(rec))
