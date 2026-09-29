"""Work write-up revisions and their repair lines (PRD 3.3)."""

from flask import Blueprint

import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import calc, domain, serializers
from services import constants as C

bp = Blueprint("write_ups", __name__)

READ_ROLES = middleware.STAFF_ROLES
READ_ONE_ROLES = middleware.STAFF_ROLES + (middleware.APPLICANT,)
ITEM_LIST_ROLES = middleware.STAFF_ROLES + (middleware.CONTRACTOR,)
EDITABLE_STATES = ("DRAFT", "REVISION_REQUESTED")


# ---------------------------------------------------------------------------
# write-ups
# ---------------------------------------------------------------------------


@bp.post(API_PREFIX + "/write-ups")
@middleware.roles(middleware.REHAB_SPECIALIST)
def create_write_up():
    body = validation.json_body()
    application = validation.body_fk(
        body, "application_id", db.applications, errors.ERR_APPLICATION_NOT_FOUND
    )
    validation.field_id(body, "application_id")
    expected = validation.field_int(body, "expected_application_version", minimum=0)
    revision_reason = validation.field_str(
        body, "revision_reason", required=False, default=None
    )

    validation.check_version(application, expected)

    if application["ownership_verification_status"] != "VERIFIED":
        fail(errors.ERR_OWNERSHIP_NOT_VERIFIED)

    prior = domain.write_ups_of(application["id"])
    revision_number = 1
    if prior:
        revision_number = max(row["revision_number"] for row in prior) + 1

    row = db.new_row()
    row.update(
        {
            "application_id": application["id"],
            "revision_number": revision_number,
            "revision_reason": revision_reason if revision_number > 1 else None,
            "prepared_by_user_id": middleware.user_id(),
            "approved_by_user_id": None,
            "state": "DRAFT",
            "work_item_count": 0,
            "base_estimate_cents": 0,
            "contingency_cents": 0,
            "total_estimate_cents": 0,
            "priority_repair_total_cents": 0,
        }
    )
    db.write_ups[row["id"]] = row

    superseded = False
    for existing in prior:
        if existing["state"] == "APPROVED":
            existing["state"] = "SUPERSEDED"
            db.touch(existing)
            superseded = True
    if superseded and application["workflow_state"] == "WRITEUP_APPROVED":
        application["workflow_state"] = "INSPECTED"
        db.touch(application)

    return response.object_response(serializers.write_up(row), 201)


@bp.post(API_PREFIX + "/write-ups/<write_up_id>/submit")
@middleware.roles(middleware.REHAB_SPECIALIST)
def submit_write_up(write_up_id):
    row = validation.path_row(db.write_ups, write_up_id, errors.ERR_WRITE_UP_NOT_FOUND)
    if row["state"] not in EDITABLE_STATES:
        fail(errors.ERR_INVALID_STATE, "The write-up cannot be submitted from its state.")

    totals = calc.write_up_totals(domain.work_items_of(row["id"]))
    if totals["work_item_count"] < 1:
        fail(errors.ERR_WRITE_UP_EMPTY)
    if totals["priority_repair_total_cents"] <= 0:
        fail(errors.ERR_PRIORITY_REPAIRS_NOT_ADDRESSED)

    row.update(totals)
    row["state"] = "SUBMITTED"
    db.touch(row)
    return response.object_response(serializers.write_up(row))


@bp.post(API_PREFIX + "/write-ups/<write_up_id>/request-revision")
@middleware.roles(middleware.PROGRAM_MANAGER)
def request_revision(write_up_id):
    row = validation.path_row(db.write_ups, write_up_id, errors.ERR_WRITE_UP_NOT_FOUND)
    body = validation.json_body()
    note = validation.field_str(body, "revision_note")

    if row["state"] != "SUBMITTED":
        fail(errors.ERR_INVALID_STATE, "Only a submitted write-up may be returned.")

    row["state"] = "REVISION_REQUESTED"
    row["_revision_note"] = note
    db.touch(row)
    return response.object_response(serializers.write_up(row))


