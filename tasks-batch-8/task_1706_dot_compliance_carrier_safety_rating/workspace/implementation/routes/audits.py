"""ComplianceAuditCase endpoints (PRD 3.8): schedule, field work, findings, close."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_AUDIT_TYPE_NOT_APPLICABLE, ERR_AUDIT_SCHEDULED_PAST_DUE,
    ERR_AUDIT_WINDOW_OVERLAP, ERR_AUDIT_INVALID_STATE,
    ERR_AUDIT_BEFORE_SCHEDULED_DATE, ERR_AUDIT_READINESS_INCOMPLETE,
    ERR_CORRECTIVE_ACTION_NOT_APPLICABLE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import (
    stamp_new, touch, recompute_posture, sweep_quoted_premiums,
    apply_rating_to_carrier, audit_readiness, OPEN_AUDIT_STATES,
)
from validate import (
    get_body, req_str, req_enum, req_int, opt_int, req_datetime,
    require_path_resource, require_ref,
)
from util import new_id, parse_datetime, CLOCK

bp = Blueprint("audits", __name__)

AUDIT_TYPES = ["NEW_ENTRANT", "COMPLIANCE_REVIEW"]
ADVERSE_OUTCOMES = ("FAIL", "CONDITIONAL", "UNSATISFACTORY")


def _window(rec):
    start = parse_datetime(rec["scheduled_date"])
    end = start + timedelta(days=rec["field_work_duration_days"])
    return start, end


@bp.post("/safety/compliance-audit-cases")
def create_audit():
    authorized(["SafetyAdmin"])
    body = get_body()
    # Stage 3: shape
    carrier_id = req_str(body, "carrier_id")
    audit_type = req_enum(body, "audit_type", AUDIT_TYPES)
    scheduled_date = req_datetime(body, "scheduled_date")
    duration = opt_int(body, "field_work_duration_days", default=14, minimum=1)
    # Stage 4: existence
    carrier = require_ref("carriers", carrier_id, "carrier_id")
    scheduled = parse_datetime(scheduled_date)
    # Stage 8: temporal — new-entrant audit may not be scheduled past its due date
    if audit_type == "NEW_ENTRANT" and carrier.get("safety_audit_due_date"):
        if scheduled > parse_datetime(carrier["safety_audit_due_date"]):
            raise_error(ERR_AUDIT_SCHEDULED_PAST_DUE,
                        "scheduled_date is after safety_audit_due_date")
    # Stage 9: half-open field-work window overlap vs other non-closed cases
    new_start, new_end = scheduled, scheduled + timedelta(days=duration)
    for a in db["compliance_audit_cases"].values():
        if a["carrier_id"] != carrier_id or a["status"] not in OPEN_AUDIT_STATES:
            continue
        a_start, a_end = _window(a)
        if new_start < a_end and a_start < new_end:
            raise_error(ERR_AUDIT_WINDOW_OVERLAP,
                        "field-work window overlaps an existing open audit")
    # Stage 9: NEW_ENTRANT applicability
    if audit_type == "NEW_ENTRANT":
        if not carrier["is_new_entrant"] or carrier["new_entrant_status"] != "PENDING_AUDIT":
            raise_error(ERR_AUDIT_TYPE_NOT_APPLICABLE,
                        "NEW_ENTRANT audit requires a new entrant in PENDING_AUDIT")
    case = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "audit_type": audit_type,
        "scheduled_date": scheduled_date,
        "field_work_duration_days": duration,
        "acute_count": None,
        "critical_count": None,
        "proposed_outcome": None,
        "status": "SCHEDULED",
    })
    db["compliance_audit_cases"][case["id"]] = case
    return success_object(public(case), 201)


@bp.get("/safety/compliance-audit-cases")
def list_audits():
    return list_response("compliance_audit_cases", filters={
        "carrier_id": request.args.get("carrier_id"),
        "audit_type": request.args.get("audit_type"),
        "status": request.args.get("status"),
    })


@bp.get("/safety/compliance-audit-cases/<rid>")
def get_audit(rid):
    return get_one("compliance_audit_cases", rid)


@bp.post("/safety/compliance-audit-cases/<rid>/start-field-work")
def start_field_work(rid):
    authorized(["SafetyAdmin"])
    case = require_path_resource("compliance_audit_cases", rid)
    if case["status"] != "SCHEDULED":
        raise_error(ERR_AUDIT_INVALID_STATE, "start-field-work requires SCHEDULED")
    if CLOCK.now() < parse_datetime(case["scheduled_date"]):
        raise_error(ERR_AUDIT_BEFORE_SCHEDULED_DATE,
                    "field work may not begin before scheduled_date")
    carrier = db["carriers"].get(case["carrier_id"])
    if carrier is None or not audit_readiness(carrier)["ready"]:
        raise_error(ERR_AUDIT_READINESS_INCOMPLETE, "carrier is not audit-ready")
    case["status"] = "FIELD_WORK"
    touch(case)
    return success_object(public(case))


@bp.post("/safety/compliance-audit-cases/<rid>/issue-findings")
def issue_findings(rid):
    authorized(["SafetyAdmin"])
    body = get_body()
    acute_count = req_int(body, "acute_count", minimum=0)
    critical_count = req_int(body, "critical_count", minimum=0)
    case = require_path_resource("compliance_audit_cases", rid)
    if case["status"] != "FIELD_WORK":
        raise_error(ERR_AUDIT_INVALID_STATE, "issue-findings requires FIELD_WORK")
    case["acute_count"] = acute_count
    case["critical_count"] = critical_count
    case["proposed_outcome"] = calc.audit_outcome(case["audit_type"], acute_count, critical_count)
    case["status"] = "FINDINGS_ISSUED"
    touch(case)
    return success_object(public(case))


@bp.post("/safety/compliance-audit-cases/<rid>/begin-corrective-action")
def begin_corrective_action(rid):
    authorized(["SafetyManager"])
    case = require_path_resource("compliance_audit_cases", rid)
    if case["status"] != "FINDINGS_ISSUED":
        raise_error(ERR_AUDIT_INVALID_STATE,
                    "begin-corrective-action requires FINDINGS_ISSUED")
    if case["proposed_outcome"] not in ADVERSE_OUTCOMES:
        raise_error(ERR_CORRECTIVE_ACTION_NOT_APPLICABLE,
                    "no corrective action for a non-adverse outcome")
    case["status"] = "CORRECTIVE_ACTION_PHASE"
    touch(case)
    return success_object(public(case))


@bp.post("/safety/compliance-audit-cases/<rid>/close")
def close(rid):
    authorized(["SafetyDirector"])
    case = require_path_resource("compliance_audit_cases", rid)
    if case["status"] not in ("FINDINGS_ISSUED", "CORRECTIVE_ACTION_PHASE"):
        raise_error(ERR_AUDIT_INVALID_STATE,
                    "close requires FINDINGS_ISSUED or CORRECTIVE_ACTION_PHASE")
    outcome = case["proposed_outcome"]
    carrier = db["carriers"].get(case["carrier_id"])
    if outcome in ("PASS", "SATISFACTORY"):
        case["status"] = "CLOSED_PASSED"
    else:
        case["status"] = "CLOSED_FAILED"
    if case["audit_type"] == "NEW_ENTRANT":
        if outcome == "PASS":
            carrier["new_entrant_status"] = "PASSED"
            recompute_posture(carrier)
            touch(carrier)
        else:  # FAIL
            carrier["new_entrant_status"] = "FAILED"
            recompute_posture(carrier)
            touch(carrier)
            sweep_quoted_premiums(carrier["id"])
    else:  # COMPLIANCE_REVIEW: write the rating with the full cascade
        apply_rating_to_carrier(carrier, outcome)
    touch(case)
    return success_object(public(case))
