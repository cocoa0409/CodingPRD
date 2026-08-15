"""Clock, departments, inventors."""
from flask import Blueprint, request

from store import db, create_record
from util import (ApiError, require, get_body, check_schema, v_nonempty_str,
                  v_enum, v_dt, fmt_dt, ok_object, ok_list, paginate)
from serializers import ser_department, ser_inventor, ser_entry, ser_dispute, ser_disclosure, ser_coi_plan
from services import license_sweep

bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/tlo/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require("SystemAdmin")
    data = check_schema(get_body(), {"to_iso8601": (True, v_dt)})
    db.clock = data["to_iso8601"]
    activated, expired = license_sweep()
    return ok_object({
        "current_utc": fmt_dt(db.clock),
        "activated_license_ids": activated,
        "expired_license_ids": expired,
    })


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@bp.route("/tlo/departments", methods=["POST"])
def create_department():
    require("SystemAdmin")
    data = check_schema(get_body(), {
        "name": (True, v_nonempty_str),
        "college_name": (True, v_nonempty_str),
    })
    dept = create_record(db.departments, {
        "name": data["name"],
        "college_name": data["college_name"],
        "distribution_pool_cents": 0,
    })
    return ok_object(ser_department(dept), status=201)


@bp.route("/tlo/departments", methods=["GET"])
def list_departments():
    require()
    page, limit, offset, total = paginate(list(db.departments.values()))
    return ok_list([ser_department(d) for d in page], limit, offset, total)


@bp.route("/tlo/departments/<departmentId>", methods=["GET"])
def get_department(departmentId):
    require()
    dept = db.departments.get(departmentId)
    if dept is None:
        raise ApiError("ERR_DEPARTMENT_NOT_FOUND", 404, "Department id does not exist")
    return ok_object(ser_department(dept))


# ---------------------------------------------------------------------------
# Inventors
# ---------------------------------------------------------------------------

@bp.route("/tlo/inventors", methods=["POST"])
def create_inventor():
    require("SystemAdmin")
    data = check_schema(get_body(), {
        "full_name": (True, v_nonempty_str),
        "email": (True, v_nonempty_str),
        "department_id": (True, v_nonempty_str),
        "appointment_type": (True, v_enum("FACULTY", "STAFF", "STUDENT")),
    })
    if data["department_id"] not in db.departments:
        raise ApiError("ERR_DEPARTMENT_NOT_FOUND", 404, "Department id does not exist")
    inv = create_record(db.inventors, {
        "full_name": data["full_name"],
        "email": data["email"],
        "department_id": data["department_id"],
        "appointment_type": data["appointment_type"],
    })
    return ok_object(ser_inventor(inv), status=201)


@bp.route("/tlo/inventors", methods=["GET"])
def list_inventors():
    require()
    records = list(db.inventors.values())
    dept_filter = request.args.get("department_id")
    if dept_filter is not None:
        records = [i for i in records if i["department_id"] == dept_filter]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_inventor(i) for i in page], limit, offset, total)


@bp.route("/tlo/inventors/<inventorId>", methods=["GET"])
def get_inventor(inventorId):
    require()
    inv = db.inventors.get(inventorId)
    if inv is None:
        raise ApiError("ERR_INVENTOR_NOT_FOUND", 404, "Inventor id does not exist")
    return ok_object(ser_inventor(inv))


def _get_inventor_or_404(inventor_id):
    inv = db.inventors.get(inventor_id)
    if inv is None:
        raise ApiError("ERR_INVENTOR_NOT_FOUND", 404, "Inventor id does not exist")
    return inv


@bp.route("/tlo/inventors/<inventorId>/disclosure-entries", methods=["GET"])
def list_inventor_entries(inventorId):
    require()
    _get_inventor_or_404(inventorId)
    records = [e for e in db.entries.values() if e["inventor_id"] == inventorId]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_entry(e) for e in page], limit, offset, total)


@bp.route("/tlo/inventors/<inventorId>/disputes", methods=["GET"])
def list_inventor_disputes(inventorId):
    require()
    _get_inventor_or_404(inventorId)
    records = [d for d in db.disputes.values() if d["raised_by_inventor_id"] == inventorId]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_dispute(d) for d in page], limit, offset, total)


@bp.route("/tlo/inventors/<inventorId>/disclosures", methods=["GET"])
def list_inventor_disclosures(inventorId):
    require()
    _get_inventor_or_404(inventorId)
    records = [d for d in db.disclosures.values() if d["submitter_inventor_id"] == inventorId]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_disclosure(d) for d in page], limit, offset, total)


@bp.route("/tlo/inventors/<inventorId>/coi-plans", methods=["GET"])
def list_inventor_coi_plans(inventorId):
    require()
    _get_inventor_or_404(inventorId)
    records = [p for p in db.coi_plans.values() if p["inventor_id"] == inventorId]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_coi_plan(p) for p in page], limit, offset, total)
