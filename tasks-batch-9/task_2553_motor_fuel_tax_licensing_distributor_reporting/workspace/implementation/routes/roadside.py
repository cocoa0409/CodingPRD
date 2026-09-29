"""Roadside dyed-fuel enforcement and the four-hop cascade (PRD 3.8)."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, FIELD_INSPECTOR, LICENSEE_AGENT,
                        RETURNS_EXAMINER, TAX_SUPERVISOR)
from services import calc, cascade, derive

bp = Blueprint("roadside", __name__, url_prefix="/mft")

READ_ROLES = (FIELD_INSPECTOR, TAX_SUPERVISOR, AUDIT_MANAGER, RETURNS_EXAMINER,
              LICENSEE_AGENT)
DYE_RESULTS = ["NEGATIVE", "POSITIVE"]


def _rank(row):
    return (row["inspection_date"], row["created_at"], row["_seq"])


def _prior_positive_count(row):
    """Frozen at assessment; a later dismissal never cheapens this penalty."""
    mine = _rank(row)
    count = 0
    for other in db.inspections.values():
        if other["id"] == row["id"]:
            continue
        if other["inspected_licensee_id"] != row["inspected_licensee_id"]:
            continue
        if other["dye_test_result"] != "POSITIVE" or other["status"] == "DISMISSED":
            continue
        if _rank(other) < mine:
            count += 1
    return count


@bp.post("/roadside-inspections")
def record_inspection():
    user_id, role = middleware.require(FIELD_INSPECTOR)
    body = shape.body()
    licensee_id = shape.req_id(body, "inspected_licensee_id")
    inspection_date = shape.req_date(body, "inspection_date")
    dye_test_result = shape.req_enum(body, "dye_test_result", DYE_RESULTS)
    gallons_in_tank = shape.req_gallons(body, "gallons_in_tank", ge=calc.ZERO)
    vehicle_identifier = shape.req_str(body, "vehicle_identifier")
    location_description = shape.opt_str(body, "location_description")

    licensee = helpers.body_licensee(licensee_id)

    row = db.base_row()
    row.update({
        "inspected_licensee_id": licensee_id,
        "inspection_date": inspection_date,
        "dye_test_result": dye_test_result,
        "gallons_in_tank": gallons_in_tank,
        "vehicle_identifier": vehicle_identifier,
        "location_description": location_description,
        "prior_positive_count": 0,
        "penalty_cents": 0,
        "status": "RECORDED",
        "dismissal_reason": None,
    })
    db.inspections[row["id"]] = row

    # A NEGATIVE result is recorded and nothing else happens.  A revoked
    # licensee's vehicle cannot be the subject of a penalty assessment.
    if dye_test_result == "POSITIVE" and licensee["status"] != "REVOKED":
        # Hop one: freeze the count, assess, post the penalty.
        prior = _prior_positive_count(row)
        row["prior_positive_count"] = prior
        row["penalty_cents"] = calc.dyed_penalty_cents(gallons_in_tank, prior)
        row["status"] = "PENALTY_ASSESSED"
        cascade.post_ledger(licensee_id, "PENALTY", row["penalty_cents"],
                            "RoadsideInspection", row["id"],
                            "Dyed-fuel penalty for vehicle %s"
                            % vehicle_identifier)
        # Hop two: the suspension, conditional on the new violation count.
        if (derive.dyed_violation_count(licensee_id)
                >= calc.DYED_SUSPENSION_THRESHOLD
                and licensee["status"] == "ACTIVE"):
            licensee["status"] = "SUSPENDED"
            db.touch(licensee)
            # Hop three re-derives the doubled bond requirement; hop four
            # freezes pending claims only while a deficiency remains.
            cascade.apply_bond_deficiency_hold(licensee)

    return response.object_response(derive.inspection_json(row), 201)


@bp.get("/roadside-inspections/<inspection_id>")
def read_inspection(inspection_id):
    middleware.require(*READ_ROLES)
    row = helpers.find("inspection", inspection_id)
    return response.object_response(derive.inspection_json(row))


@bp.get("/roadside-inspections")
def list_inspections():
    middleware.require(*READ_ROLES)
    rows = db.ordered(db.inspections)
    rows = helpers.filter_by(rows, {
        "inspected_licensee_id": "inspected_licensee_id",
        "dye_test_result": "dye_test_result",
        "status": "status",
    })
    return response.list_response(rows, derive.inspection_json)


@bp.post("/roadside-inspections/<inspection_id>/dismiss")
def dismiss_inspection(inspection_id):
    middleware.require(TAX_SUPERVISOR)
    body = shape.body()
    dismissal_reason = shape.req_str(body, "dismissal_reason")
    row = helpers.find("inspection", inspection_id)

    if row["status"] != "PENALTY_ASSESSED":
        raise ApiError("ERR_INSPECTION_NOT_DISMISSIBLE")

    row["status"] = "DISMISSED"
    row["dismissal_reason"] = dismissal_reason
    db.touch(row)
    # A compensating entry, never a deletion of the original PENALTY row.
    cascade.post_ledger(row["inspected_licensee_id"], "PENALTY_REVERSAL",
                        -row["penalty_cents"], "RoadsideInspection", row["id"],
                        "Dismissal of dyed-fuel penalty: %s" % dismissal_reason)
    return response.object_response(derive.inspection_json(row))
