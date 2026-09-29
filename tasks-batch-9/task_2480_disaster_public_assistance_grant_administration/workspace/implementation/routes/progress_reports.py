"""ProgressReport endpoints: quarterly filing."""
from flask import Blueprint

from db import now, now_iso, parse_instant, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.ledger import (
    cascade_applicant,
    create_progress_report,
    reports_of_applicant,
)
from validate import QUARTER_RE, body, v_id, v_int, v_num, v_str

bp = Blueprint("progress_reports", __name__)


def _status_for_clock(due_at):
    due = parse_instant(due_at)
    if due is not None and now() <= due:
        return "SUBMITTED"
    return "LATE"


@bp.route(PREFIX + "/progress-reports", methods=["POST"])
def create_report():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_owner = payload.get("applicant_id")
    if isinstance(raw_owner, str):
        check_scope(actor, raw_owner)

    applicant_id = v_id(payload, "applicant_id")
    quarter_label = v_str(payload, "quarter_label")
    if not QUARTER_RE.match(quarter_label):
        fail("ERR_INVALID_REQUEST", "quarter_label must match ^\\d{4}-Q[1-4]$")
    expenditures = v_int(payload, "expenditures_to_date_cents", required=False,
                         default=0, minimum=0)
    pct_complete = v_num(payload, "pct_complete", required=False, default=0,
                         minimum=0, maximum=100)

    applicant = require("applicants", applicant_id)

    for existing in reports_of_applicant(applicant_id):
        if existing["quarter_label"] == quarter_label:
            fail("ERR_DUPLICATE_REPORT_PERIOD",
                 "a report already exists for %s" % quarter_label)

    row = create_progress_report(applicant, quarter_label, "DUE",
                                 expenditures=expenditures,
                                 pct_complete=pct_complete)
    setf(row, "status", _status_for_clock(row["due_at"]))
    setf(row, "submitted_at", now_iso())
    return respond(row, 201)


@bp.route(PREFIX + "/progress-reports", methods=["GET"])
def list_reports():
    authenticate(ALL_ROLES)
    return render_list("progress_reports", {
        "applicant_id": "applicant_id",
        "status": "status",
        "quarter_label": "quarter_label",
    })


@bp.route(PREFIX + "/progress-reports/<progress_report_id>", methods=["GET"])
def get_report(progress_report_id):
    actor = authenticate(ALL_ROLES)
    row = find("progress_reports", progress_report_id)
    if row is not None:
        check_scope(actor, row["applicant_id"])
    row = require("progress_reports", progress_report_id)
    return respond(row)


@bp.route(PREFIX + "/progress-reports/<progress_report_id>/submit", methods=["POST"])
def submit_report(progress_report_id):
    actor = authenticate(("ApplicantAgent",))
    row = find("progress_reports", progress_report_id)
    if row is not None:
        check_scope(actor, row["applicant_id"])
    row = require("progress_reports", progress_report_id)

    payload = body()
    expenditures = v_int(payload, "expenditures_to_date_cents", minimum=0)
    pct_complete = v_num(payload, "pct_complete", minimum=0, maximum=100)

    if row["status"] not in ("DUE", "DELINQUENT"):
        fail("ERR_REPORT_ALREADY_SUBMITTED",
             "this report has already been filed")

    was_delinquent = row["status"] == "DELINQUENT"

    setf(row, "expenditures_to_date_cents", expenditures)
    setf(row, "pct_complete", pct_complete)
    setf(row, "submitted_at", now_iso())
    setf(row, "status", _status_for_clock(row["due_at"]))
    touch(row)

    if was_delinquent:
        cascade_applicant(find("applicants", row["applicant_id"]))

    return respond(row)
