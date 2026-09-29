"""Reporting periods, facility reports, penalties and the period-close run."""
from flask import Blueprint, request

import calc
import db
import resolve
import response
import serialize
import services
import validate
from db import store
from errors import ApiError
from middleware import (FACILITY_ADMIN, PROGRAM_ADMIN, PROGRAM_AUDITOR, endpoint,
                        identity, user_id)

bp = Blueprint("compliance", __name__)

READ_ROLES = [PROGRAM_ADMIN, PROGRAM_AUDITOR, FACILITY_ADMIN]
RATE_FIELDS = ("cohort_screened_rate", "encounter_screened_rate",
               "followup_resolution_rate", "report_timeliness_rate")
SURVEILLANCE_WINDOW_DAYS = 30


# --- reporting periods ------------------------------------------------------
@bp.post("/reporting-periods")
@endpoint([PROGRAM_ADMIN])
def create_period():
    body = validate.body()
    period_start = validate.datetime_field(body, "period_start")
    period_end = validate.datetime_field(body, "period_end")
    due = validate.datetime_field(body, "submission_due_datetime")
    identity()
    if period_end <= period_start or due < period_end:
        raise ApiError("ERR_INVALID_WINDOW")
    for existing in db.sort_rows(list(store.periods.values())):
        if (period_start < existing["period_end"]
                and existing["period_start"] < period_end):
            raise ApiError("ERR_PERIOD_OVERLAP")
    row = db.base_row()
    row.update({
        "period_start": period_start,
        "period_end": period_end,
        "submission_due_datetime": due,
        "status": "OPEN",
        "closed_at": None,
        "facilities_assessed_count": 0,
        "episodes_escalated_count": 0,
        "episodes_lost_count": 0,
    })
    store.periods[row["id"]] = row
    return response.single(row, serialize.period, 201)


@bp.get("/reporting-periods/<period_id>")
@endpoint(READ_ROLES)
def get_period(period_id):
    row = resolve.one("period", period_id)
    identity()
    return response.single(row, serialize.period)


# --- facility reports -------------------------------------------------------
def _write_actuals(report, period):
    screened, refer = calc.report_actual_counts(report["facility_id"], period)
    report["actual_screened_count"] = screened
    report["actual_refer_count"] = refer
    if report["auto_generated"]:
        report["variance_case_count"] = refer
    else:
        report["variance_case_count"] = (
            abs(report["attested_screened_count"] - screened)
            + abs(report["attested_refer_count"] - refer))


@bp.post("/facility-reports")
@endpoint([FACILITY_ADMIN])
def create_report():
    body = validate.body()
    facility_id = validate.id_field(body, "facility_id")
    reporting_period_id = validate.id_field(body, "reporting_period_id")
    attested_screened = validate.int_field(body, "attested_screened_count",
                                           minimum=0, maximum=99999)
    attested_refer = validate.int_field(body, "attested_refer_count",
                                        minimum=0, maximum=99999)
    expected_version = validate.int_field(body, "expected_facility_version",
                                          minimum=1)
    supersedes_report_id = validate.id_field(body, "supersedes_report_id",
                                             required=False)
    linked = resolve.fks({
        "facility_id": facility_id,
        "supersedes_report_id": supersedes_report_id,
        "reporting_period_id": reporting_period_id,
    })
    facility = linked["facility_id"]
    period = linked["reporting_period_id"]
    incumbent = linked.get("supersedes_report_id")
    identity(facility_id=facility["id"])

    if facility["version"] != expected_version:
        raise ApiError("ERR_STALE_FACILITY_VERSION")
    if incumbent is not None and incumbent["status"] not in (
            "SUBMITTED", "RETURNED_FOR_CORRECTION"):
        raise ApiError("ERR_REPORT_INVALID_STATE")
    if incumbent is not None and (
            incumbent["facility_id"] != facility["id"]
            or incumbent["reporting_period_id"] != period["id"]):
        raise ApiError("ERR_LINKAGE_MISMATCH")
    if facility["facility_type"] == "EI_PROGRAM":
        raise ApiError("ERR_FACILITY_TYPE_MISMATCH")
    open_reports = [r for r in store.reports.values()
                    if r["facility_id"] == facility["id"]
                    and r["reporting_period_id"] == period["id"]
                    and r["status"] != "SUPERSEDED"]
    if open_reports and (incumbent is None
                         or incumbent["id"] not in [r["id"] for r in open_reports]):
        raise ApiError("ERR_DUPLICATE_REPORT")

    submitted_at = db.now()
    row = db.base_row()
    row.update({
        "facility_id": facility["id"],
        "reporting_period_id": period["id"],
        "supersedes_report_id": incumbent["id"] if incumbent else None,
        "attested_screened_count": attested_screened,
        "attested_refer_count": attested_refer,
        "actual_screened_count": 0,
        "actual_refer_count": 0,
        "variance_case_count": 0,
        "submitted_at": submitted_at,
        "submitted_late": submitted_at > period["submission_due_datetime"],
        "auto_generated": False,
        "status": "SUBMITTED",
        "accepted_by_user_id": None,
        "review_note": None,
        "assessed_penalty_points": 0,
        "waiver_reason": None,
    })
    _write_actuals(row, period)
    store.reports[row["id"]] = row
    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        db.touch(incumbent)
    db.touch(facility)
    return response.single(row, serialize.report, 201)


