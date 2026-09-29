"""Conflicts screening, waivers and the blocked-screening cascade (PRD 3.4)."""

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_CLIENT_COUNSEL,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
)
from response import created_response, object_response, paginated
from routes.matters import require_matter_client, require_not_suspended
from services import cascade, compute
from validation import opt_str, present, req_bool, req_enum, req_id, req_text_array

bp = Blueprint("screenings", __name__)

DECISION_OUTCOMES = ("CLEARED", "WAIVER_REQUIRED", "BLOCKED")
NON_TERMINAL = ("PENDING", "WAIVER_REQUIRED", "CLEARED")


@bp.route("/conflicts-screenings", methods=["POST"])
def create_screening():
    require_roles(ROLE_STAFFING_COORDINATOR)
    payload = body()

    # Rank 5 - body foreign keys.
    reviewer = None
    matter = None
    if present(payload, "reviewer_id") and isinstance(payload["reviewer_id"], str):
        reviewer = compute.get_reviewer(payload["reviewer_id"])
    if present(payload, "matter_id") and isinstance(payload["matter_id"], str):
        matter = compute.get_matter(payload["matter_id"])

    req_id(payload, "reviewer_id")
    req_id(payload, "matter_id")
    if reviewer is None:
        reviewer = compute.get_reviewer(payload["reviewer_id"])
    if matter is None:
        matter = compute.get_matter(payload["matter_id"])
    declared_adverse_parties = req_text_array(payload, "declared_adverse_parties",
                                              1, 200, allow_empty=True)

    require_not_suspended(matter)
    if reviewer["engagement_status"] == "REMOVED":
        raise ApiError("ERR_REVIEWER_REMOVED", "The reviewer has been removed.")
    for existing in compute.screenings_of_pair(reviewer["id"], matter["id"]):
        if existing["status"] in NON_TERMINAL:
            raise ApiError("ERR_SCREENING_ALREADY_OPEN",
                           "A non-terminal screening already exists for this pair.")

    row = base_row()
    row.update({
        "reviewer_id": reviewer["id"],
        "matter_id": matter["id"],
        "declared_adverse_parties": declared_adverse_parties,
        "status": "PENDING",
        "decision_note": None,
        "screened_at": None,
        "waiver_granted": False,
    })
    db.screenings[row["id"]] = row
    return created_response(compute.screening_out(row))


@bp.route("/conflicts-screenings/<screening_id>", methods=["GET"])
def read_screening(screening_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_CLIENT_COUNSEL)
    screening = compute.get_screening(screening_id)
    return object_response(compute.screening_out(screening))


@bp.route("/conflicts-screenings", methods=["GET"])
def list_screenings():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_CLIENT_COUNSEL)
    rows = by_creation(list(db.screenings.values()))
    reviewer_id = request.args.get("reviewer_id")
    matter_id = request.args.get("matter_id")
    status = request.args.get("status")
    if reviewer_id:
        rows = [r for r in rows if r["reviewer_id"] == reviewer_id]
    if matter_id:
        rows = [r for r in rows if r["matter_id"] == matter_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, compute.screening_out)


@bp.route("/conflicts-screenings/<screening_id>/decision", methods=["POST"])
def decide_screening(screening_id):
    require_roles(ROLE_STAFFING_COORDINATOR)
    screening = compute.get_screening(screening_id)
    matter = compute.get_matter(screening["matter_id"])
    reviewer = compute.get_reviewer(screening["reviewer_id"])
    payload = body()
    outcome = req_enum(payload, "outcome", DECISION_OUTCOMES)
    decision_note = opt_str(payload, "decision_note", 1, 2000, None)

    current = screening["status"]
    if current == "PENDING":
        pass
    elif current == "CLEARED" and outcome == "BLOCKED":
        pass
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "A screening in %s may not move to %s." % (current, outcome))

    if current == "PENDING" and outcome == "CLEARED":
        client = compute.get_client(matter["client_id"])
        if client["legal_name"] in screening["declared_adverse_parties"]:
            raise ApiError("ERR_INVALID_STATE",
                           "The instructing client is a declared adverse party.")

    require_not_suspended(matter)

    screening["screened_at"] = db.now_iso()
    screening["decision_note"] = decision_note
    screening["status"] = outcome
    touch(screening)

    if outcome == "CLEARED":
        cascade.clear_reviewer(reviewer)
        cascade.sync_matter_staffing(matter)
    elif outcome == "BLOCKED" and current == "CLEARED":
        cascade.blocked_screening_cascade(screening)
    return object_response(compute.screening_out(screening))


@bp.route("/conflicts-screenings/<screening_id>/waiver", methods=["POST"])
def rule_waiver(screening_id):
    require_roles(ROLE_CLIENT_COUNSEL)
    screening = compute.get_screening(screening_id)
    matter = compute.get_matter(screening["matter_id"])
    reviewer = compute.get_reviewer(screening["reviewer_id"])
    require_matter_client(matter)
    payload = body()
    granted = req_bool(payload, "granted")
    decision_note = opt_str(payload, "decision_note", 1, 2000, None)

    if screening["status"] != "WAIVER_REQUIRED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a WAIVER_REQUIRED screening may receive a waiver ruling.")

    screening["decision_note"] = decision_note
    if granted:
        screening["status"] = "CLEARED"
        screening["waiver_granted"] = True
        touch(screening)
        cascade.clear_reviewer(reviewer)
        cascade.sync_matter_staffing(matter)
    else:
        screening["status"] = "BLOCKED"
        touch(screening)
    return object_response(compute.screening_out(screening))
