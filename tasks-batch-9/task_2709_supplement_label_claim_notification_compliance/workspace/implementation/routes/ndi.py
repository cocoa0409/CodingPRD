"""New dietary ingredient notification and the 75-day waiting period (PRD 3.2)."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("ndi_notifications", __name__)

READ_ROLES = (
    auth.ROLE_SPECIALIST,
    auth.ROLE_REVIEWER,
    auth.ROLE_APPROVAL,
    auth.ROLE_QA,
    auth.ROLE_AUDITOR,
)


def _sync_ingredient_flag(ingredient):
    ingredient["ndi_notification_required"] = (
        ingredient["eligibility_status"] in calc.NDI_REQUIRED_STATES
    )


@bp.route(PREFIX + "/ndi-notifications", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def create_notification():
    body = validate.body()
    ingredient_id = validate.req_str(body, "ingredient_id")
    submitter_reference = validate.req_str(body, "submitter_reference")
    safety_narrative = validate.req_str(body, "safety_narrative")

    fk_row("ingredients", ingredient_id, errors.ERR_INGREDIENT_NOT_FOUND)

    row = db.base_fields()
    row.update(
        {
            "ingredient_id": ingredient_id,
            "submitter_reference": submitter_reference,
            "safety_narrative": safety_narrative,
            "notification_status": "DRAFT",
            "submitted_at": None,
            "waiting_period_end": None,
            "agency_response_at": None,
            "agency_objection_reason": None,
        }
    )
    db.insert("ndi_notifications", row)
    return response.object_response(serialize.ndi_notification(row), 201)


@bp.route(PREFIX + "/ndi-notifications/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_notification(row_id):
    row = path_row("ndi_notifications", row_id, errors.ERR_NDI_NOTIFICATION_NOT_FOUND)
    return response.object_response(serialize.ndi_notification(row))


@bp.route(PREFIX + "/ndi-notifications", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_notifications():
    return listing(
        "ndi_notifications",
        serialize.ndi_notification,
        filters=("ingredient_id", "notification_status"),
    )


@bp.route(PREFIX + "/ndi-notifications/<row_id>/submit", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def submit_notification(row_id):
    row = path_row("ndi_notifications", row_id, errors.ERR_NDI_NOTIFICATION_NOT_FOUND)
    if row["notification_status"] != "DRAFT":
        fail(
            errors.ERR_NDI_NOTIFICATION_STATE_INVALID,
            "Only a DRAFT notification may be filed with the agency.",
        )

    now = db.now()
    candidate_end = calc.add_days(now, calc.WAITING_PERIOD_DAYS)
    for other in db.all_rows("ndi_notifications"):
        if other["id"] == row["id"]:
            continue
        if other["ingredient_id"] != row["ingredient_id"]:
            continue
        if other["notification_status"] != "SUBMITTED":
            continue
        # Half-open occupancy: touching the exclusive upper bound is adjacent, not overlapping.
        if now < other["waiting_period_end"] and other["submitted_at"] < candidate_end:
            fail(
                errors.ERR_NDI_WINDOW_OVERLAP,
                "The 75-day waiting period overlaps another submitted notification.",
            )

    row["notification_status"] = "SUBMITTED"
    row["submitted_at"] = now
    row["waiting_period_end"] = candidate_end
    db.touch(row)

    ingredient = db.get("ingredients", row["ingredient_id"])
    if ingredient is not None and ingredient["eligibility_status"] == "NDI_REQUIRED":
        ingredient["eligibility_status"] = "NDI_PENDING"
        _sync_ingredient_flag(ingredient)
        db.touch(ingredient)

    return response.object_response(serialize.ndi_notification(row))


@bp.route(PREFIX + "/ndi-notifications/<row_id>/agency-response", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def agency_response(row_id):
    row = path_row("ndi_notifications", row_id, errors.ERR_NDI_NOTIFICATION_NOT_FOUND)
    body = validate.body()
    decision = validate.req_enum(body, "response", calc.AGENCY_RESPONSES)
    objection_reason = validate.opt_str(body, "agency_objection_reason")

    if row["notification_status"] != "SUBMITTED":
        fail(
            errors.ERR_NDI_NOTIFICATION_STATE_INVALID,
            "Only a SUBMITTED notification may receive an agency response.",
        )

    now = db.now()
    if decision == "ACKNOWLEDGE" and now < row["waiting_period_end"]:
        fail(
            errors.ERR_WAITING_PERIOD_NOT_ELAPSED,
            "The 75-day premarket waiting period has not elapsed.",
        )

    ingredient = db.get("ingredients", row["ingredient_id"])
    row["agency_response_at"] = now

    if decision == "ACKNOWLEDGE":
        row["notification_status"] = "ACKNOWLEDGED"
        db.touch(row)
        if ingredient is not None and ingredient["eligibility_status"] == "NDI_PENDING":
            ingredient["eligibility_status"] = "NDI_ACKNOWLEDGED"
            _sync_ingredient_flag(ingredient)
            db.touch(ingredient)
    else:
        row["notification_status"] = "OBJECTED"
        row["agency_objection_reason"] = objection_reason
        db.touch(row)
        if ingredient is not None and ingredient["eligibility_status"] == "NDI_PENDING":
            ingredient["eligibility_status"] = "NDI_OBJECTED"
            _sync_ingredient_flag(ingredient)
            db.touch(ingredient)
            cascade.ingredient_objection_cascade(ingredient)

    return response.object_response(serialize.ndi_notification(row))
