"""Assignment endpoints (PRD §3.2, §3.9): dual approval lifecycle, OCC-guarded
repatriation initiation, completion, closure, and cancellation."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ASSIGNMENT_OVERLAP,
    ERR_COC_REQUIRED,
    ERR_ENGAGEMENT_NOT_FINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MAX_DURATION_EXCEEDED,
    ERR_PACKAGE_NOT_APPROVED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SPLIT_NOT_ACTIVE,
    ERR_STALE_ASSIGNMENT_VERSION,
    ERR_UNSETTLED_LEDGER,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, program_of_assignment, touch
from util import CLOCK
from validate import (
    get_body, req_bool, req_date, req_enum, req_field, req_str,
    require_fk, require_path_resource,
)

bp = Blueprint("assignments", __name__)

ASSIGNMENT_TYPES = {"SHORT_TERM", "LONG_TERM"}
# States in which an assignment still occupies the employee's date window.
OVERLAP_STATES = {"DRAFT", "PENDING_BU_APPROVAL", "PENDING_MOBILITY_APPROVAL",
                  "ACTIVE", "REPATRIATION_PENDING"}
CANCELLABLE_STATES = {"DRAFT", "PENDING_BU_APPROVAL", "PENDING_MOBILITY_APPROVAL"}


def _check_expected_version(asg, body):
    """OCC guard (validation priority 6)."""
    ev = req_field(body, "expected_assignment_version")
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise_error(ERR_INVALID_REQUEST, "expected_assignment_version must be an integer")
    if ev != asg["version"]:
        raise_error(
            ERR_STALE_ASSIGNMENT_VERSION,
            "expected_assignment_version does not match the assignment's current version",
        )


@bp.post("/mobility/assignments")
def create_assignment():
    authorized(["MobilityAdmin"])
    body = get_body()
    # Existence: body FK fields.
    program = require_fk("programs", req_field(body, "program_id"), "program_id")
    employee = require_fk("employees", req_field(body, "employee_id"), "employee_id")
    require_fk("allowance_policies", req_field(body, "policy_id"), "policy_id")
    # Shape.
    host_country_code = req_str(body, "host_country_code")
    host_business_unit = req_str(body, "host_business_unit")
    assignment_type = req_enum(body, "assignment_type", ASSIGNMENT_TYPES)
    totalization_applies = req_bool(body, "totalization_applies")
    start_date = req_date(body, "start_date")
    planned_end_date = req_date(body, "planned_end_date")
    if planned_end_date < start_date:
        raise_error(ERR_INVALID_REQUEST, "planned_end_date must be on or after start_date")
    # Date-window family, pinned order: duration cap BEFORE the overlap sweep.
    if (planned_end_date - start_date).days > program["max_assignment_duration_days"]:
        raise_error(
            ERR_MAX_DURATION_EXCEEDED,
            "assignment duration exceeds the program's max_assignment_duration_days",
        )
    # Closed-interval overlap: touching endpoints conflict.
    for a in db["assignments"].values():
        if a["employee_id"] != employee["id"] or a["status"] not in OVERLAP_STATES:
            continue
        if start_date.isoformat() <= a["planned_end_date"] and a["start_date"] <= planned_end_date.isoformat():
            raise_error(
                ERR_ASSIGNMENT_OVERLAP,
                "employee already holds an overlapping assignment in this window",
            )

    rec = new_record("assignments", {
        "program_id": program["id"],
        "employee_id": employee["id"],
        "policy_id": body["policy_id"],
        "host_country_code": host_country_code,
        "host_business_unit": host_business_unit,
        "assignment_type": assignment_type,
        "totalization_applies": totalization_applies,
        "start_date": start_date.isoformat(),
        "planned_end_date": planned_end_date.isoformat(),
        "actual_end_date": None,
        "status": "DRAFT",
        "cost_posture": "NORMAL",
        "ytd_gross_cents": 0,
        "ytd_hypo_withheld_cents": 0,
        "ytd_per_diem_days": 0,
        "ytd_chargeback_cents": 0,
        "submitted_by_user_id": None,
        "bu_approved_by_user_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/assignments/<rid>")
def get_assignment(rid):
    return get_one("assignments", rid)


@bp.get("/mobility/assignments")
def list_assignments():
    return list_response("assignments", {
        "program_id": request.args.get("program_id"),
        "employee_id": request.args.get("employee_id"),
        "policy_id": request.args.get("policy_id"),
        "status": request.args.get("status"),
    })


@bp.post("/mobility/assignments/<rid>/submit")
def submit_assignment(rid):
    caller = authorized(["MobilityAdmin"])
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT assignment can be submitted")
    asg["status"] = "PENDING_BU_APPROVAL"
    asg["submitted_by_user_id"] = caller.user_id
    touch(asg)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/approve-bu")
def approve_bu(rid):
    caller = authorized(["BusinessUnitApprover"])
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "PENDING_BU_APPROVAL":
        raise_error(ERR_INVALID_STATE, "assignment is not pending business-unit approval")
    asg["status"] = "PENDING_MOBILITY_APPROVAL"
    asg["bu_approved_by_user_id"] = caller.user_id
    touch(asg)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/reject-bu")
def reject_bu(rid):
    authorized(["BusinessUnitApprover"])
    get_body()  # optional reason accepted
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "PENDING_BU_APPROVAL":
        raise_error(ERR_INVALID_STATE, "assignment is not pending business-unit approval")
    asg["status"] = "DRAFT"
    asg["submitted_by_user_id"] = None
    touch(asg)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/approve-mobility")
def approve_mobility(rid):
    caller = authorized(["MobilityApprover"])
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "PENDING_MOBILITY_APPROVAL":
        raise_error(ERR_INVALID_STATE, "assignment is not pending mobility approval")
    # Segregation of duties (priority 7) before the referential gates (priority 8).
    if asg["bu_approved_by_user_id"] is not None and caller.user_id == asg["bu_approved_by_user_id"]:
        raise_error(
            ERR_SEGREGATION_OF_DUTIES,
            "mobility approver must differ from the business-unit approver",
        )
    # Referential gates in pinned order: package, split, certificate.
    package_ok = any(
        p["assignment_id"] == asg["id"] and p["status"] == "APPROVED"
        for p in db["compensation_packages"].values()
    )
    if not package_ok:
        raise_error(ERR_PACKAGE_NOT_APPROVED, "an APPROVED compensation package is required")
    split_ok = any(
        s["assignment_id"] == asg["id"] and s["status"] == "ACTIVE"
        for s in db["payroll_splits"].values()
    )
    if not split_ok:
        raise_error(ERR_SPLIT_NOT_ACTIVE, "an ACTIVE payroll split is required")
    if asg["totalization_applies"]:
        coc_ok = any(
            c["assignment_id"] == asg["id"] and c["status"] == "ISSUED"
            for c in db["certificates_of_coverage"].values()
        )
        if not coc_ok:
            raise_error(ERR_COC_REQUIRED, "an ISSUED certificate of coverage is required")
    asg["status"] = "ACTIVE"
    touch(asg)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/reject-mobility")
def reject_mobility(rid):
    authorized(["MobilityApprover"])
    get_body()  # optional reason accepted
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "PENDING_MOBILITY_APPROVAL":
        raise_error(ERR_INVALID_STATE, "assignment is not pending mobility approval")
    asg["status"] = "DRAFT"
    asg["submitted_by_user_id"] = None
    asg["bu_approved_by_user_id"] = None
    touch(asg)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/initiate-repatriation")
def initiate_repatriation(rid):
    authorized(["MobilityAdmin"])
    body = get_body()
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE assignment can begin repatriation")
    _check_expected_version(asg, body)
    asg["status"] = "REPATRIATION_PENDING"
    touch(asg)  # version increments by exactly one
    # Cascade hop 1: the ACTIVE payroll split suspends.
    for sp in db["payroll_splits"].values():
        if sp["assignment_id"] == asg["id"] and sp["status"] == "ACTIVE":
            sp["status"] = "SUSPENDED"
            touch(sp)
    # Cascade hop 2: every DRAFT shadow payroll record of the assignment voids.
    for rec in db["shadow_payroll_records"].values():
        if rec["assignment_id"] == asg["id"] and rec["status"] == "DRAFT":
            rec["status"] = "VOIDED"
            touch(rec)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/complete-repatriation")
def complete_repatriation(rid):
    authorized(["MobilityAdmin"])
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "REPATRIATION_PENDING":
        raise_error(ERR_INVALID_STATE, "assignment is not pending repatriation completion")
    for ve in db["vendor_engagements"].values():
        if ve["assignment_id"] == asg["id"] and ve["status"] not in ("FILED", "CLOSED"):
            raise_error(
                ERR_ENGAGEMENT_NOT_FINAL,
                "every vendor engagement must be FILED or CLOSED",
            )
    asg["status"] = "REPATRIATED"
    asg["actual_end_date"] = CLOCK.today().isoformat()
    touch(asg)
    for sp in db["payroll_splits"].values():
        if sp["assignment_id"] == asg["id"] and sp["status"] in ("ACTIVE", "SUSPENDED"):
            sp["status"] = "TERMINATED"
            touch(sp)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/close")
def close_assignment(rid):
    authorized(["MobilityAdmin"])
    asg = require_path_resource("assignments", rid)
    if asg["status"] != "REPATRIATED":
        raise_error(ERR_INVALID_STATE, "only a REPATRIATED assignment can be closed")
    for s in db["settlements"].values():
        if s["assignment_id"] == asg["id"] and s["status"] != "SETTLED":
            raise_error(ERR_UNSETTLED_LEDGER, "every settlement must be SETTLED")
    for e in db["chargeback_entries"].values():
        if e["assignment_id"] == asg["id"] and e["status"] not in ("POSTED", "VOIDED"):
            raise_error(ERR_UNSETTLED_LEDGER, "every chargeback entry must be POSTED or VOIDED")
    asg["status"] = "CLOSED"
    touch(asg)
    return success_object(public(asg))


@bp.post("/mobility/assignments/<rid>/cancel")
def cancel_assignment(rid):
    authorized(["MobilityAdmin"])
    asg = require_path_resource("assignments", rid)
    if asg["status"] not in CANCELLABLE_STATES:
        raise_error(ERR_INVALID_STATE, "only a DRAFT or in-approval assignment can be cancelled")
    asg["status"] = "CANCELLED"
    touch(asg)
    return success_object(public(asg))
