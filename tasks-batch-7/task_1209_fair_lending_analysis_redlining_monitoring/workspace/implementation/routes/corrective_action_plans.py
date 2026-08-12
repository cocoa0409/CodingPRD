"""Corrective action plans."""
from datetime import date

from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_request, invalid_state
from middleware import (
    body, check_int, get_or_404, list_page, occ_check, require_field, require_roles,
)
from response import success_list, success_obj
from services.cap import allocate_pool

bp = Blueprint("corrective_action_plans", __name__)

ROLES = (
    "FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector",
    "RemediationSpecialist",
)
TERMINAL = ("COMPLETED", "SUPERSEDED", "CANCELLED")
DIRECTOR_POOL_THRESHOLD = 25000000


@bp.post("/fair-lending/corrective-action-plans")
@require_roles("FairLendingAnalyst")
def create_cap():
    data = body()
    finding_id = require_field(data, "finding_id")
    title = require_field(data, "title")
    pool_cents = check_int(require_field(data, "pool_cents"), "pool_cents")
    if pool_cents < 0:
        raise invalid_request("pool_cents must be >= 0")
    due_date = require_field(data, "due_date")
    finding = get_or_404("findings", finding_id, "DisparityFinding")
    # OCC on the parent finding version.
    occ_check(data, "expected_finding_version", finding["version"])
    if finding["status"] != "SUBSTANTIATED":
        raise invalid_state("CAPs may be drafted only for SUBSTANTIATED findings")
    # At most one active (SUBMITTED/EXECUTING/OVERDUE) CAP per finding.
    for c in db.STORES["caps"].values():
        if c["finding_id"] == finding["id"] and c["status"] in (
            "SUBMITTED", "EXECUTING", "OVERDUE",
        ):
            raise err(
                "ERR_CAP_ACTIVE",
                "A CAP in SUBMITTED/EXECUTING/OVERDUE already exists for the finding",
            )
    # Drafting supersedes the finding's prior DRAFT/RETURNED plans.
    for c in db.STORES["caps"].values():
        if c["finding_id"] == finding["id"] and c["status"] in ("DRAFT", "RETURNED"):
            c["status"] = "SUPERSEDED"
            db.touch(c)
    rec = db.new_record(
        {
            "finding_id": finding["id"],
            "title": title,
            "pool_cents": pool_cents,
            "remaining_cents": pool_cents,
            "disbursed_cents": 0,
            "due_date": due_date,
            "status": "DRAFT",
            "created_by_user_id": g.user_id,
            "approved_by_user_id": None,
            "approved_at": None,
        }
    )
    db.STORES["caps"][rec["id"]] = rec
    db.touch(finding)
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/corrective-action-plans")
@require_roles(*ROLES)
def list_caps():
    page, total, limit, offset = list_page(
        "caps",
        {"finding_id": request.args.get("finding_id"), "status": request.args.get("status")},
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/corrective-action-plans/<capId>")
@require_roles(*ROLES)
def get_cap(capId):
    rec = get_or_404("caps", capId, "CorrectiveActionPlan")
    return success_obj(db.public(rec))


def _load(capId):
    rec = get_or_404("caps", capId, "CorrectiveActionPlan")
    return rec


def _terminal_guard(rec):
    if rec["status"] in TERMINAL:
        raise already_terminal("CorrectiveActionPlan is in terminal state %s" % rec["status"])


@bp.post("/fair-lending/corrective-action-plans/<capId>/submit")
@require_roles("FairLendingAnalyst")
def submit_cap(capId):
    rec = _load(capId)
    _terminal_guard(rec)
    if rec["status"] != "DRAFT":
        raise invalid_state("CorrectiveActionPlan is not in DRAFT status")
    rec["status"] = "SUBMITTED"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/corrective-action-plans/<capId>/approve")
@require_roles("FairLendingOfficer", "ComplianceDirector")
def approve_cap(capId):
    rec = _load(capId)
    _terminal_guard(rec)
    if rec["status"] != "SUBMITTED":
        raise invalid_state("CorrectiveActionPlan is not in SUBMITTED status")
    finding = db.STORES["findings"].get(rec["finding_id"])
    if finding is None:
        raise err("ERR_NOT_FOUND", "DisparityFinding does not exist")
    if finding["status"] != "SUBSTANTIATED":
        raise invalid_state("Linked finding is not SUBSTANTIATED")
    # Conditional authority: high-value pools require the ComplianceDirector.
    if rec["pool_cents"] >= DIRECTOR_POOL_THRESHOLD and g.role != "ComplianceDirector":
        raise err(
            "ERR_DIRECTOR_APPROVAL_REQUIRED",
            "pool_cents >= 25000000 requires ComplianceDirector approval",
        )
    rec["status"] = "EXECUTING"
    rec["approved_by_user_id"] = g.user_id
    rec["approved_at"] = db.now_iso()
    # Remediation waterfall: one AUTO_ALLOCATED PENDING payment per harmed
    # application; residual applied to the first entry.
    allocate_pool(rec, finding)
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/corrective-action-plans/<capId>/return")
@require_roles("FairLendingOfficer", "ComplianceDirector")
def return_cap(capId):
    rec = _load(capId)
    _terminal_guard(rec)
    if rec["status"] != "SUBMITTED":
        raise invalid_state("CorrectiveActionPlan is not in SUBMITTED status")
    rec["status"] = "RETURNED"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/corrective-action-plans/<capId>/revise")
@require_roles("FairLendingAnalyst")
def revise_cap(capId):
    rec = _load(capId)
    _terminal_guard(rec)
    if rec["status"] != "RETURNED":
        raise invalid_state("CorrectiveActionPlan is not in RETURNED status")
    rec["status"] = "DRAFT"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/corrective-action-plans/<capId>/extend")
@require_roles("ComplianceDirector")
def extend_cap(capId):
    rec = _load(capId)
    _terminal_guard(rec)
    if rec["status"] != "OVERDUE":
        raise invalid_state("CorrectiveActionPlan is not in OVERDUE status")
    data = body()
    new_due_date = require_field(data, "new_due_date")
    try:
        new_due = date.fromisoformat(new_due_date)
    except (TypeError, ValueError):
        raise invalid_request("new_due_date must be an ISO date")
    if new_due <= db.now_dt().date():
        raise invalid_request("new_due_date must be later than the current logical date")
    rec["due_date"] = new_due_date
    rec["status"] = "EXECUTING"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/corrective-action-plans/<capId>/cancel")
@require_roles("FairLendingAnalyst", "ComplianceDirector")
def cancel_cap(capId):
    rec = _load(capId)
    _terminal_guard(rec)
    if rec["status"] not in ("DRAFT", "RETURNED"):
        raise invalid_state("Only DRAFT or RETURNED plans can be cancelled")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success_obj(db.public(rec))
