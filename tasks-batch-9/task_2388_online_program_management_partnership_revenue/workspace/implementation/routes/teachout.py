"""Teach-out plan certification and its liability waterfall."""

from flask import Blueprint

import db
import serializers
from db import touch
from errors import ApiError, bad_request
from middleware import authenticate, body
from response import object_response
from routes.common import get_partnership, get_plan, get_program
from services.cascades import allocate_liability
from services.derive import recompute_partnership
from services.money import parse_iso_date
from validation import Field, validate_body

bp = Blueprint("teachout", __name__)

CERTIFY_SPEC = {
    "asset_transfer_confirmed": Field("boolean", required=True),
    "certification_note": Field("string"),
}

NOTICE_MIN_DAYS = 90


@bp.post("/teach-out-plans/<plan_id>/certify")
def certify(plan_id):
    uid, role = authenticate(("ComplianceAuditor",))
    values = validate_body(body(), CERTIFY_SPEC)
    if values["asset_transfer_confirmed"] is not True:
        raise bad_request("asset_transfer_confirmed must be true to certify a plan.")

    plan = get_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_TEACH_OUT_PLAN_INVALID_STATE")

    program = get_program(plan["program_id"])
    if program["status"] != "TEACH_OUT":
        raise ApiError("ERR_PROGRAM_INVALID_STATE")

    notice = parse_iso_date(plan["student_notification_date"])
    end = parse_iso_date(plan["teach_out_end_date"])
    if (end - notice).days < NOTICE_MIN_DAYS:
        raise ApiError("ERR_TEACH_OUT_NOTICE_TOO_SHORT")

    partnership = get_partnership(program["partnership_id"])
    allocate_liability(plan, program, partnership)

    plan["status"] = "CERTIFIED"
    plan["certified_by_user_id"] = uid
    plan["certified_at"] = db.now_iso()
    touch(plan)

    recompute_partnership(partnership)
    return object_response(serializers.teach_out_plan(plan))
