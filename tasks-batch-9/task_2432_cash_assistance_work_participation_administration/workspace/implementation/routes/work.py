"""Work assignments, participation reporting and verification (PRD 3.5, 3.6)."""

from flask import Blueprint

import guards
from calc import (ACTIVITY_CATEGORIES, CORE_CATEGORIES, credited_hours)
from domain import (case_month_participated, hold_requested_auths, lookup,
                    month_overlaps_assignment, recompute_assignment_hours,
                    recompute_supportive_fy, rows_where, scheduled_capacity_ok,
                    void_auths_of_assignment)
from errors import fail
from guards import Fields, raw_body, require
from respond import created, filter_value, listing, ok, pagination
from store import clock_fiscal_year, db, new_record, touch

bp = Blueprint("work", __name__)

TERMINATION_REASONS = ("COMPLETED_ACTIVITY", "NONCOMPLIANCE", "CASE_CLOSED",
                       "PLAN_CHANGE")
VERIFICATION_SOURCES = ("EMPLOYER_ATTESTATION", "TIMESHEET", "THIRD_PARTY",
                        "SELF_REPORT")
ACTIVATION_COMPLIANCE = ("ASSIGNED", "CONCILIATION_PENDING", "CURE_PENDING")


def _case(case_id):
    return lookup("cases", case_id, "ERR_CASE_NOT_FOUND")


def _assignment(assignment_id):
    return lookup("work_assignments", assignment_id,
                  "ERR_WORK_ASSIGNMENT_NOT_FOUND")


def _report(report_id):
    return lookup("participation_reports", report_id,
                  "ERR_PARTICIPATION_REPORT_NOT_FOUND")


@bp.post("/cases/<case_id>/work-assignments")
def assign_activity(case_id):
    require(guards.SPECIALIST)
    _case(case_id)
    fields = Fields(raw_body())
    fields.enum("activity_category", ACTIVITY_CATEGORIES)
    fields.integer("scheduled_weekly_hours", minimum=1, maximum=60)
    fields.date("start_date")
    fields.date("end_date")
    if not scheduled_capacity_ok(case_id, fields["start_date"], fields["end_date"],
                                 fields["scheduled_weekly_hours"]):
        fail("ERR_SCHEDULED_HOURS_CAPACITY_EXCEEDED",
             "Scheduled weekly hours across overlapping assignments exceed 60.")

    assignment = new_record({
        "case_id": case_id,
        "activity_category": fields["activity_category"],
        "is_core": fields["activity_category"] in CORE_CATEGORIES,
        "scheduled_weekly_hours": fields["scheduled_weekly_hours"],
        "start_date": fields["start_date"],
        "end_date": fields["end_date"],
        "status": "PROPOSED",
        "termination_reason": "NONE",
        "cumulative_verified_hours": 0,
        "compliance_flag": "NONE",
    })
    db.work_assignments[assignment["id"]] = assignment
    return created(assignment)


@bp.get("/cases/<case_id>/work-assignments")
def list_assignments(case_id):
    require()
    _case(case_id)
    limit, offset = pagination()
    rows = rows_where("work_assignments", case_id=case_id)
    for name in ("status", "activity_category"):
        value = filter_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return listing(rows, limit, offset)


@bp.get("/work-assignments/<assignment_id>")
def read_assignment(assignment_id):
    require()
    return ok(_assignment(assignment_id))


@bp.post("/work-assignments/<assignment_id>/activate")
def activate_assignment(assignment_id):
    require(guards.SPECIALIST)
    assignment = _assignment(assignment_id)
    if assignment["status"] != "PROPOSED":
        fail("ERR_INVALID_ASSIGNMENT_STATE",
             "Only a PROPOSED assignment may be activated.")
    case = db.cases[assignment["case_id"]]
    if case["benefit_status"] != "ACTIVE":
        fail("ERR_CASE_NOT_ACTIVE", "The case must be ACTIVE to activate work.")
    if case["compliance_status"] not in ACTIVATION_COMPLIANCE:
        fail("ERR_INVALID_CASE_STATE",
             "The case compliance posture does not permit activation.")
    if not scheduled_capacity_ok(case["id"], assignment["start_date"],
                                 assignment["end_date"],
                                 assignment["scheduled_weekly_hours"],
                                 exclude_id=assignment["id"]):
        fail("ERR_SCHEDULED_HOURS_CAPACITY_EXCEEDED",
             "Scheduled weekly hours across overlapping assignments exceed 60.")
    assignment["status"] = "ACTIVE"
    touch(assignment)
    return ok(assignment)


@bp.post("/work-assignments/<assignment_id>/terminate")
def terminate_assignment(assignment_id):
    require(guards.SPECIALIST)
    assignment = _assignment(assignment_id)
    fields = Fields(raw_body())
    fields.enum("termination_reason", TERMINATION_REASONS)
    if assignment["status"] not in ("PROPOSED", "ACTIVE"):
        fail("ERR_INVALID_ASSIGNMENT_STATE",
             "This assignment may no longer be terminated.")
    reason = fields["termination_reason"]
    assignment["termination_reason"] = reason
    if reason == "COMPLETED_ACTIVITY":
        assignment["status"] = "COMPLETED"
        touch(assignment)
    else:
        assignment["status"] = "TERMINATED"
        touch(assignment)
        case = db.cases[assignment["case_id"]]
        fiscal_year = clock_fiscal_year()
        void_auths_of_assignment(assignment, fiscal_year)
        recompute_supportive_fy(case, fiscal_year)
    return ok(assignment)


