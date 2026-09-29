"""Drawdown endpoints: cash request, disbursement decision and refund."""
from flask import Blueprint

from db import new_row, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.ledger import cascade_applicant, disaster_of_applicant
from validate import body, v_enum, v_id, v_int, v_str

bp = Blueprint("drawdowns", __name__)


@bp.route(PREFIX + "/drawdowns", methods=["POST"])
def create_drawdown():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_owner = payload.get("applicant_id")
    if isinstance(raw_owner, str):
        check_scope(actor, raw_owner)

    applicant_id = v_id(payload, "applicant_id")
    project_id = v_id(payload, "project_id")
    requested_cents = v_int(payload, "requested_cents", minimum=1)
    expected_version = v_int(payload, "expected_applicant_version", minimum=0)

    applicant = require("applicants", applicant_id)
    project = require("projects", project_id)

    if applicant["version"] != expected_version:
        fail("ERR_STALE_APPLICANT_VERSION",
             "expected_applicant_version %s does not match the current version %s"
             % (expected_version, applicant["version"]))

    if project["status"] != "OBLIGATED":
        fail("ERR_PROJECT_INVALID_STATE",
             "cash may only be drawn against an OBLIGATED project")

    if applicant["eligibility_status"] != "ELIGIBLE":
        fail("ERR_APPLICANT_NOT_ELIGIBLE", "the applicant is not ELIGIBLE")

    if project["applicant_id"] != applicant_id:
        fail("ERR_CROSS_APPLICANT_REFERENCE",
             "the project belongs to another applicant")

    if applicant["drawdown_status"] != "ACTIVE":
        fail("ERR_DRAWDOWN_SUSPENDED", "the applicant's drawdowns are SUSPENDED")

    if requested_cents > applicant["available_drawdown_cents"]:
        fail("ERR_DRAWDOWN_EXCEEDS_AVAILABLE",
             "requested_cents exceeds available_drawdown_cents")

    row = new_row("drawdowns", {
        "applicant_id": applicant_id,
        "project_id": project_id,
        "requested_cents": requested_cents,
        "approved_cents": 0,
        "refunded_cents": 0,
        "status": "REQUESTED",
        "disbursed_by_user_id": None,
        "rejection_reason": None,
    })
    touch(applicant)
    return respond(row, 201)


@bp.route(PREFIX + "/drawdowns", methods=["GET"])
def list_drawdowns():
    authenticate(ALL_ROLES)
    return render_list("drawdowns", {
        "applicant_id": "applicant_id",
        "project_id": "project_id",
        "status": "status",
    })


@bp.route(PREFIX + "/drawdowns/<drawdown_id>", methods=["GET"])
def get_drawdown(drawdown_id):
    actor = authenticate(ALL_ROLES)
    row = find("drawdowns", drawdown_id)
    if row is not None:
        check_scope(actor, row["applicant_id"])
    row = require("drawdowns", drawdown_id)
    return respond(row)


@bp.route(PREFIX + "/drawdowns/<drawdown_id>/disburse", methods=["POST"])
def disburse_drawdown(drawdown_id):
    actor = authenticate(("GrantsOfficer",))
    drawdown = require("drawdowns", drawdown_id)
    payload = body()

    decision = v_enum(payload, "decision", ("PAY", "REJECT"))
    rejection_reason = None
    if decision == "REJECT":
        rejection_reason = v_str(payload, "rejection_reason", non_empty=False)

    if drawdown["status"] != "REQUESTED":
        fail("ERR_DRAWDOWN_INVALID_STATE",
             "only a REQUESTED drawdown may be decided")

    applicant = find("applicants", drawdown["applicant_id"])
    project = find("projects", drawdown["project_id"])

    if decision == "PAY":
        if project is not None and project["obligated_by_user_id"] is not None \
                and project["obligated_by_user_id"] == actor.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the officer who obligated this project may not disburse against it")
        if applicant is None or applicant["drawdown_status"] != "ACTIVE":
            fail("ERR_DRAWDOWN_SUSPENDED", "the applicant's drawdowns are SUSPENDED")

        setf(drawdown, "approved_cents", drawdown["requested_cents"])
        setf(drawdown, "status", "PAID")
        setf(drawdown, "disbursed_by_user_id", actor.user_id)
        disaster = cascade_applicant(applicant)
        touch(applicant)
        if disaster is not None:
            touch(disaster)
    else:
        setf(drawdown, "status", "REJECTED")
        setf(drawdown, "rejection_reason", rejection_reason)

    touch(drawdown)
    return respond(drawdown)


@bp.route(PREFIX + "/drawdowns/<drawdown_id>/refund", methods=["POST"])
def refund_drawdown(drawdown_id):
    actor = authenticate(("ApplicantAgent",))
    drawdown = find("drawdowns", drawdown_id)
    if drawdown is not None:
        check_scope(actor, drawdown["applicant_id"])
    drawdown = require("drawdowns", drawdown_id)

    payload = body()
    refund_cents = v_int(payload, "refund_cents", minimum=0)

    if drawdown["status"] != "PAID":
        fail("ERR_DRAWDOWN_INVALID_STATE", "only a PAID drawdown may be refunded")

    if refund_cents > drawdown["approved_cents"]:
        fail("ERR_REFUND_EXCEEDS_DRAWDOWN",
             "refund_cents exceeds the disbursed approved_cents")

    setf(drawdown, "refunded_cents", refund_cents)
    setf(drawdown, "status", "REFUNDED")

    applicant = find("applicants", drawdown["applicant_id"])
    disaster = cascade_applicant(applicant)
    if applicant is not None:
        touch(applicant)
    if disaster is None:
        disaster = disaster_of_applicant(applicant)
    if disaster is not None:
        touch(disaster)

    touch(drawdown)
    return respond(drawdown)
