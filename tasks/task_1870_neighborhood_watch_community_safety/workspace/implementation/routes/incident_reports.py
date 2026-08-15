"""IncidentReport routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles, get_auth
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("incident_reports", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")

VALID_CATEGORIES = {"SUSPICIOUS_ACTIVITY", "PROPERTY_CRIME", "VANDALISM", "NOISE", "TRAFFIC", "OTHER"}


def _serialize_report(r):
    return {
        "id": r["id"],
        "block_id": r["block_id"],
        "reporter_member_id": r["reporter_member_id"],
        "category": r["category"],
        "occurred_at": r["occurred_at"],
        "severity": r["severity"],
        "review_status": r["review_status"],
        "corroboration_weight": r["corroboration_weight"],
        "shared_with_liaison": r["shared_with_liaison"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/watch/incident-reports", methods=["POST"])
def create_report():
    user_id, role = require_roles("Member", "BlockCaptain")
    body = request.get_json(force=True, silent=True) or {}

    block_id = body.get("block_id")
    reporter_member_id = body.get("reporter_member_id")
    category = body.get("category")
    occurred_at = body.get("occurred_at")
    severity = body.get("severity")

    # Field-level validation
    if not category or category not in VALID_CATEGORIES:
        raise errors.invalid_request("Invalid category")
    if severity is None or not isinstance(severity, int) or severity < 1 or severity > 5:
        raise errors.invalid_request("severity must be an integer in [1,5]")
    if not occurred_at:
        raise errors.invalid_request("occurred_at is required")
    try:
        occurred_dt = db.parse_iso(occurred_at)
    except Exception:
        raise errors.invalid_request("occurred_at is not valid ISO-8601")

    # occurred_at must be <= current logical clock
    if occurred_dt > db.get_clock():
        raise errors.invalid_request("occurred_at cannot be in the future")

    # Existence
    b = db.blocks.get(block_id) if block_id else None
    if not b:
        raise errors.not_found("Block not found")
    m = db.members.get(reporter_member_id) if reporter_member_id else None
    if not m:
        raise errors.not_found("Member not found")

    # Referential integrity: reporter must be ACTIVE member of the block's group
    if m["membership_status"] != "ACTIVE":
        raise errors.referential("Reporter is not an ACTIVE member")
    if m["watch_group_id"] != b["watch_group_id"]:
        raise errors.referential("Reporter does not belong to the block's watch group")

    record = {
        "block_id": block_id,
        "reporter_member_id": reporter_member_id,
        "category": category,
        "occurred_at": occurred_at,
        "severity": severity,
        "review_status": "SUBMITTED",
        "corroboration_weight": 0,
        "shared_with_liaison": False,
    }
    svc.stamp_new(record)
    db.incident_reports[record["id"]] = record
    return success_object(_serialize_report(record), 201)


@bp.route("/watch/incident-reports", methods=["GET"])
def list_reports():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.incident_reports.values())

    # Filters
    bid = request.args.get("block_id")
    if bid:
        items = [r for r in items if r["block_id"] == bid]
    rid = request.args.get("reporter_member_id")
    if rid:
        items = [r for r in items if r["reporter_member_id"] == rid]
    rs = request.args.get("review_status")
    if rs:
        items = [r for r in items if r["review_status"] == rs]
    cat = request.args.get("category")
    if cat:
        items = [r for r in items if r["category"] == cat]

    items.sort(key=lambda r: r["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_report(r) for r in items], limit, offset, total)


@bp.route("/watch/incident-reports/<id>", methods=["GET"])
def get_report(id):
    user_id, role = require_roles(*ALL_ROLES)
    r = db.incident_reports.get(id)
    if not r:
        raise errors.not_found("IncidentReport not found")

    # Lazy agreement expiry sweep
    block = db.blocks.get(r["block_id"])
    if block:
        svc.sweep_agreement_expiry(block["watch_group_id"])

    # LiaisonOfficer data-share gate
    if role == "LiaisonOfficer":
        if not r["shared_with_liaison"]:
            gid = block["watch_group_id"] if block else None
            if not gid or not svc.has_active_agreement(gid, {"INCIDENT_SUMMARIES", "FULL"}):
                raise errors.data_share_required("Liaison read requires shared report or ACTIVE agreement")

    return success_object(_serialize_report(r))


@bp.route("/watch/incident-reports/<id>/begin-review", methods=["POST"])
def begin_review(id):
    user_id, role = require_roles("ProgramCoordinator")
    r = db.incident_reports.get(id)
    if not r:
        raise errors.not_found("IncidentReport not found")

    if r["review_status"] != "SUBMITTED":
        raise errors.invalid_state("Report is not SUBMITTED")

    # Segregation of duties
    if user_id == r["reporter_member_id"]:
        raise errors.segregation("Cannot review own report")

    r["review_status"] = "UNDER_REVIEW"
    svc.touch(r)
    return success_object(_serialize_report(r))


@bp.route("/watch/incident-reports/<id>/request-info", methods=["POST"])
def request_info(id):
    user_id, role = require_roles("ProgramCoordinator")
    r = db.incident_reports.get(id)
    if not r:
        raise errors.not_found("IncidentReport not found")

    if r["review_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Report is not UNDER_REVIEW")

    r["review_status"] = "NEEDS_INFO"
    svc.touch(r)
    return success_object(_serialize_report(r))


@bp.route("/watch/incident-reports/<id>/resubmit", methods=["POST"])
def resubmit(id):
    user_id, role = require_roles("Member", "BlockCaptain")
    r = db.incident_reports.get(id)
    if not r:
        raise errors.not_found("IncidentReport not found")

    if r["review_status"] != "NEEDS_INFO":
        raise errors.invalid_state("Report is not NEEDS_INFO")

    # Reporter-only check
    if user_id != r["reporter_member_id"]:
        raise errors.reporter_only()

    r["review_status"] = "UNDER_REVIEW"
    svc.touch(r)
    return success_object(_serialize_report(r))


@bp.route("/watch/incident-reports/<id>/corroborate", methods=["POST"])
def corroborate(id):
    user_id, role = require_roles("LiaisonOfficer")
    r = db.incident_reports.get(id)
    if not r:
        raise errors.not_found("IncidentReport not found")

    if r["review_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Report is not UNDER_REVIEW")

    # Data share gate
    block = db.blocks.get(r["block_id"])
    if not block:
        raise errors.not_found("Block not found")
    gid = block["watch_group_id"]
    if not svc.has_active_agreement(gid, {"INCIDENT_SUMMARIES", "FULL"}):
        raise errors.data_share_required("Corroboration requires an ACTIVE DataShareAgreement")

    r["review_status"] = "CORROBORATED"
    r["shared_with_liaison"] = True
    svc.compute_corroboration_weight(r)
    svc.touch(r)

    # Cascade: block heat + last_incident_at
    svc.recompute_block_heat(r["block_id"])

    # Participation score recompute
    svc.recompute_posture(gid)

    return success_object(_serialize_report(r))


@bp.route("/watch/incident-reports/<id>/dismiss", methods=["POST"])
def dismiss(id):
    user_id, role = require_roles("ProgramCoordinator")
    r = db.incident_reports.get(id)
    if not r:
        raise errors.not_found("IncidentReport not found")

    if r["review_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Report is not UNDER_REVIEW")

    # Segregation of duties
    if user_id == r["reporter_member_id"]:
        raise errors.segregation("Cannot dismiss own report")

    r["review_status"] = "DISMISSED"
    svc.touch(r)
    return success_object(_serialize_report(r))


@bp.route("/watch/incident-reports/<id>/clear", methods=["POST"])
def clear(id):
    user_id, role = require_roles("LiaisonOfficer")
    r = db.incident_reports.get(id)
    if not r:
        raise errors.not_found("IncidentReport not found")

    if r["review_status"] != "CORROBORATED":
        raise errors.invalid_state("Report is not CORROBORATED")

    r["review_status"] = "CLEARED"
    svc.compute_corroboration_weight(r)
    svc.touch(r)

    # Cascade: block heat recompute
    svc.recompute_block_heat(r["block_id"])

    return success_object(_serialize_report(r))
