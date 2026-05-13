"""Complaint lifecycle and corrective actions."""

from flask import g

from clock import clock
from db import bump_version, common_fields_create, db, touch
from errors import (
    ERR_CONFLICT_OF_INTEREST,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from services.audit import append_audit
from services.project import get_project_or_404
from services.supplier import get_supplier_or_ref_404


COMPLAINT_SUBJECTS = {"PRESCREEN_RESULT", "EVALUATION", "AWARD", "CONTRACT"}
CORRECTIVE_ACTIONS = {"REOPEN_PRESCREEN", "REOPEN_EVALUATION", "REVOKE_AWARD", "FREEZE_PROJECT"}


def get_complaint_or_404(complaint_id: str) -> dict:
    c = db.complaints.get(complaint_id)
    if not c:
        raise_error(ERR_NOT_FOUND, f"complaint '{complaint_id}' not found")
    return c


def file_complaint(project_id: str, body: dict):
    project = get_project_or_404(project_id)
    csi = body.get("complainant_supplier_id")
    if not isinstance(csi, str) or not csi:
        raise_error(ERR_VALIDATION, "complainant_supplier_id is required")
    actor_id = getattr(g, "user_id", None)
    if actor_id != csi:
        raise_error(ERR_FORBIDDEN, "supplier may only file complaints on its own behalf")
    get_supplier_or_ref_404(csi)
    subject = body.get("subject")
    if subject not in COMPLAINT_SUBJECTS:
        raise_error(ERR_VALIDATION, "subject invalid")
    narrative = body.get("narrative")
    if not isinstance(narrative, str) or not narrative:
        raise_error(ERR_VALIDATION, "narrative must be non-empty string")
    c = {
        "id": db.new_id(),
        **common_fields_create(),
        "project_id": project_id,
        "complainant_supplier_id": csi,
        "subject": subject,
        "narrative": narrative,
        "complaint_status": "SUBMITTED",
        "decision_at": None,
        "corrective_action": None,
    }
    db.complaints[c["id"]] = c
    return c


def accept_complaint(complaint_id: str):
    c = get_complaint_or_404(complaint_id)
    if c["complaint_status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "complaint must be SUBMITTED")
    c["complaint_status"] = "UNDER_REVIEW"
    bump_version(c)
    append_audit("COMPLAINT", c["id"], "COMPLAINT_ACCEPTED", {
        "project_id": c["project_id"],
        "complaint_id": c["id"],
    })
    return c


def _coi_violation_complaint(project_id: str) -> bool:
    """For uphold/dismiss: the actor (Regulator) cannot also be a Supplier on this project."""
    actor_id = getattr(g, "user_id", None)
    actor_role = getattr(g, "user_role", None)
    if actor_id is None:
        return False
    # Supplier cannot be Regulator: if actor_id matches any supplier_id of a bid/complaint on this project, that's CoI.
    if actor_role != "Regulator":
        return False
    # Check if actor has ever appeared as a Supplier on this project's audit log (rare) or as a bidder
    for b in db.bids.values():
        if b["project_id"] == project_id and b["supplier_id"] == actor_id:
            return True
    for cm in db.complaints.values():
        if cm["project_id"] == project_id and cm["complainant_supplier_id"] == actor_id:
            return True
    return False


def uphold_complaint(complaint_id: str, body: dict):
    c = get_complaint_or_404(complaint_id)
    if c["complaint_status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "complaint must be UNDER_REVIEW to uphold")
    ca = body.get("corrective_action")
    if ca not in CORRECTIVE_ACTIONS:
        raise_error(ERR_VALIDATION, "corrective_action invalid")
    if _coi_violation_complaint(c["project_id"]):
        raise_error(ERR_CONFLICT_OF_INTEREST, "actor has CoI on this project")
    project = get_project_or_404(c["project_id"])
    c["complaint_status"] = "UPHELD"
    c["corrective_action"] = ca
    c["decision_at"] = clock.now_iso()
    bump_version(c)
    # Apply corrective action
    if ca == "REOPEN_PRESCREEN":
        if project["project_status"] not in {"BIDDING_OPEN", "BIDDING_CLOSED", "EVALUATING"}:
            raise_error(ERR_INVALID_STATE, "REOPEN_PRESCREEN only valid for BIDDING_OPEN/BIDDING_CLOSED/EVALUATING")
        project["project_status"] = "PRESCREEN_OPEN"
        bump_version(project)
    elif ca == "REOPEN_EVALUATION":
        if project["project_status"] != "EVALUATING":
            raise_error(ERR_INVALID_STATE, "REOPEN_EVALUATION only valid for EVALUATING")
        cid = db.committee_by_project.get(project["id"])
        if cid:
            comm = db.committees[cid]
            comm["committee_status"] = "EVALUATING"
    elif ca == "REVOKE_AWARD":
        project["project_status"] = "FROZEN"
        project["frozen_reason"] = "COMPLAINT_UPHELD"
        bump_version(project)
        award_id = db.award_by_project.get(project["id"])
        if award_id:
            a = db.awards[award_id]
            a["award_status"] = "REVOKED"
            bump_version(a)
            winning_bid_id = a.get("winning_bid_id")
            wb = db.bids.get(winning_bid_id) if winning_bid_id else None
            if wb:
                wb["bid_status"] = "DISQUALIFIED"
                bump_version(wb)
            # parent PlanItem reverts EXECUTED status (only if no Contract has gone to ACTIVE)
            # PRD: "reverts the parent plan item's EXECUTED status because a contract is now precluded by the award revocation."
            item = db.plan_items.get(project["plan_item_id"])
            if item and item["item_status"] == "EXECUTED":
                item["item_status"] = "PUBLISHED"
                bump_version(item)
        # tender becomes SUPERSEDED (PRD §3.5 says SUPERSEDED is reached "when an award against the project is revoked")
        doc_id = db.tender_by_project.get(project["id"])
        if doc_id:
            doc = db.tender_documents[doc_id]
            doc["doc_status"] = "SUPERSEDED"
            touch(doc)
    elif ca == "FREEZE_PROJECT":
        project["project_status"] = "FROZEN"
        project["frozen_reason"] = "COMPLAINT_UPHELD"
        bump_version(project)
    append_audit("COMPLAINT", c["id"], "COMPLAINT_DECIDED", {
        "project_id": c["project_id"],
        "complaint_id": c["id"],
        "corrective_action": ca,
    })
    return c


def dismiss_complaint(complaint_id: str):
    c = get_complaint_or_404(complaint_id)
    if c["complaint_status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "complaint must be UNDER_REVIEW to dismiss")
    if _coi_violation_complaint(c["project_id"]):
        raise_error(ERR_CONFLICT_OF_INTEREST, "actor has CoI on this project")
    c["complaint_status"] = "DISMISSED"
    c["decision_at"] = clock.now_iso()
    bump_version(c)
    append_audit("COMPLAINT", c["id"], "COMPLAINT_DECIDED", {
        "project_id": c["project_id"],
        "complaint_id": c["id"],
        "corrective_action": None,
    })
    return c


def withdraw_complaint(complaint_id: str):
    c = get_complaint_or_404(complaint_id)
    actor_id = getattr(g, "user_id", None)
    if actor_id != c["complainant_supplier_id"]:
        raise_error(ERR_FORBIDDEN, "only the complainant supplier may withdraw")
    if c["complaint_status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "complaint must be SUBMITTED to withdraw")
    c["complaint_status"] = "WITHDRAWN"
    bump_version(c)
    return c
