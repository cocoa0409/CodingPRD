"""BranchInspection endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INSPECTION_ALREADY_OPEN,
    ERR_INSPECTION_GAP_VIOLATION,
    ERR_INSPECTION_INVALID_STATE,
    ERR_FINDINGS_STILL_OPEN,
    ERR_STALE_BRANCH_VERSION,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.branch import (
    branch_inspections, last_closed_inspection, recompute_branch,
    recompute_inspection_counts,
)
from services.core import new_record, public, touch
from util import add_days, clock_ts, parse_date, today
from validate import (
    get_body, opt_version, req_date, req_str, require_path_resource, require_ref,
    soft_date, soft_int,
)

bp = Blueprint("inspections", __name__)

MIN_GAP_DAYS = 300
OPEN_INSPECTION_STATUSES = ("SCHEDULED", "IN_PROGRESS", "AWAITING_REMEDIATION")


@bp.post("/inspections")
def create_inspection():
    authorized(["ComplianceAnalyst"])
    body = get_body()
    # Priority 3: FK existence
    branch = require_ref("branches", body.get("branch_id"), "branch_id")
    # Priority 3.5: OCC on BranchOffice.version (runs before all business checks)
    expected = body.get("expected_branch_version")
    if branch is not None and soft_int(expected) and expected != branch["version"]:
        raise_error(ERR_STALE_BRANCH_VERSION,
                    "expected_branch_version does not match the branch's current version")
    scheduled_raw = body.get("scheduled_date")
    if branch is not None:
        # Priority 7a: minimum 300-day gap vs the last CLOSED inspection
        last = last_closed_inspection(branch["id"])
        if last is not None and last.get("completed_date") and soft_date(scheduled_raw):
            earliest = add_days(parse_date(last["completed_date"]), MIN_GAP_DAYS)
            if parse_date(scheduled_raw) < earliest:
                raise_error(ERR_INSPECTION_GAP_VIOLATION,
                            "scheduled_date is less than 300 days after the last CLOSED "
                            "inspection's completed_date")
        # Priority 7b: at most one non-CLOSED inspection per branch
        for i in branch_inspections(branch["id"]):
            if i["status"] in OPEN_INSPECTION_STATUSES:
                raise_error(ERR_INSPECTION_ALREADY_OPEN,
                            "branch already has a non-CLOSED inspection")
    # Priority 8: schema
    branch_id = req_str(body, "branch_id")
    scheduled_date = req_date(body, "scheduled_date")
    opt_version(body, "expected_branch_version")
    if branch is None:
        raise_error(ERR_VALIDATION, "missing or invalid field: branch_id")

    rec = new_record("inspections", {
        "branch_id": branch_id,
        "scheduled_date": scheduled_date,
        "started_at": None,
        "completed_date": None,
        "open_findings_count": 0,
        "high_severity_open_count": 0,
        "status": "SCHEDULED",
    })
    touch(branch)  # scheduling pins a branch version bump
    return success_object(public(rec), status=201)


@bp.get("/inspections")
def list_inspections():
    return list_response("inspections", filters={
        "branch_id": request.args.get("branch_id"),
        "status": request.args.get("status"),
    })


@bp.get("/inspections/<rid>")
def get_inspection(rid):
    return get_one("inspections", rid)


@bp.post("/inspections/<rid>/start")
def start_inspection(rid):
    authorized(["ComplianceAnalyst"])
    insp = require_path_resource("inspections", rid)
    if insp["status"] != "SCHEDULED":
        raise_error(ERR_INSPECTION_INVALID_STATE,
                    "only a SCHEDULED inspection can be started")
    insp["status"] = "IN_PROGRESS"
    insp["started_at"] = clock_ts()
    touch(insp)
    return success_object(public(insp))


@bp.post("/inspections/<rid>/close")
def close_inspection(rid):
    """Conditional close (PRD 3.2): IN_PROGRESS -> CLOSED on zero open findings,
    IN_PROGRESS -> AWAITING_REMEDIATION while findings remain open, and
    AWAITING_REMEDIATION -> CLOSED once every finding is VERIFIED_CLOSED."""
    authorized(["CompliancePrincipal"])
    insp = require_path_resource("inspections", rid)
    branch = db["branches"].get(insp["branch_id"])
    # Priority 3.5: OCC on BranchOffice.version
    body = get_body()
    expected = body.get("expected_branch_version")
    if branch is not None and soft_int(expected) and expected != branch["version"]:
        raise_error(ERR_STALE_BRANCH_VERSION,
                    "expected_branch_version does not match the branch's current version")
    # Priority 4: state
    status = insp["status"]
    if status not in ("IN_PROGRESS", "AWAITING_REMEDIATION"):
        raise_error(ERR_INSPECTION_INVALID_STATE,
                    "close is allowed only from IN_PROGRESS or AWAITING_REMEDIATION")

    opt_version(body, "expected_branch_version")

    if status == "IN_PROGRESS":
        recompute_inspection_counts(insp)
        if insp["open_findings_count"] == 0:
            _close(insp, branch)
        else:
            # Fieldwork ends, remediation begins; no branch mutation here.
            insp["status"] = "AWAITING_REMEDIATION"
            touch(insp)
    else:  # AWAITING_REMEDIATION
        findings = [f for f in db["findings"].values() if f["inspection_id"] == insp["id"]]
        if any(f["status"] != "VERIFIED_CLOSED" for f in findings):
            raise_error(ERR_FINDINGS_STILL_OPEN,
                        "all findings must be VERIFIED_CLOSED before closing")
        _close(insp, branch)
    return success_object(public(insp))


def _close(insp, branch):
    insp["status"] = "CLOSED"
    insp["completed_date"] = today().isoformat()
    touch(insp)
    if branch is not None:
        # Full branch recomputation incl. a fresh next_inspection_due_date;
        # the state machine pins a branch version bump on reaching CLOSED.
        recompute_branch(branch, recompute_due=True)
        touch(branch)
