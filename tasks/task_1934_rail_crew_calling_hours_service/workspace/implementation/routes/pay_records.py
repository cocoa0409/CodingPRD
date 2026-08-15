from flask import Blueprint, request

from db import store, base_record, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REFERENTIAL_MISMATCH,
    ERR_PAY_INCOMPLETE,
    ERR_STALE_VERSION,
)
from middleware import auth, require_roles, require_owner
from response import ok_obj, paged
from services import agreement_pay
from validators import body, req_str, req_int, opt_int

bp = Blueprint("pay_records", __name__)

ALL_ROLES = ("CrewManager", "CrewCaller", "Employee")


def _get_record(pr_id):
    pr = store.pay_records.get(pr_id)
    if pr is None:
        raise ApiError(ERR_NOT_FOUND, 404, "PayRecord '%s' not found." % pr_id)
    return pr


def _compute_gross(pr, variant):
    asg = store.assignments.get(pr["assignment_id"])
    mode = asg["deadhead_mode"] if asg is not None else "NONE"
    return agreement_pay(
        pr["claimed_minutes"], pr["claimed_deadhead_minutes"], mode, variant
    )


@bp.post("/api/pay-records")
def create_pay_record():
    data = body()
    employee_id = req_str(data, "employee_id")
    assignment_id = req_str(data, "assignment_id")
    claimed_minutes = req_int(data, "claimed_minutes", min_value=0)
    claimed_deadhead = opt_int(data, "claimed_deadhead_minutes", 0, min_value=0)
    _, role = auth()
    require_roles(role, ("Employee",))
    asg = store.assignments.get(assignment_id)
    if asg is None or asg["employee_id"] != employee_id:
        raise ApiError(
            ERR_REFERENTIAL_MISMATCH, 422,
            "assignment_id must reference an Assignment belonging to employee_id.",
        )
    if store.employees.get(employee_id) is None:
        raise ApiError(
            ERR_REFERENTIAL_MISMATCH, 422,
            "employee_id does not reference an existing Employee.",
        )
    rec = base_record()
    rec.update({
        "employee_id": employee_id,
        "assignment_id": assignment_id,
        "claimed_minutes": claimed_minutes,
        "claimed_deadhead_minutes": claimed_deadhead,
        "gross_pay_cents": 0,
        "record_status": "DRAFT",
    })
    store.pay_records[rec["id"]] = rec
    return ok_obj(rec, 201)


@bp.get("/api/pay-records")
def list_pay_records():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    rows = list(store.pay_records.values())
    for param in ("employee_id", "assignment_id", "record_status"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if r[param] == v]
    return paged(rows, request.args)


@bp.get("/api/pay-records/<pr_id>")
def get_pay_record(pr_id):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok_obj(_get_record(pr_id))


@bp.post("/api/pay-records/<pr_id>/submit")
def submit_pay_record(pr_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    pr = _get_record(pr_id)
    require_owner(uid, pr["employee_id"])
    if pr["record_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "PayRecord is not DRAFT.")
    if pr["claimed_minutes"] <= 0:
        raise ApiError(
            ERR_PAY_INCOMPLETE, 422, "claimed_minutes must be greater than zero."
        )
    pr["gross_pay_cents"] = _compute_gross(pr, "provisional")
    pr["record_status"] = "SUBMITTED"
    touch(pr)
    return ok_obj(pr)


@bp.post("/api/pay-records/<pr_id>/dispute")
def dispute_pay_record(pr_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    pr = _get_record(pr_id)
    if pr["record_status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "PayRecord is not SUBMITTED.")
    pr["record_status"] = "DISPUTED"
    touch(pr)
    return ok_obj(pr)


@bp.post("/api/pay-records/<pr_id>/resubmit")
def resubmit_pay_record(pr_id):
    data = body()
    claimed_minutes = req_int(data, "claimed_minutes", min_value=0)
    claimed_deadhead = opt_int(data, "claimed_deadhead_minutes", None, min_value=0)
    uid, role = auth()
    require_roles(role, ("Employee",))
    pr = _get_record(pr_id)
    require_owner(uid, pr["employee_id"])
    if pr["record_status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "PayRecord is not DISPUTED.")
    pr["claimed_minutes"] = claimed_minutes
    if claimed_deadhead is not None:
        pr["claimed_deadhead_minutes"] = claimed_deadhead
    pr["gross_pay_cents"] = _compute_gross(pr, "provisional")
    pr["record_status"] = "SUBMITTED"
    touch(pr)
    return ok_obj(pr)


@bp.post("/api/pay-records/<pr_id>/finalize")
def finalize_pay_record(pr_id):
    data = body()
    expected_version = req_int(data, "expected_pay_record_version")
    _, role = auth()
    require_roles(role, ("CrewManager",))
    pr = _get_record(pr_id)
    if pr["record_status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "PayRecord is not SUBMITTED.")
    if expected_version != pr["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_pay_record_version does not match the record's current version.",
        )
    pr["gross_pay_cents"] = _compute_gross(pr, "final")
    pr["record_status"] = "FINALIZED"
    touch(pr)  # increments version by one
    return ok_obj(pr)
