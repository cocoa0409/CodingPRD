"""Approval conditions: reads, mitigation payment, compliance, violation."""
from flask import Blueprint

import cascades
import clock
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("approval_conditions", __name__)

CONDITION_STATUSES = ("IMPOSED", "SATISFIED", "VIOLATED", "RELEASED")
PAYMENT_STATUSES = ("NOT_APPLICABLE", "OUTSTANDING", "PAID", "REVERSED")


@bp.route("/transfer-applications/<aid>/approval-conditions", methods=["GET"])
def list_conditions(aid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    app = common.get_app(aid)
    middleware.require_owner(caller, common.app_owner(app))

    limit, offset = validate.pagination()
    status = validate.query_enum("status", CONDITION_STATUSES)
    payment_status = validate.query_enum("payment_status", PAYMENT_STATUSES)

    rows = []
    for row in derive.conditions_for_app(app["id"]):
        if status is not None and row["status"] != status:
            continue
        if payment_status is not None and row["payment_status"] != payment_status:
            continue
        rows.append(row)
    rows = common.sort_created_asc(rows)
    return common.emit(rows, serialize.approval_condition, limit, offset)


@bp.route("/approval-conditions/<cid>", methods=["GET"])
def get_condition(cid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    condition = common.get_condition(cid)
    middleware.require_owner(caller, common.condition_owner(condition))
    return response.object_response(serialize.approval_condition(condition))


@bp.route("/approval-conditions/<cid>/pay", methods=["POST"])
def pay_condition(cid):
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ADJUDICATOR)
    )
    condition = common.get_condition(cid)
    owner_id = common.condition_owner(condition)
    middleware.require_owner(caller, owner_id)
    validate.get_body(required=False)

    if condition["payment_status"] != "OUTSTANDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an OUTSTANDING mitigation fee may be paid (payment_status is %s)."
            % condition["payment_status"],
        )
    claimant = db.claimants.get(owner_id)
    if claimant is not None and claimant["standing_status"] == "BARRED":
        raise ApiError(
            "ERR_CLAIMANT_NOT_IN_GOOD_STANDING",
            "A BARRED claimant may not transact.",
        )

    condition["payment_status"] = "PAID"
    db.touch(condition)

    app = db.transfer_applications.get(condition["transfer_application_id"])
    if app is not None:
        derive.recompute_app(app)
    if claimant is not None:
        derive.apply_fee_cascade(claimant)
    return response.object_response(serialize.approval_condition(condition))


@bp.route("/approval-conditions/<cid>/satisfy", methods=["POST"])
def satisfy_condition(cid):
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ADJUDICATOR)
    )
    condition = common.get_condition(cid)
    middleware.require_owner(caller, common.condition_owner(condition))

    body = validate.get_body()
    validate.req_str(body, "compliance_evidence", min_len=1, max_len=500)

    if condition["status"] not in ("IMPOSED", "VIOLATED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A condition in status %s cannot be satisfied." % condition["status"],
        )
    if condition["payment_status"] not in ("NOT_APPLICABLE", "PAID"):
        raise ApiError(
            "ERR_CONDITION_FEE_OUTSTANDING",
            "The mitigation fee must be paid before the condition can be satisfied.",
        )

    condition["status"] = "SATISFIED"
    db.touch(condition)
    return response.object_response(serialize.approval_condition(condition))


@bp.route("/approval-conditions/<cid>/violate", methods=["POST"])
def violate_condition(cid):
    middleware.authenticate((middleware.ROLE_ANALYST,))
    condition = common.get_condition(cid)

    body = validate.get_body()
    validate.req_str(body, "violation_note", min_len=1, max_len=500)

    if condition["status"] != "IMPOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an IMPOSED condition may be marked violated (status is %s)."
            % condition["status"],
        )
    due = condition["compliance_due_date"]
    if due is not None and clock.now() < clock.parse_date(due):
        raise ApiError(
            "ERR_WINDOW_STILL_OPEN",
            "The compliance window runs until %s." % due,
        )

    cascades.condition_violation(condition)
    return response.object_response(serialize.approval_condition(condition))
