"""ChangeRequest endpoints: proposal, approval, apply, void."""
from datetime import timedelta

from flask import Blueprint, request

from engine import apply_change_request, void_change_request
from errors import ApiError
from serialize import ser_change_request
from services import bump, get_or_404, is_salary_field, valid_salary_literal
from store import db
from util import (
    ALL_ROLES, auth, body, clock_date, inv, list_page, new_entity, ok,
    parse_date_val, parse_int_val, req_field,
)

bp = Blueprint("changes", __name__)


def _supersede_rivals(cr):
    for other in db.change_requests.values():
        if other["id"] == cr["id"]:
            continue
        if other["status"] not in ("PENDING_APPROVAL", "PARTIALLY_APPROVED"):
            continue
        if other["target_field_id"] == cr["target_field_id"] and \
                other["target_worker_id"] == cr["target_worker_id"] and \
                other["target_position_id"] == cr["target_position_id"]:
            other["status"] = "SUPERSEDED"  # no audit entry for supersession
            bump(other)


def _create_change_request(target_worker_id, target_position_id):
    b = body()
    target_type = req_field(b, "target_type")
    if target_worker_id and target_type != "WORKER_FIELD":
        raise inv("target_type must be WORKER_FIELD under a worker")
    if target_position_id and target_type not in ("POSITION_FIELD", "POSITION_HIERARCHY"):
        raise inv("target_type must be POSITION_FIELD or POSITION_HIERARCHY under a position")
    target_field_id = req_field(b, "target_field_id")
    if not isinstance(target_field_id, str):
        raise inv("Invalid target_field_id")
    new_value = req_field(b, "new_value")
    if isinstance(new_value, (dict, list)) or new_value is None:
        raise inv("new_value must be a scalar")
    new_value = str(new_value)
    # body FK existence (tier 3)
    field = get_or_404(db.data_fields, target_field_id, "ERR_DATA_FIELD_NOT_FOUND")
    correction_mode = b.get("correction_mode", "NEW_RECORD")
    if correction_mode not in ("NEW_RECORD", "CORRECT_HISTORY"):
        raise inv("Invalid correction_mode")
    propagate = b.get("propagate_correction", False)
    if not isinstance(propagate, bool):
        raise inv("propagate_correction must be a boolean")
    target_row_id = b.get("target_row_id")
    if target_row_id is not None:
        row = get_or_404(db.assignments, target_row_id, "ERR_ASSIGNMENT_NOT_FOUND")
        if target_worker_id and row["worker_id"] != target_worker_id:
            raise inv("target_row_id does not belong to the target worker")
    # body well-formedness (tier 4)
    effective_date = None
    if target_worker_id:
        if correction_mode == "NEW_RECORD":
            if b.get("effective_date") is None:
                raise inv("effective_date is required for NEW_RECORD")
            effective_date = parse_date_val(b.get("effective_date"), "effective_date")
        elif b.get("effective_date") is not None:
            parse_date_val(b.get("effective_date"), "effective_date")
        if correction_mode == "CORRECT_HISTORY" and not target_row_id:
            raise ApiError("ERR_CORRECTION_MODE_NOT_ALLOWED", 422,
                           "CORRECT_HISTORY requires target_row_id")
        if is_salary_field(field) and not valid_salary_literal(new_value, allow_pct=False):
            raise inv("new_value must be integer cents for assignment.salary_cents")
    else:
        if b.get("effective_date") is None:
            raise inv("effective_date is required for position-targeted requests")
        effective_date = parse_date_val(b.get("effective_date"), "effective_date")
        if is_salary_field(field) and not valid_salary_literal(new_value, allow_pct=False):
            raise inv("new_value must be integer cents for assignment.salary_cents")
    return field, target_type, new_value, effective_date, correction_mode, target_row_id, propagate


@bp.post("/hris/workers/<workerId>/change-requests")
def create_worker_change_request(workerId):
    caller = auth(["HrisAnalyst"])
    worker = get_or_404(db.workers, workerId, "ERR_WORKER_NOT_FOUND")
    field, target_type, new_value, effective_date, correction_mode, target_row_id, propagate = \
        _create_change_request(workerId, None)
    b = body()
    # OCC (tier 5): expected_worker_version is non-optional
    if "expected_worker_version" not in b or b["expected_worker_version"] is None:
        raise inv("expected_worker_version is required")
    expected = parse_int_val(b["expected_worker_version"], "expected_worker_version")
    if expected != worker["version"]:
        raise ApiError("ERR_STALE_WORKER_VERSION", 412,
                       "expected_worker_version does not match current version")
    # state (tier 6): field must be ACTIVE for new references
    if field["status"] != "ACTIVE":
        raise ApiError("ERR_FIELD_NOT_ACTIVE", 409, "Data field is not ACTIVE")
    cr = new_entity(db.change_requests)
    cr.update({"target_type": target_type, "target_worker_id": workerId,
               "target_position_id": None, "target_field_id": field["id"],
               "new_value": new_value, "effective_date": effective_date,
               "correction_mode": correction_mode, "target_row_id": target_row_id,
               "propagate_correction": propagate, "status": "PENDING_APPROVAL",
               "created_by": caller, "approver_1_id": None, "approver_2_id": None,
               "prior_value": None, "prior_row_end": None})
    db.change_requests[cr["id"]] = cr
    _supersede_rivals(cr)
    bump(worker)
    return ok(ser_change_request(cr), code=201)


