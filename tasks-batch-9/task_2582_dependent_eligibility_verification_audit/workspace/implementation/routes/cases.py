"""Audit cases: reads, the reminder cadence, and outreach history (section 3.3)."""

from flask import Blueprint

import calc
import clock
import constants as K
import db
import derive
import emit
import response
import serialize
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("cases", __name__)

READ_ROLES = ("ProgramAdmin", "VerificationAnalyst", "AppealReviewer", "RecoveryAgent")


def _case_or_404(case_id):
    case = db.get("cases", case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    return case


@bp.route("/audit-cases/<case_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_case(case_id):
    case = _case_or_404(case_id)
    return response.obj_out(serialize.case, case)


@bp.route("/audit-cases", methods=["GET"])
@endpoint(*READ_ROLES)
def list_cases():
    program_id = validate.query_filter("program_id")
    employee_id = validate.query_filter("employee_id")
    status = validate.query_filter("status")
    rows = db.ordered(
        "cases",
        lambda c: (program_id is None or c["program_id"] == program_id)
        and (employee_id is None or c["employee_id"] == employee_id)
        and (status is None or c["status"] == status),
    )
    return response.arr_out(serialize.case, rows, validate.paginate(rows))


@bp.route("/audit-cases/<case_id>/reminders", methods=["POST"])
@endpoint("ProgramAdmin", "VerificationAnalyst")
def send_reminder(case_id):
    case = _case_or_404(case_id)
    payload = validate.body()
    channel = validate.req_enum(payload, "channel", K.CHANNELS)
    template_code = validate.opt_str(payload, "template_code")

    if case["status"] not in ("NOTIFIED", "IN_PROGRESS"):
        raise ApiError("ERR_CASE_STATE_INVALID")

    program = db.get("programs", case["program_id"])
    now = clock.now()
    gap_days = calc.reminder_gap_days(case, now)
    min_gap = (program or {}).get("reminder_min_gap_days") or 0
    if gap_days is not None and gap_days < min_gap:
        raise ApiError("ERR_REMINDER_CADENCE_VIOLATION")

    max_reminders = (program or {}).get("max_reminders") or 0
    if (case.get("reminders_sent_count") or 0) >= max_reminders:
        raise ApiError("ERR_REMINDER_LIMIT_REACHED")

    emit.communication(case, "REMINDER", channel, template_code, now)
    db.set_fields(case, last_reminder_at=now)
    derive.refresh_all()
    return response.obj_out(serialize.case, case)


@bp.route("/audit-cases/<case_id>/communications", methods=["GET"])
@endpoint("ProgramAdmin", "VerificationAnalyst", "AppealReviewer")
def list_case_communications(case_id):
    case = _case_or_404(case_id)
    kind = validate.query_filter("kind")
    rows = db.ordered(
        "communications",
        lambda e: e["case_id"] == case["id"] and (kind is None or e["kind"] == kind),
    )
    return response.arr_out(serialize.communication, rows, validate.paginate(rows))


@bp.route("/audit-cases/<case_id>/amnesty-removals", methods=["GET"])
@endpoint("ProgramAdmin", "VerificationAnalyst", "RecoveryAgent")
def list_case_amnesty_removals(case_id):
    case = _case_or_404(case_id)
    rows = db.ordered("amnesty_removals", lambda r: r["case_id"] == case["id"])
    return response.arr_out(serialize.amnesty_removal, rows, validate.paginate(rows))