@bp.post("/work-assignments/<assignment_id>/participation-reports")
def file_report(assignment_id):
    require(guards.CASEWORKER, guards.SPECIALIST)
    assignment = _assignment(assignment_id)
    fields = Fields(raw_body())
    fields.month("report_month")
    fields.integer("reported_hours", minimum=0, maximum=744)
    fields.enum("verification_source", VERIFICATION_SOURCES)
    month = fields["report_month"]
    case = db.cases[assignment["case_id"]]
    if case["benefit_status"] != "ACTIVE":
        fail("ERR_CASE_NOT_ACTIVE",
             "The case must be ACTIVE to file participation hours.")
    for existing in rows_where("participation_reports",
                               work_assignment_id=assignment_id):
        if existing["report_month"] == month and \
                existing["status"] in ("SUBMITTED", "VERIFIED"):
            fail("ERR_DUPLICATE_REPORT_MONTH",
                 "A report for this assignment and month already exists.")
    if not month_overlaps_assignment(month, assignment):
        fail("ERR_REPORT_MONTH_OUTSIDE_ASSIGNMENT",
             "The report month does not intersect the assignment period.")

    report = new_record({
        "work_assignment_id": assignment_id,
        "report_month": month,
        "reported_hours": fields["reported_hours"],
        "verification_source": fields["verification_source"],
        "status": "SUBMITTED",
        "verified_hours": None,
        "core_hours_credited": 0,
        "non_core_hours_credited": 0,
        "rejection_reason": None,
    })
    db.participation_reports[report["id"]] = report
    return created(report)


@bp.get("/work-assignments/<assignment_id>/participation-reports")
def list_reports(assignment_id):
    require()
    _assignment(assignment_id)
    limit, offset = pagination()
    rows = rows_where("participation_reports", work_assignment_id=assignment_id)
    for name in ("report_month", "status"):
        value = filter_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return listing(rows, limit, offset)


@bp.post("/participation-reports/<report_id>/verify")
def verify_report(report_id):
    require(guards.SPECIALIST)
    report = _report(report_id)
    fields = Fields(raw_body())
    fields.integer("verified_hours")
    accepted = fields["verified_hours"]
    if accepted < 0 or accepted > report["reported_hours"]:
        fail("ERR_INVALID_REQUEST",
             "verified_hours must be between 0 and the reported hours.")
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_REPORT_STATE", "Only a SUBMITTED report may be verified.")
    assignment = db.work_assignments[report["work_assignment_id"]]
    if assignment["status"] not in ("ACTIVE", "COMPLETED"):
        fail("ERR_INVALID_ASSIGNMENT_STATE",
             "Hours may only be verified against an ACTIVE or COMPLETED assignment.")

    credited = credited_hours(accepted, report["verification_source"])
    report["verified_hours"] = credited
    if assignment["is_core"]:
        report["core_hours_credited"] = credited
        report["non_core_hours_credited"] = 0
    else:
        report["core_hours_credited"] = 0
        report["non_core_hours_credited"] = credited
    report["status"] = "VERIFIED"
    touch(report)

    recompute_assignment_hours(assignment)
    case = db.cases[assignment["case_id"]]
    participated = case_month_participated(case, report["report_month"])
    flag = "NONE" if participated else "SHORTFALL"
    if assignment["compliance_flag"] != flag:
        assignment["compliance_flag"] = flag
        touch(assignment)
    if flag == "SHORTFALL" and case["compliance_status"] == "ASSIGNED":
        episode = new_record({
            "case_id": case["id"],
            "prior_episode_id": None,
            "allegation_reason": "HOURS_SHORTFALL",
            "origin": "SYSTEM_SHORTFALL",
            "status": "ALLEGED",
            "conciliation_start_date": None,
            "conciliation_deadline_date": None,
            "sanction_level": 0,
            "sanction_pct": 0.00,
            "sanction_imposed_month": None,
            "good_cause_reason": "NONE",
            "cure_plan_note": None,
        })
        db.compliance_episodes[episode["id"]] = episode
        case["compliance_status"] = "CONCILIATION_PENDING"
        touch(case)
        hold_requested_auths(case)
    return ok(report)


@bp.post("/participation-reports/<report_id>/reject")
def reject_report(report_id):
    require(guards.SPECIALIST)
    report = _report(report_id)
    fields = Fields(raw_body())
    fields.text("rejection_reason")
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_REPORT_STATE", "Only a SUBMITTED report may be rejected.")
    report["status"] = "REJECTED"
    report["rejection_reason"] = fields["rejection_reason"]
    report["verified_hours"] = 0
    report["core_hours_credited"] = 0
    report["non_core_hours_credited"] = 0
    touch(report)
    return ok(report)
