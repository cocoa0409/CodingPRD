"""RequiredActionItem endpoints."""
from flask import Blueprint, request

from db import DB, clock_now
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404
from util import as_str, body, paginate, pagination, required, touch

bp = Blueprint("action_items", __name__)


def action_item_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


@bp.get("/accreditation/findings/<id>/action-items")
def list_finding_action_items(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    get_or_404("findings", id, "VisitFinding")
    limit, offset = pagination()
    rows = [a for a in DB["action_items"].values() if a["finding_id"] == id]
    rows.sort(key=lambda a: a["created_at"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([action_item_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/terms/<id>/action-items")
def list_term_action_items(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("terms", id, "AccreditationTerm")
    limit, offset = pagination()
    visit_ids = {v["id"] for v in DB["visits"].values() if v["term_id"] == id}
    finding_ids = {
        f["id"] for f in DB["findings"].values() if f["visit_id"] in visit_ids
    }
    rows = [a for a in DB["action_items"].values() if a["finding_id"] in finding_ids]
    rows.sort(key=lambda a: a["created_at"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([action_item_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/action-items/<id>")
def get_action_item(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    row = get_or_404("action_items", id, "RequiredActionItem")
    return ok(action_item_view(row))


@bp.post("/accreditation/action-items/<id>/submit-evidence")
def submit_evidence(id):
    user_id, _ = auth(["SchoolLeader"])
    item = get_or_404("action_items", id, "RequiredActionItem")
    data = body()
    # narrative is required by the endpoint spec
    as_str(required(data, "narrative"), "narrative")
    if item["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Action item must be OPEN or OVERDUE to submit evidence",
        )
    was_overdue = item["status"] == "OVERDUE"
    item["status"] = "SUBMITTED"
    # Track the actor so verify can enforce SoD, and mark pending-overdue.
    item["_last_submitter_user_id"] = user_id
    item["_pending_overdue_submission"] = was_overdue
    touch(item)
    return ok(action_item_view(item))


@bp.post("/accreditation/action-items/<id>/verify")
def verify_action_item(id):
    user_id, _ = auth(["Reviewer"])
    item = get_or_404("action_items", id, "RequiredActionItem")
    now = clock_now()
    if item["status"] == "SUBMITTED":
        # On-time verification required.
        if now > item["_due_date_dt"]:
            raise ApiError(
                "ERR_TEMPORAL_WINDOW_VIOLATION",
                422,
                "Verification is past the due_date",
            )
        # SoD: reviewer may not be the same individual who submitted.
        if item.get("_last_submitter_user_id") == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                422,
                "Reviewer may not verify their own submission",
            )
        item["status"] = "VERIFIED"
        item["verified_by_user_id"] = user_id
        item["_pending_overdue_submission"] = False
        touch(item)
        return ok(action_item_view(item))
    if item["status"] == "OVERDUE":
        # Verify directly from OVERDUE requires a preceding submit-evidence from OVERDUE.
        if not item.get("_pending_overdue_submission"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "OVERDUE verification requires a preceding submit-evidence",
            )
        if item.get("_last_submitter_user_id") == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                422,
                "Reviewer may not verify their own submission",
            )
        item["status"] = "VERIFIED"
        item["verified_by_user_id"] = user_id
        item["_pending_overdue_submission"] = False
        touch(item)
        # Late verification consequence: system -> ON_PROBATION.
        finding = DB["findings"].get(item["finding_id"])
        if finding is not None:
            visit = DB["visits"].get(finding["visit_id"])
            if visit is not None:
                term = DB["terms"].get(visit["term_id"])
                if term is not None:
                    system = DB["systems"].get(term["system_id"])
                    if system is not None and system["accreditation_status"] != "ON_PROBATION":
                        system["accreditation_status"] = "ON_PROBATION"
                        touch(system)
        return ok(action_item_view(item))
    raise ApiError(
        "ERR_INVALID_STATE",
        409,
        "Action item must be SUBMITTED or OVERDUE to verify",
    )


@bp.post("/accreditation/action-items/<id>/return")
def return_action_item(id):
    auth(["Reviewer"])
    item = get_or_404("action_items", id, "RequiredActionItem")
    if item["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Action item must be SUBMITTED")
    item["status"] = "OPEN"
    item["_pending_overdue_submission"] = False
    touch(item)
    return ok(action_item_view(item))


@bp.post("/accreditation/action-items/<id>/waive")
def waive_action_item(id):
    auth(["AccreditationCommission"])
    item = get_or_404("action_items", id, "RequiredActionItem")
    if item["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Action item must be OPEN to waive")
    if clock_now() > item["_due_date_dt"]:
        raise ApiError(
            "ERR_TEMPORAL_WINDOW_VIOLATION",
            422,
            "Cannot waive after the due_date",
        )
    item["status"] = "WAIVED"
    touch(item)
    return ok(action_item_view(item))
