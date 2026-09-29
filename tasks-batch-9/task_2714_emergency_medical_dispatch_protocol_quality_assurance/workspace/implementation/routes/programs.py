"""QA programmes (PRD 3.1) and the logical clock (PRD 2.4)."""
from decimal import Decimal

from flask import Blueprint

import calc
import helpers
import validate
from auth import ALL_OPERATORS, require
from envelope import ok, public
from errors import fail
from store import base_row, db, set_clock

bp = Blueprint("programs", __name__)

ACCREDITATION_BODIES = ("IAED", "NAED_LOCAL", "STATE_OEMS")


@bp.post("/audit-programs")
@require("ProgramAdmin")
def create_program():
    payload = validate.body()
    name = validate.get_str(payload, "name")
    body_name = validate.get_enum(payload, "accreditation_body", ACCREDITATION_BODIES)
    target = validate.get_decimal(
        payload, "target_compliance_pct", required=False, default=Decimal("90.0")
    )
    watch = validate.get_decimal(
        payload, "watch_floor_pct", required=False, default=Decimal("80.0")
    )
    high_risk = validate.get_decimal(
        payload, "high_risk_target_pct", required=False, default=Decimal("85.0")
    )
    review_deadline_days = validate.get_int(
        payload, "review_deadline_days", required=False, default=30, minimum=1
    )
    rebuttal_window_days = validate.get_int(
        payload, "rebuttal_window_days", required=False, default=14, minimum=1
    )
    max_rebuttal_rounds = validate.get_int(
        payload, "max_rebuttal_rounds", required=False, default=2, minimum=0, maximum=3
    )
    escalated_sample_floor = validate.get_int(
        payload, "escalated_sample_floor", required=False, default=25, minimum=1
    )
    hours_threshold = validate.get_decimal(
        payload,
        "hours_owed_restriction_threshold",
        required=False,
        default=Decimal("6.0"),
        minimum=0,
    )

    target = calc.q1(target)
    watch = calc.q1(watch)
    high_risk = calc.q1(high_risk)
    hours_threshold = calc.q1(hours_threshold)

    # PRD 3.1 — the three thresholds must be mutually coherent.
    if not (watch > Decimal("0.0") and watch < target and target <= Decimal("100.0")):
        fail(
            "ERR_INVALID_THRESHOLD_CONFIG",
            "Require 0.0 < watch_floor_pct < target_compliance_pct <= 100.0.",
        )
    if not (high_risk > Decimal("0.0") and high_risk <= Decimal("100.0")):
        fail(
            "ERR_INVALID_THRESHOLD_CONFIG",
            "Require 0.0 < high_risk_target_pct <= 100.0.",
        )

    program = base_row()
    program.update(
        {
            "name": name,
            "accreditation_body": body_name,
            "target_compliance_pct": target,
            "watch_floor_pct": watch,
            "high_risk_target_pct": high_risk,
            "review_deadline_days": review_deadline_days,
            "rebuttal_window_days": rebuttal_window_days,
            "max_rebuttal_rounds": max_rebuttal_rounds,
            "escalated_sample_floor": escalated_sample_floor,
            "hours_owed_restriction_threshold": hours_threshold,
            "accreditation_status": "SETUP",
            "latest_compliance_pct": None,
            "submitted_report_count": 0,
            "sentinel_event_count": 0,
        }
    )
    db.programs[program["id"]] = program
    return ok(public(program), 201)


@bp.get("/audit-programs/<program_id>")
@require(*ALL_OPERATORS)
def read_program(program_id):
    return ok(public(helpers.program(program_id)))


@bp.post("/_clock/set_current_utc")
@require("ProgramAdmin")
def set_current_utc():
    payload = validate.body()
    instant = validate.get_instant(payload, "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": instant})