@bp.post("/facility-reports/<report_id>/review")
@endpoint([PROGRAM_AUDITOR])
def review_report(report_id):
    body = validate.body()
    decision = validate.enum_field(body, "decision", validate.REVIEW_DECISIONS)
    note = validate.string_field(body, "note", required=False)
    report = resolve.one("report", report_id)
    identity()
    period = store.periods.get(report["reporting_period_id"])
    if period is not None and period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_ALREADY_CLOSED")
    if decision == "ACCEPT":
        if report["status"] not in ("SUBMITTED", "RETURNED_FOR_CORRECTION"):
            raise ApiError("ERR_REPORT_INVALID_STATE")
        report["status"] = "ACCEPTED"
        report["accepted_by_user_id"] = user_id()
        report["review_note"] = note
        if period is not None:
            _write_actuals(report, period)
    else:
        if report["status"] != "SUBMITTED":
            raise ApiError("ERR_REPORT_INVALID_STATE")
        report["status"] = "RETURNED_FOR_CORRECTION"
        report["review_note"] = note
    db.touch(report)
    return response.single(report, serialize.report)


@bp.post("/facility-reports/<report_id>/waive-penalty")
@endpoint([PROGRAM_ADMIN])
def waive_penalty(report_id):
    body = validate.body()
    waiver_reason = validate.string_field(body, "waiver_reason", min_len=1)
    report = resolve.one("report", report_id)
    identity()
    period = store.periods.get(report["reporting_period_id"])
    if report["status"] != "ACCEPTED" or report["assessed_penalty_points"] <= 0:
        raise ApiError("ERR_REPORT_INVALID_STATE")
    if period is None or period["status"] != "CLOSED":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    if user_id() == report["accepted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # PENALTY_WAIVED rows drop out of the derived penalty balance.
    report["status"] = "PENALTY_WAIVED"
    report["waiver_reason"] = waiver_reason
    db.touch(report)
    facility = store.facilities.get(report["facility_id"])
    db.touch(facility)
    return response.single(report, serialize.report)


@bp.get("/facility-reports/<report_id>")
@endpoint(READ_ROLES)
def get_report(report_id):
    row = resolve.one("report", report_id)
    identity()
    return response.single(row, serialize.report)


@bp.get("/facility-reports")
@endpoint(READ_ROLES)
def list_reports():
    limit, offset = response.pagination()
    identity()
    rows = list(store.reports.values())
    for field in ("facility_id", "reporting_period_id", "supersedes_report_id",
                  "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    auto = validate.flag_query("auto_generated")
    if auto is not None:
        rows = [r for r in rows if r["auto_generated"] is auto]
    return response.listing(db.sort_rows(rows), serialize.report, limit, offset)


# --- the period-close checkpoint --------------------------------------------
def _mint_auto_report(facility, period):
    """A non-filing report of record, minted by the close run itself."""
    row = db.base_row()
    row.update({
        "facility_id": facility["id"],
        "reporting_period_id": period["id"],
        "supersedes_report_id": None,
        "attested_screened_count": None,
        "attested_refer_count": None,
        "actual_screened_count": 0,
        "actual_refer_count": 0,
        "variance_case_count": 0,
        "submitted_at": db.now(),
        "submitted_late": db.now() > period["submission_due_datetime"],
        "auto_generated": True,
        "status": "ACCEPTED",
        "accepted_by_user_id": None,
        "review_note": None,
        "assessed_penalty_points": 0,
        "waiver_reason": None,
    })
    _write_actuals(row, period)
    store.reports[row["id"]] = row
    return row


def _assess_facilities(period):
    """Step 1: assess every non-EI facility in ascending created_at order."""
    assessed = []
    degraded = []
    for facility in db.sort_rows(list(store.facilities.values())):
        if facility["facility_type"] not in calc.ASSESSABLE_FACILITY_TYPES:
            continue
        record = calc.report_of_record(facility["id"], period["id"])
        if record is None:
            record = _mint_auto_report(facility, period)
        elif record["status"] in ("SUBMITTED", "RETURNED_FOR_CORRECTION"):
            record["status"] = "ACCEPTED"
            _write_actuals(record, period)
            db.touch(record)
        # The carryover is the balance observed before this assessment writes.
        assessment = calc.penalty_assessment(facility, record)
        record["assessed_penalty_points"] = assessment["assessed_penalty_points"]
        db.touch(record)
        performance = calc.facility_performance(facility, period)
        facility["performance_score"] = performance["performance_score"]
        facility["encounter_basis_performance_score"] = \
            performance["encounter_basis_performance_score"]
        for field in RATE_FIELDS:
            facility[field] = performance[field]
        db.touch(facility)
        period["facilities_assessed_count"] += 1
        assessed.append(facility)
        if calc.facility_posture(facility) in ("PROBATION", "SUSPENDED"):
            degraded.append(facility)
    return assessed, degraded


def _escalation_cascade(period, degraded):
    """Step 2 (cascade C2): the state takes over the episodes of degraded facilities."""
    affected = []
    seen = set()
    for facility in degraded:
        for infant in db.sort_rows(calc.facility_infants(facility["id"])):
            escalated = False
            for episode in db.sort_rows(calc.infant_episodes(infant["id"])):
                if episode["status"] not in ("PENDING_SCHEDULING", "SCHEDULED"):
                    continue
                episode["escalation_flag"] = True
                episode["owner_scope"] = "STATE_PROGRAM"
                db.touch(episode)
                period["episodes_escalated_count"] += 1
                escalated = True
            if escalated and infant["id"] not in seen:
                seen.add(infant["id"])
                affected.append(infant)
    for infant in affected:
        band = services.recompute_risk(infant)
        if band != "CRITICAL":
            continue
        live = [t for t in calc.infant_tasks(infant["id"])
                if t["status"] in ("UNASSIGNED", "OPEN")]
        if live:
            continue
        services.mint_cascade_task(infant, "OUTREACH_CALL")
        services.recompute_risk(infant)


def _timeliness_sweep(period):
    """Step 3: overdue episodes, then the loss-to-follow-up rule."""
    for episode in db.sort_rows(list(store.episodes.values())):
        if episode["status"] != "PENDING_SCHEDULING":
            continue
        infant = store.infants.get(episode["infant_id"])
        if infant is None:
            continue
        age = calc.effective_age(infant, db.now())
        benchmark = episode["benchmark_days"]
        if age <= benchmark:
            continue
        if episode["timeliness_status"] != "OVERDUE":
            episode["timeliness_status"] = "OVERDUE"
            db.touch(episode)
        if (age > benchmark + calc.LATE_GRACE_DAYS
                and calc.attempt_count(episode) >= calc.ATTEMPT_CEILING):
            episode["status"] = "LOST_TO_FOLLOW_UP"
            episode["closure_reason"] = "LOST_TO_FOLLOW_UP"
            episode["closed_at"] = db.now()
            db.touch(episode)
            infant["screening_status"] = "LOST_TO_FOLLOW_UP"
            db.touch(infant)
            services.recompute_risk(infant)
            period["episodes_lost_count"] += 1


def _registry_sweep():
    """Step 4: age the surveillance registry forward."""
    now = db.now()
    for entry in db.sort_rows(list(store.risk_entries.values())):
        due = entry["surveillance_due_date"]
        target = None
        if entry["status"] == "ACTIVE":
            if now > due:
                target = "SURVEILLANCE_OVERDUE"
            elif now >= db.add_days(due, -SURVEILLANCE_WINDOW_DAYS):
                target = "SURVEILLANCE_DUE"
        elif entry["status"] == "SURVEILLANCE_DUE" and now > due:
            target = "SURVEILLANCE_OVERDUE"
        if target is not None:
            entry["status"] = target
            db.touch(entry)


@bp.post("/reporting-periods/<period_id>/close")
@endpoint([PROGRAM_ADMIN])
def close_period(period_id):
    validate.body()
    period = resolve.one("period", period_id)
    identity()
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_ALREADY_CLOSED")
    for other in store.periods.values():
        if (other["id"] != period["id"] and other["status"] == "OPEN"
                and other["period_end"] <= period["period_start"]):
            raise ApiError("ERR_EARLIER_PERIOD_OPEN")
    if db.now() < period["period_end"]:
        raise ApiError("ERR_PERIOD_NOT_ENDED")

    assessed, degraded = _assess_facilities(period)
    _escalation_cascade(period, degraded)
    _timeliness_sweep(period)
    _registry_sweep()

    period["status"] = "CLOSED"
    period["closed_at"] = db.now()
    db.touch(period)
    label = calc.period_label(period)
    for facility in assessed:
        facility["last_closed_period_label"] = label
        db.touch(facility)
    return response.single(period, serialize.period)
