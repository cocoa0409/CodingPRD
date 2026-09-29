"""Logical clock control and the reconciliation checkpoint (PRD 2.6)."""

from flask import Blueprint

import db
import services
import validate
from db import all_of, clock_date, clock_now, parse_date, set_clock
from errors import ApiError
from middleware import endpoint
from routes.common import ok_data

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_current_utc():
    body = validate.body()
    instant = validate.f_instant(body, "current_utc")
    if instant <= clock_now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")

    set_clock(instant)

    for case in all_of("case"):
        services.refresh_case_timeliness(case)
        services.refresh_case_follow_up(case)

    for source in all_of("source"):
        services.refresh_source_completeness(source,
                                             write_reconciled_through=True)

    today = clock_date()
    sweepable = []
    for deficiency in all_of("deficiency"):
        if deficiency["deficiency_state"] != "CITED":
            continue
        due = parse_date(deficiency["response_due_date"])
        if due is not None and today > due:
            sweepable.append(deficiency)
    sweepable.sort(key=lambda d: (d["response_due_date"], d["created_at"],
                                  d["_seq"]))
    for deficiency in sweepable:
        services.escalate_deficiency(deficiency)

    for program in all_of("program"):
        services.refresh_program_follow_up(program)
        services.refresh_program_conference(program)
        services.refresh_program_aggregates(program)

    for abstractor in all_of("abstractor"):
        services.refresh_abstractor_quality(abstractor)
        services.refresh_abstractor_productivity(abstractor)

    return ok_data({})