@bp.post("/hris/positions/<positionId>/change-requests")
def create_position_change_request(positionId):
    caller = auth(["HrisAnalyst"])
    position = get_or_404(db.positions, positionId, "ERR_POSITION_NOT_FOUND")
    field, target_type, new_value, effective_date, correction_mode, target_row_id, propagate = \
        _create_change_request(None, positionId)
    b = body()
    if "expected_position_version" not in b or b["expected_position_version"] is None:
        raise inv("expected_position_version is required")
    expected = parse_int_val(b["expected_position_version"], "expected_position_version")
    if expected != position["version"]:
        raise ApiError("ERR_STALE_POSITION_VERSION", 412,
                       "expected_position_version does not match current version")
    if field["status"] != "ACTIVE":
        raise ApiError("ERR_FIELD_NOT_ACTIVE", 409, "Data field is not ACTIVE")
    # temporal (tier 10 applies at position-change create)
    cdate = clock_date()
    if effective_date < cdate or effective_date > cdate + timedelta(days=365):
        raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_WINDOW", 422,
                       "Position change effective_date must be on/after the clock date")
    cr = new_entity(db.change_requests)
    cr.update({"target_type": target_type, "target_worker_id": None,
               "target_position_id": positionId, "target_field_id": field["id"],
               "new_value": new_value, "effective_date": effective_date,
               "correction_mode": "NEW_RECORD", "target_row_id": None,
               "propagate_correction": False, "status": "PENDING_APPROVAL",
               "created_by": caller, "approver_1_id": None, "approver_2_id": None,
               "prior_value": None, "prior_row_end": None})
    db.change_requests[cr["id"]] = cr
    _supersede_rivals(cr)
    bump(position)
    return ok(ser_change_request(cr), code=201)


@bp.get("/hris/change-requests")
def list_change_requests():
    auth(ALL_ROLES)
    items = list(db.change_requests.values())
    for key in ("target_worker_id", "target_position_id", "target_field_id",
                "target_row_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if c[key] == v]
    return list_page(items, ser_change_request)


@bp.get("/hris/change-requests/<changeRequestId>")
def get_change_request(changeRequestId):
    auth(ALL_ROLES)
    cr = get_or_404(db.change_requests, changeRequestId, "ERR_CHANGE_REQUEST_NOT_FOUND")
    return ok(ser_change_request(cr))


def _has_approver_grant(user_id):
    for g in db.grants.values():
        if g["user_id"] == user_id and g["role_code"] == "CHANGE_APPROVER" \
                and g["status"] == "PROVISIONED":
            return True
    return False


@bp.post("/hris/change-requests/<changeRequestId>/approve")
def approve_change_request(changeRequestId):
    caller = auth(["ChangeApprover"])
    cr = get_or_404(db.change_requests, changeRequestId, "ERR_CHANGE_REQUEST_NOT_FOUND")
    if cr["status"] not in ("PENDING_APPROVAL", "PARTIALLY_APPROVED"):
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409,
                       "Change request is not pending approval")
    # authority tier: provisioned grant -> self-approval
    if not _has_approver_grant(caller):
        raise ApiError("ERR_GRANT_NOT_PROVISIONED", 403,
                       "Caller holds no PROVISIONED CHANGE_APPROVER grant")
    if caller == cr["created_by"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 403,
                       "Approver may not be the request creator")
    if cr["status"] == "PARTIALLY_APPROVED" and caller == cr["approver_1_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 403,
                       "Second approver must differ from the first")
    field = db.data_fields.get(cr["target_field_id"])
    if field is not None and field["sensitivity"] == "RESTRICTED":
        if cr["status"] == "PENDING_APPROVAL":
            cr["approver_1_id"] = caller
            cr["status"] = "PARTIALLY_APPROVED"
        else:
            cr["approver_2_id"] = caller
            cr["status"] = "APPROVED"
    else:
        cr["approver_1_id"] = caller
        cr["status"] = "APPROVED"
    bump(cr)
    return ok(ser_change_request(cr))


@bp.post("/hris/change-requests/<changeRequestId>/reject")
def reject_change_request(changeRequestId):
    auth(["ChangeApprover"])
    cr = get_or_404(db.change_requests, changeRequestId, "ERR_CHANGE_REQUEST_NOT_FOUND")
    if cr["status"] not in ("PENDING_APPROVAL", "PARTIALLY_APPROVED"):
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409,
                       "Change request is not pending approval")
    cr["status"] = "REJECTED"
    bump(cr)
    return ok(ser_change_request(cr))


@bp.post("/hris/change-requests/<changeRequestId>/apply")
def apply_change(changeRequestId):
    caller = auth(["HrisAnalyst"])
    cr = get_or_404(db.change_requests, changeRequestId, "ERR_CHANGE_REQUEST_NOT_FOUND")
    apply_change_request(cr, caller)
    return ok(ser_change_request(cr))


@bp.post("/hris/change-requests/<changeRequestId>/void")
def void_change(changeRequestId):
    caller = auth(["HrisAnalyst"])
    cr = get_or_404(db.change_requests, changeRequestId, "ERR_CHANGE_REQUEST_NOT_FOUND")
    void_change_request(cr, caller)
    return ok(ser_change_request(cr))
