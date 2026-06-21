"""Dispute routes: raise (freeze cascade), fetch, list, resolve (cascade)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles
from services import common, lookups

bp = Blueprint("disputes", __name__)

SUBJECT_TYPES = {"DRAW", "CHANGE_ORDER"}
RAISED_BY = {"HOMEOWNER", "CONTRACTOR"}
RESOLUTIONS = {"UPHELD", "OVERTURNED"}


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    user_id, role = require_roles("Homeowner", "Contractor")
    body = common.get_body()
    project_id = common.as_str(common.require_field(body, "project_id"), "project_id")
    subject_type = common.as_enum(
        common.require_field(body, "subject_type"), "subject_type", SUBJECT_TYPES)
    subject_id = common.as_str(common.require_field(body, "subject_id"), "subject_id")
    raised_by = common.as_enum(common.require_field(body, "raised_by"), "raised_by", RAISED_BY)
    reason = common.as_str(common.require_field(body, "reason"), "reason")

    # existence
    project = lookups.get_project(project_id)
    draw = lookups.get_draw(subject_id)
    if draw["project_id"] != project_id:
        raise errors.not_found("Subject draw does not belong to the project.")

    # ownership
    if role == "Homeowner" and project["homeowner_id"] != user_id:
        raise errors.not_owner("Homeowner does not own this project.")
    if role == "Contractor" and draw["contractor_id"] != user_id:
        raise errors.not_owner("Contractor does not own this draw.")

    # state: project IN_PROGRESS; draw REQUESTED or APPROVED
    if project["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Project must be IN_PROGRESS to raise a dispute.")
    if draw["status"] not in ("REQUESTED", "APPROVED"):
        raise errors.invalid_state("Subject draw must be REQUESTED or APPROVED to dispute.")

    rec = {
        "project_id": project_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "raised_by": raised_by,
        "reason": reason,
        "resolution": None,
        "status": "OPEN",
        # remember the pre-dispute draw status for OVERTURNED retainage handling
        "_draw_status_before": draw["status"],
    }
    common.stamp_new(rec)
    db.disputes[rec["id"]] = rec

    # freeze cascade
    project["status"] = "DISPUTED"
    common.touch(project)
    draw["status"] = "DISPUTED"
    common.touch(draw)
    milestone = lookups.get_milestone(draw["milestone_id"])
    milestone["status"] = "DISPUTED"
    common.touch(milestone)

    return response.success(common.public(rec), 201)


@bp.route("/disputes/<rid>", methods=["GET"])
def get_dispute(rid):
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    rec = lookups.get_dispute(rid)
    return response.success(common.public(rec), 200)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    items = list(db.disputes.values())
    for field in ("project_id", "subject_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [d for d in items if d.get(field) == val]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


@bp.route("/disputes/<rid>/resolve", methods=["POST"])
def resolve_dispute(rid):
    require_roles("PlatformAdmin")
    dispute = lookups.get_dispute(rid)
    body = common.get_body()
    resolution = common.as_enum(
        common.require_field(body, "resolution"), "resolution", RESOLUTIONS)
    if dispute["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN dispute can be resolved.")

    project = lookups.get_project(dispute["project_id"])
    draw = lookups.get_draw(dispute["subject_id"])
    milestone = lookups.get_milestone(draw["milestone_id"])
    escrow = lookups.escrow_for_project(dispute["project_id"])

    dispute["status"] = "RESOLVED"
    dispute["resolution"] = resolution

    if resolution == "UPHELD":
        draw["status"] = "APPROVED"
        common.touch(draw)
        milestone["status"] = "APPROVED"
        common.touch(milestone)
    else:  # OVERTURNED
        draw["status"] = "REJECTED"
        common.touch(draw)
        milestone["status"] = "PENDING"
        common.touch(milestone)
        # void conditional waiver
        if draw["lien_waiver_id"]:
            waiver = db.lien_waivers.get(draw["lien_waiver_id"])
            if waiver is not None:
                waiver["status"] = "VOIDED"
                common.touch(waiver)
        # if the draw had been APPROVED before dispute: return retainage hold
        if dispute.get("_draw_status_before") == "APPROVED" and escrow is not None:
            escrow["retained_cents"] -= draw["retainage_cents"]
            escrow["available_cents"] += draw["retainage_cents"]
            common.touch(escrow)

    project["status"] = "IN_PROGRESS"
    common.touch(project)
    common.touch(dispute)
    return response.success(common.public(dispute), 200)
