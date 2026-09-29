"""LoanerAssignment endpoints (PRD 3.9)."""
from flask import Blueprint

import calc
import db
import helpers
import serialize
import validate
from auth import authorize, check_account_scope
from db import touch
from errors import ApiError

bp = Blueprint("loaner_assignments", __name__)

READ_ROLES = ("PlantManager", "IntakeClerk", "ComplianceOfficer", "CustomerContact")


@bp.post("/loaner-assignments")
def create_assignment():
    authorize(("IntakeClerk",))
    data = validate.body()
    customer_account_id = validate.req_id(data, "customer_account_id")
    requested_model_spec_id = validate.req_id(data, "requested_model_spec_id")
    (start, start_raw), (end, end_raw) = validate.req_window(data)
    loaner_unit_id = validate.opt_id(data, "loaner_unit_id")

    account = helpers.account(customer_account_id)
    helpers.model(requested_model_spec_id)
    loaner = helpers.loaner(loaner_unit_id) if loaner_unit_id is not None else None

    if loaner is not None:
        if calc.loaner_double_booked(loaner["id"], start, end):
            raise ApiError("ERR_LOANER_DOUBLE_BOOKED",
                           "That loaner is already committed across this window.")
        if loaner["certification_valid_until"] < end:
            raise ApiError("ERR_LOANER_CERTIFICATION_EXPIRED",
                           "That loaner's certification lapses mid-loan.")

    if account["liability_waiver_status"] != "ON_FILE":
        raise ApiError("ERR_LIABILITY_WAIVER_MISSING",
                       "The program has no current liability waiver on file.")
    if account["status"] == "BILLING_HOLD":
        raise ApiError("ERR_ACCOUNT_ON_HOLD", "The program's account is on a billing hold.")

    if loaner is None:
        loaner = calc.select_loaner_unit(requested_model_spec_id, start, end)
        if loaner is None:
            raise ApiError("ERR_NO_LOANER_AVAILABLE",
                           "No eligible loaner covers the requested window.")
        selected_by = "SERVER_SELECTED"
    else:
        selected_by = "EXPLICIT"

    status = "OUT_ON_LOAN" if start <= db.now() else "RESERVED"
    record = db.base_record()
    record.update({
        "customer_account_id": account["id"],
        "requested_model_spec_id": requested_model_spec_id,
        "loaner_unit_id": loaner["id"],
        "window_start": start,
        "window_end": end,
        "selected_by": selected_by,
        "returned_at": None,
        "status": status,
    })
    db.raw_set(record, "window_start", start_raw)
    db.raw_set(record, "window_end", end_raw)
    db.db.loaner_assignments[record["id"]] = record

    loaner["status"] = status
    loaner["assignment_count"] = (loaner["assignment_count"] or 0) + 1
    touch(loaner)
    return helpers.single(record, serialize.loaner_assignment, 201)


@bp.get("/loaner-assignments/<row_id>")
def get_assignment(row_id):
    authorize(READ_ROLES)
    return helpers.single(helpers.assignment(row_id), serialize.loaner_assignment)


@bp.get("/loaner-assignments")
def list_assignments():
    caller = authorize(READ_ROLES)
    customer_account_id = validate.query_str("customer_account_id")
    requested_model_spec_id = validate.query_str("requested_model_spec_id")
    loaner_unit_id = validate.query_str("loaner_unit_id")
    status = validate.query_enum("status", calc.ASSIGNMENT_STATUSES)
    if caller.is_customer:
        if customer_account_id is not None:
            check_account_scope(caller, customer_account_id)
        customer_account_id = caller.user_id
    filters = {
        "customer_account_id": customer_account_id,
        "requested_model_spec_id": requested_model_spec_id,
        "loaner_unit_id": loaner_unit_id,
        "status": status,
    }
    return helpers.listing("loaner_assignments", serialize.loaner_assignment, filters)


@bp.post("/loaner-assignments/<row_id>/return")
def return_assignment(row_id):
    authorize(("IntakeClerk",))
    data = validate.body()
    validate.opt_str(data, "return_condition_note", max_len=1000)
    record = helpers.assignment(row_id)

    if record["status"] not in ("RESERVED", "OUT_ON_LOAN"):
        raise ApiError("ERR_LOANER_ASSIGNMENT_STATE_INVALID",
                       "This loan has already been returned.")

    record["returned_at"] = db.now()
    record["status"] = "RETURNED"
    touch(record)
    loaner = db.db.loaner_units.get(record["loaner_unit_id"])
    if loaner is not None:
        loaner["status"] = "AVAILABLE"
        touch(loaner)
    return helpers.single(record, serialize.loaner_assignment)
