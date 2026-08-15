"""CorrectiveAction endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized, ALL_ROLES, ROLE_OFFICER, ROLE_COORDINATOR
from response import success_object
from services.core import (
    new_record, public, apply_changes, refresh_site, stale_reports_for_drill,
    ca_counter_changes, ca_is_overdue, corrective_actions_of,
)
from validate import get_body, reject_unknown, req_date, req_enum, req_str, opt_str
from routes.helpers import get_path, list_query

bp = Blueprint("actions", __name__)

PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@bp.post("/after-action-reviews/<rid>/corrective-actions")
def create_action(rid):
    authorized([ROLE_OFFICER])
    aar = get_path("after_action_reviews", rid)
    body = get_body()
    reject_unknown(body, ["description", "priority", "due_date", "assignee_name"])
    description = req_str(body, "description")
    priority = req_enum(body, "priority", PRIORITIES)
    due_date = req_date(body, "due_date")
    assignee = req_str(body, "assignee_name")

    # priority 5: review must be ACCEPTED
    if aar["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE,
                    "corrective actions may only open on an ACCEPTED review")

    rec = new_record("corrective_actions", {
        "aar_id": aar["id"],
        "description": description,
        "priority": priority,
        "due_date": due_date,
        "assignee_name": assignee,
        "status": "OPEN",
        "evidence_note": None,
        "is_overdue": False,
        "verified_by_user_id": None,
    })
    rec["is_overdue"] = ca_is_overdue(rec)
    apply_changes(aar, ca_counter_changes(aar["id"]))
    drill = db["drill_events"].get(aar["drill_event_id"])
    if drill is not None:
        refresh_site(drill["site_id"])
    return success_object(public(rec), 201)


@bp.get("/after-action-reviews/<rid>/corrective-actions")
def list_actions(rid):
    authorized(ALL_ROLES)
    get_path("after_action_reviews", rid)
    filters = {"aar_id": rid, "status": request.args.get("status")}
    return list_query("corrective_actions", filters)


@bp.post("/corrective-actions/<rid>/submit-verification")
def submit_verification(rid):
    authorized([ROLE_OFFICER])
    ca = get_path("corrective_actions", rid)
    body = get_body()
    reject_unknown(body, ["evidence_note"])
    evidence = req_str(body, "evidence_note")

    if ca["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_INVALID_STATE,
                    "action must be OPEN or REOPENED to submit verification")

    apply_changes(ca, {"status": "PENDING_VERIFICATION", "evidence_note": evidence})
    return success_object(public(ca))


@bp.post("/corrective-actions/<rid>/verify")
def verify_action(rid):
    caller = authorized([ROLE_COORDINATOR])
    ca = get_path("corrective_actions", rid)
    body = get_body()
    reject_unknown(body, ["decision", "note"])
    decision = req_enum(body, "decision", ["VERIFY", "REOPEN"])
    opt_str(body, "note")

    if ca["status"] != "PENDING_VERIFICATION":
        raise_error(ERR_INVALID_STATE,
                    "action must be PENDING_VERIFICATION to verify")

    aar = db["after_action_reviews"].get(ca["aar_id"])
    drill = db["drill_events"].get(aar["drill_event_id"]) if aar else None

    if decision == "VERIFY":
        apply_changes(ca, {
            "status": "VERIFIED",
            "verified_by_user_id": caller.user_id,
            "is_overdue": False,
        })
        # Cascade: review auto-closes when ACCEPTED with >= 1 action and all VERIFIED
        if aar is not None:
            changes = ca_counter_changes(aar["id"])
            if (aar["status"] == "ACCEPTED" and changes["ca_total_count"] >= 1
                    and all(c["status"] == "VERIFIED"
                            for c in corrective_actions_of(aar["id"]))):
                changes["status"] = "CLOSED"
            apply_changes(aar, changes)
            if aar["status"] == "CLOSED" and drill is not None \
                    and drill["status"] == "COMPLETED":
                apply_changes(drill, {"status": "CLOSED"})
                stale_reports_for_drill(drill["site_id"], drill["scheduled_date"])
    else:
        apply_changes(ca, {"status": "REOPENED", "is_overdue": ca_is_overdue(ca)})

    if drill is not None:
        refresh_site(drill["site_id"])
    return success_object(public(ca))
