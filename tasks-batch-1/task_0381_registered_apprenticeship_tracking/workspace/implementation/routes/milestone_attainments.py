"""Milestone attainment endpoints + approve/reject/resubmit (PRD §3.6, §3.7)."""
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
from lookups import get_agreement, get_attainment, get_milestone
from middleware import require_roles
from response import success_array, success_object
from services.calc import recompute_agreement_derived

bp = Blueprint("milestone_attainments", __name__)


@bp.route("/apprenticeship/milestone-attainments", methods=["POST"])
@require_roles("Sponsor")
def create_attainment():
    body = get_json_body()
    agreement_id = require_str(body, "agreement_id")
    milestone_id = require_str(body, "milestone_id")
    attained_on = require_str(body, "attained_on")

    # FK existence (priority 4).
    agreement = get_agreement(agreement_id)
    milestone = get_milestone(milestone_id)

    # Priority 8: milestone belongs to the agreement's program.
    if milestone["program_id"] != agreement["program_id"]:
        raise err(
            "ERR_MILESTONE_PROGRAM_MISMATCH",
            "Milestone does not belong to the agreement's program.",
        )

    # Priority 9: attained_on >= agreement.start_date.
    if attained_on < agreement["start_date"]:
        raise err("ERR_DATE_BEFORE_AGREEMENT_START", "attained_on is before the agreement start_date.")

    # Priority 17: at most one SUBMITTED/APPROVED per (agreement, milestone).
    if any(
        a["agreement_id"] == agreement_id
        and a["milestone_id"] == milestone_id
        and a["status"] in ("SUBMITTED", "APPROVED")
        for a in db.milestone_attainments.values()
    ):
        raise err(
            "ERR_DUPLICATE_RESOURCE",
            "An outstanding attainment already exists for this agreement and milestone.",
        )

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "agreement_id": agreement_id,
            "milestone_id": milestone_id,
            "attained_on": attained_on,
            "status": "SUBMITTED",
        }
    )
    db.milestone_attainments[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/milestone-attainments", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_attainments():
    limit, offset = parse_pagination()
    items = list(db.milestone_attainments.values())
    for key in ("agreement_id", "milestone_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/milestone-attainments/<aid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_attainment_route(aid):
    rec = get_attainment(aid)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/milestone-attainments/<aid>/approve", methods=["POST"])
@require_roles("TrainingCoordinator")
def approve_attainment(aid):
    rec = get_attainment(aid)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_ATTAINMENT_NOT_SUBMITTED", "Attainment must be SUBMITTED to approve.")
    agreement = db.agreements[rec["agreement_id"]]
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Parent agreement must be ACTIVE to approve.")

    rec["status"] = "APPROVED"
    agreement["milestones_attained_count"] += 1
    recompute_agreement_derived(agreement)

    db.touch(rec, bump_version=True)
    db.touch(agreement, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/milestone-attainments/<aid>/reject", methods=["POST"])
@require_roles("TrainingCoordinator")
def reject_attainment(aid):
    rec = get_attainment(aid)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_ATTAINMENT_NOT_SUBMITTED", "Attainment must be SUBMITTED to reject.")
    rec["status"] = "REJECTED"
    # Rejection re-runs the cascade; APPROVED count is unchanged so derived state
    # is stable, but the PRD lists rejection as a trigger. Only bump the agreement
    # if a derived value actually moves.
    agreement = db.agreements[rec["agreement_id"]]
    changed = recompute_agreement_derived(agreement)
    db.touch(rec, bump_version=True)
    if changed:
        db.touch(agreement, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/milestone-attainments/<aid>/resubmit", methods=["POST"])
@require_roles("Sponsor")
def resubmit_attainment(aid):
    rec = get_attainment(aid)
    if rec["status"] != "REJECTED":
        raise err("ERR_ATTAINMENT_NOT_REJECTED", "Attainment must be REJECTED to resubmit.")
    rec["status"] = "SUBMITTED"
    # Resubmission re-runs the cascade (PRD §3.7 lists resubmit as a trigger);
    # only bump the agreement if a derived value actually moves.
    agreement = db.agreements[rec["agreement_id"]]
    changed = recompute_agreement_derived(agreement)
    db.touch(rec, bump_version=True)
    if changed:
        db.touch(agreement, bump_version=True)
    return success_object(serialize(rec))
