"""Aggregate report snapshots (PRD 3.12)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import calc, serialize

bp = Blueprint("reports", __name__)


def _students_in_scope(school_id):
    students = store.all_rows("students")
    if school_id is None:
        return students
    scoped = []
    year = clock.current_school_year()
    for student in students:
        for enrollment in store.DB["enrollments"].values():
            if (
                enrollment["student_id"] == student["id"]
                and enrollment["school_id"] == school_id
                and enrollment["school_year"] == year
                and enrollment["status"] in ("ACTIVE", "WITHDRAWN", "TRANSFERRED")
            ):
                scoped.append(student)
                break
    return scoped


def _student_is_scoped(student_id, school_id):
    year = clock.current_school_year()
    for enrollment in store.DB["enrollments"].values():
        if (
            enrollment["student_id"] == student_id
            and enrollment["school_id"] == school_id
            and enrollment["school_year"] == year
            and enrollment["status"] in ("ACTIVE", "WITHDRAWN", "TRANSFERRED")
        ):
            return True
    return False


@bp.post("/sbhc/reports")
def create_report():
    op = Op("POST /sbhc/reports", ["SbhcAdmin"])
    op.body_id("school", "schools", "school_id", "ERR_SCHOOL_NOT_FOUND")
    op.schema(
        [
            Field("period_start_date", "date", required=True),
            Field("period_end_date", "date", required=True),
            Field("school_id", "string"),
            Field("visit_type_filter", "enum", values=config.VISIT_TYPES),
        ]
    )

    def _period(op):
        start = clock.parse_date(op.body["period_start_date"])
        end = clock.parse_date(op.body["period_end_date"])
        if end < start:
            raise ApiError(
                "ERR_INVALID_REPORT_PERIOD",
                "period_end_date must be the same as or later than period_start_date.",
            )

    op.hook(8, _period)
    op.run()

    school_id = op.field("school_id", None)
    visit_type_filter = op.field("visit_type_filter", None)
    start = clock.parse_date(op.body["period_start_date"])
    end = clock.parse_date(op.body["period_end_date"])

    def in_period(row):
        created = clock.parse_datetime(row["created_at"]).date()
        return start <= created <= end

    visits = [v for v in store.all_rows("visits") if in_period(v)]
    if school_id is not None:
        visits = [v for v in visits if v["school_id"] == school_id]
    if visit_type_filter is not None:
        visits = [v for v in visits if v["visit_type"] == visit_type_filter]

    counts = {status: 0 for status in config.VISIT_CLINICAL_STATUSES}
    money = {
        "gross_charge_total_cents": 0,
        "no_charge_total_cents": 0,
        "patient_responsibility_total_cents": 0,
        "write_off_total_cents": 0,
        "payer_billed_total_cents": 0,
    }
    for visit in visits:
        counts[visit["clinical_status"]] += 1
        for key in money:
            money[key] += visit[key]

    referrals = [r for r in store.all_rows("referrals") if in_period(r)]
    if school_id is not None:
        referrals = [r for r in referrals if _student_is_scoped(r["student_id"], school_id)]
    referral_total = len(referrals)
    referral_closed = len([r for r in referrals if r["status"] == "CLOSED"])
    referral_lost = len([r for r in referrals if r["status"] == "LOST_TO_FOLLOW_UP"])

    students = _students_in_scope(school_id)
    grace_count = len(
        [s for s in students if s["immunization_compliance_status"] == "COMPLIANT"]
    )
    strict_count = len([s for s in students if calc.strict_compliant(s)])

    report = store.new_row(
        "reports",
        {
            "school_id": school_id,
            "visit_type_filter": visit_type_filter,
            "period_start_date": op.body["period_start_date"],
            "period_end_date": op.body["period_end_date"],
            "generated_at": clock.now_iso(),
            "total_visits": len(visits),
            "scheduled_visit_count": counts["SCHEDULED"],
            "in_progress_visit_count": counts["IN_PROGRESS"],
            "completed_visit_count": counts["COMPLETED"],
            "cancelled_visit_count": counts["CANCELLED"],
            "no_show_visit_count": counts["NO_SHOW"],
            "gross_charge_total_cents": money["gross_charge_total_cents"],
            "no_charge_total_cents": money["no_charge_total_cents"],
            "patient_responsibility_total_cents": money["patient_responsibility_total_cents"],
            "write_off_total_cents": money["write_off_total_cents"],
            "payer_billed_total_cents": money["payer_billed_total_cents"],
            "referral_total_count": referral_total,
            "referral_closed_count": referral_closed,
            "referral_lost_count": referral_lost,
            "referral_closure_rate_all": calc.closure_rate(referral_closed, referral_total),
            "referral_closure_rate_excluding_lost": calc.closure_rate(
                referral_closed, referral_total - referral_lost
            ),
            "grace_compliance_count": grace_count,
            "strict_compliance_count": strict_count,
        },
        with_version=False,
    )
    return envelope.created(serialize.dump(report))


@bp.get("/sbhc/reports/<id>")
def read_report(id):
    op = Op("GET /sbhc/reports/{id}", ["SbhcAdmin"])
    op.path_id("report", "reports", id, "ERR_RESOURCE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("report")))


@bp.get("/sbhc/reports")
def list_reports():
    op = Op("GET /sbhc/reports", ["SbhcAdmin"])
    op.paginated()
    op.run()
    rows = store.all_rows("reports")
    rows = helpers.filter_eq(rows, op.args, {"school_id": "school_id"})
    return helpers.list_response(rows, op)
