"""Append-only job change events and the re-analysis cascade (PRD 3.9)."""
from flask import Blueprint

import db
from constants import TRIGGER_TYPES
from middleware import body, endpoint
from response import success
from services import calculations, derive, lookup, serialize
from validation import (
    opt_int,
    opt_num,
    opt_state_code,
    req_enum,
    req_int,
    req_num,
    req_state_code,
    req_str,
)

bp = Blueprint("job_change_triggers", __name__)


@bp.post("/job-change-triggers")
@endpoint(["ComplianceAnalyst"])
def create_trigger():
    payload = body()
    position_id = req_str(payload, "position_id")
    trigger_type = req_enum(payload, "trigger_type", TRIGGER_TYPES)

    # rank 4: each type requires exactly one payload field
    if trigger_type == "SALARY_CHANGE":
        new_annual_salary_cents = req_int(payload, "new_annual_salary_cents", minimum=1)
    else:
        new_annual_salary_cents = opt_int(payload, "new_annual_salary_cents", minimum=1)
    if trigger_type == "DUTIES_CHANGE":
        new_exempt_duty_pct = req_num(
            payload, "new_exempt_duty_pct", minimum=0, maximum=100
        )
    else:
        new_exempt_duty_pct = opt_num(
            payload, "new_exempt_duty_pct", minimum=0, maximum=100
        )
    if trigger_type == "REPORTING_CHANGE":
        new_supervises_headcount = req_int(
            payload, "new_supervises_headcount", minimum=0
        )
    else:
        new_supervises_headcount = opt_int(
            payload, "new_supervises_headcount", minimum=0
        )
    if trigger_type == "STATE_CHANGE":
        new_work_state_code = req_state_code(payload, "new_work_state_code")
    else:
        new_work_state_code = opt_state_code(payload, "new_work_state_code")

    # rank 5: foreign key
    position = lookup.position(position_id)

    inputs = {
        "new_annual_salary_cents": new_annual_salary_cents,
        "new_exempt_duty_pct": new_exempt_duty_pct,
        "new_supervises_headcount": new_supervises_headcount,
        "new_work_state_code": new_work_state_code,
    }
    requires_reanalysis, reason_code = calculations.reanalysis_requirement(
        position, trigger_type, inputs
    )

    row = db.make_row(
        versioned=False,
        position_id=position["id"],
        trigger_type=trigger_type,
        requires_reanalysis=requires_reanalysis,
        reason_code=reason_code,
        **inputs
    )
    db.job_change_triggers[row["id"]] = row

    if not requires_reanalysis:
        # the event is recorded, but nothing else moves at all
        return success(serialize.job_change_trigger(row), 201)

    # 1. write the changed attribute onto the position
    if trigger_type == "SALARY_CHANGE":
        position["annual_salary_cents"] = new_annual_salary_cents
    elif trigger_type == "DUTIES_CHANGE":
        position["self_reported_exempt_pct_override"] = new_exempt_duty_pct
    elif trigger_type == "STATE_CHANGE":
        position["work_state_code"] = new_work_state_code

    # 2. supersede every analysis of the position that is not already superseded
    for analysis in db.ordered(
        [
            a
            for a in db.exemption_analyses.values()
            if a["position_id"] == position["id"] and a["status"] != "SUPERSEDED"
        ]
    ):
        analysis["status"] = "SUPERSEDED"
        db.touch(analysis)

    # 3. the position returns to UNREVIEWED regardless
    position["classification_status"] = "UNREVIEWED"

    # 4. a duties change withdraws every attested account
    if trigger_type == "DUTIES_CHANGE":
        for interview in derive.interviews_of(position["id"]):
            if interview["status"] == "ATTESTED":
                interview["status"] = "VOIDED"
                interview["void_reason"] = "CHANGE_TRIGGER_DUTIES"
                db.touch(interview)

    # 5. position duty fields, then family risk, then engagement posture
    lookup.touch_position_chain(position)
    return success(serialize.job_change_trigger(row), 201)