@bp.post(API_PREFIX + "/write-ups/<write_up_id>/approve")
@middleware.roles(middleware.PROGRAM_MANAGER)
def approve_write_up(write_up_id):
    row = validation.path_row(db.write_ups, write_up_id, errors.ERR_WRITE_UP_NOT_FOUND)
    application = db.applications.get(row["application_id"])

    if row["state"] != "SUBMITTED":
        fail(errors.ERR_INVALID_STATE, "Only a submitted write-up may be approved.")
    if application is None or application["workflow_state"] != "INSPECTED":
        fail(errors.ERR_INVALID_STATE, "The case is not awaiting scope approval.")
    if middleware.user_id() == row["prepared_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES)

    row["state"] = "APPROVED"
    row["approved_by_user_id"] = middleware.user_id()
    db.touch(row)

    application["workflow_state"] = "WRITEUP_APPROVED"
    db.touch(application)

    return response.object_response(serializers.write_up(row))


@bp.get(API_PREFIX + "/write-ups/<write_up_id>")
@middleware.roles(*READ_ONE_ROLES)
def read_write_up(write_up_id):
    row = validation.path_row(db.write_ups, write_up_id, errors.ERR_WRITE_UP_NOT_FOUND)
    return response.object_response(serializers.write_up(row))


@bp.get(API_PREFIX + "/write-ups")
@middleware.roles(*READ_ROLES)
def list_write_ups():
    application_id = validation.filter_str("application_id")
    state = validation.filter_enum("state", C.WRITE_UP_STATES)
    rows = []
    for row in db.write_ups.values():
        if application_id is not None and row["application_id"] != application_id:
            continue
        if state is not None and row["state"] != state:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.write_up)


# ---------------------------------------------------------------------------
# repair lines
# ---------------------------------------------------------------------------


@bp.post(API_PREFIX + "/work-items")
@middleware.roles(middleware.REHAB_SPECIALIST)
def create_work_item():
    body = validation.json_body()
    write_up = validation.body_fk(
        body, "write_up_id", db.write_ups, errors.ERR_WRITE_UP_NOT_FOUND
    )
    validation.field_id(body, "write_up_id")
    description = validation.field_str(body, "description")
    category = validation.field_enum(body, "category", C.WORK_CATEGORIES)
    priority_class = validation.field_enum(body, "priority_class", C.PRIORITY_CLASSES)
    estimated_cost = validation.field_int(body, "estimated_cost_cents", minimum=1)
    is_lead = validation.field_bool(body, "is_lead_hazard_reduction", default=False)
    is_historic = validation.field_bool(body, "is_historic_sensitive", default=False)

    if write_up["state"] not in EDITABLE_STATES:
        fail(errors.ERR_INVALID_STATE, "Repair lines may only be edited on an open write-up.")

    multiplier = calc.work_item_multiplier(is_lead, is_historic)
    row = db.new_row(versioned=False)
    row.update(
        {
            "write_up_id": write_up["id"],
            "description": description,
            "category": category,
            "priority_class": priority_class,
            "estimated_cost_cents": estimated_cost,
            "is_lead_hazard_reduction": is_lead,
            "is_historic_sensitive": is_historic,
            "protocol_multiplier": float(multiplier),
            "line_total_cents": calc.work_item_line_total(estimated_cost, multiplier),
        }
    )
    db.work_items[row["id"]] = row

    domain.recompute_write_up(write_up)
    db.touch(write_up)

    return response.object_response(serializers.work_item(row), 201)


@bp.delete(API_PREFIX + "/work-items/<work_item_id>")
@middleware.roles(middleware.REHAB_SPECIALIST)
def delete_work_item(work_item_id):
    row = validation.path_row(db.work_items, work_item_id, errors.ERR_WORK_ITEM_NOT_FOUND)
    write_up = db.write_ups.get(row["write_up_id"])
    if write_up is None or write_up["state"] not in EDITABLE_STATES:
        fail(errors.ERR_INVALID_STATE, "Repair lines may only be edited on an open write-up.")

    del db.work_items[row["id"]]
    domain.recompute_write_up(write_up)
    db.touch(write_up)
    return response.no_content()


@bp.get(API_PREFIX + "/work-items/<work_item_id>")
@middleware.roles(*READ_ROLES)
def read_work_item(work_item_id):
    row = validation.path_row(db.work_items, work_item_id, errors.ERR_WORK_ITEM_NOT_FOUND)
    return response.object_response(serializers.work_item(row))


@bp.get(API_PREFIX + "/work-items")
@middleware.roles(*ITEM_LIST_ROLES)
def list_work_items():
    write_up_id = validation.filter_str("write_up_id")
    priority_class = validation.filter_enum("priority_class", C.PRIORITY_CLASSES)
    rows = []
    for row in db.work_items.values():
        if write_up_id is not None and row["write_up_id"] != write_up_id:
            continue
        if priority_class is not None and row["priority_class"] != priority_class:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.work_item)
