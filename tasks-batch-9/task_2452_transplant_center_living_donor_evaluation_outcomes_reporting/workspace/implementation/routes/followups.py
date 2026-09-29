"""Donor follow-up submission and waiver (PRD 3.7)."""

from flask import Blueprint

import calc
import domain
import serialize
from db import db, now, touch
from errors import ApiError
from middleware import authenticate
from response import object_response
from util import dec
from validation import get_body, req_list, req_str

bp = Blueprint("followups", __name__)

OPEN_FOLLOW_UP_STATUSES = ("DUE", "INCOMPLETE", "DELINQUENT")


def find_follow_up(follow_up_id):
    row = db.follow_ups.get(follow_up_id)
    if row is None:
        raise ApiError(
            "ERR_FOLLOW_UP_NOT_FOUND", "no DonorFollowUp with id %s" % follow_up_id
        )
    return row


@bp.post("/donor-follow-ups/<follow_up_id>/submission")
def submit_follow_up(follow_up_id):
    authenticate(["TransplantCoordinator"])
    follow_up = find_follow_up(follow_up_id)

    body = get_body()
    submitted_fields = req_list(body, "submitted_fields")

    # priority 9 -- WAIVED and SUBMITTED_COMPLETE accept nothing further
    if follow_up["status"] not in OPEN_FOLLOW_UP_STATUSES:
        raise ApiError(
            "ERR_FOLLOW_UP_TERMINAL",
            "a follow-up in %s accepts no submission" % follow_up["status"],
        )

    # priority 21 -- the interval must actually be due
    clock = now()
    if clock < follow_up["due_on"]:
        raise ApiError(
            "ERR_FOLLOW_UP_NOT_DUE", "the follow-up interval is not due yet"
        )

    count = calc.submitted_field_count(submitted_fields, follow_up["required_fields_count"])
    pct = calc.completeness_pct(count, follow_up["required_fields_count"])

    program = domain.program_of_follow_up(follow_up)
    threshold = dec(program["follow_up_completeness_threshold_pct"])

    follow_up["submitted_field_count"] = count
    follow_up["completeness_pct"] = pct
    follow_up["status"] = "SUBMITTED_COMPLETE" if pct >= threshold else "INCOMPLETE"
    follow_up["submitted_at"] = clock
    touch(follow_up)

    domain.refresh_posture(program)
    return object_response(serialize.donor_follow_up(follow_up))


@bp.post("/donor-follow-ups/<follow_up_id>/waiver")
def waive_follow_up(follow_up_id):
    authenticate(["ProgramAdmin"])
    follow_up = find_follow_up(follow_up_id)

    body = get_body()
    waiver_reason_code = req_str(body, "waiver_reason_code")

    # priority 9
    if follow_up["status"] not in OPEN_FOLLOW_UP_STATUSES:
        raise ApiError(
            "ERR_FOLLOW_UP_TERMINAL",
            "a follow-up in %s accepts no waiver" % follow_up["status"],
        )

    follow_up["status"] = "WAIVED"
    follow_up["waiver_reason_code"] = waiver_reason_code
    touch(follow_up)

    domain.refresh_posture(domain.program_of_follow_up(follow_up))
    return object_response(serialize.donor_follow_up(follow_up))
