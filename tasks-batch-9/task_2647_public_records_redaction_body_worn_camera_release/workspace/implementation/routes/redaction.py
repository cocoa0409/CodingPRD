"""Redaction production and quality review (PRD 3.6)."""
from flask import Blueprint

import calc
import services
import validate
from core import must_get, read_endpoint, write_endpoint
from db import fmt_dt, store
from errors import fail
from middleware import (
    ROLE_LEGAL_COUNSEL,
    ROLE_QUALITY_REVIEWER,
    ROLE_RECORDS_CLERK,
    ROLE_RECORDS_SUPERVISOR,
    ROLE_REDACTION_TECHNICIAN,
)
from reconcile import reconcile_all
from response import paginate

bp = Blueprint("redaction", __name__)


@bp.route("/records/responsive-records/<record_id>/redaction-tasks",
          methods=["POST"])
@write_endpoint([ROLE_REDACTION_TECHNICIAN, ROLE_RECORDS_SUPERVISOR], code=201)
def create_task(ctx, record_id):
    data = validate.body()
    target_type = validate.req_enum(data, "target_type", calc.TARGET_TYPES)
    # No bounds here: every range violation is reported as ERR_INVALID_CLIP_RANGE.
    clip_start_ms = validate.req_int(data, "clip_start_ms")
    clip_end_ms = validate.req_int(data, "clip_end_ms")
    technician_id = validate.req_str(data, "assigned_technician_id")
    claim_id = validate.opt_str(data, "exemption_claim_id")
    record = must_get("responsive_records", record_id,
                      "ERR_RESPONSIVE_RECORD_NOT_FOUND")
    technician = must_get("staff", technician_id, "ERR_STAFF_NOT_FOUND")
    claim = None
    if claim_id is not None:
        claim = must_get("exemption_claims", claim_id,
                         "ERR_EXEMPTION_CLAIM_NOT_FOUND")
    request = services.request_of_record(record)
    required_level, _ = calc.certification_requirement(target_type, claim)
    if technician["redaction_certification_level"] < required_level:
        fail("ERR_CERTIFICATION_INSUFFICIENT",
             "the technician must hold redaction certification level %d"
             % required_level)
    if record["release_posture"] == "BLOCKED":
        fail("ERR_RECORD_RELEASE_BLOCKED",
             "no work may be opened on a record withheld in full")
    if claim is not None and claim["responsive_record_id"] != record["id"]:
        fail("ERR_CLAIM_RECORD_MISMATCH",
             "the exemption claim belongs to a different responsive record")
    asset = calc.asset_of_record(record)
    duration_ms = asset["duration_ms"] if asset else 0
    if clip_start_ms < 0 or clip_end_ms <= clip_start_ms or clip_end_ms > duration_ms:
        fail("ERR_INVALID_CLIP_RANGE",
             "the clip interval must satisfy 0 <= start < end <= %d" % duration_ms)
    if calc.clip_overlaps(record["id"], target_type, clip_start_ms, clip_end_ms):
        fail("ERR_CLIP_OVERLAP",
             "a live task already covers part of this interval for %s" % target_type)
    if services.deposit_outstanding(request):
        fail("ERR_DEPOSIT_UNPAID",
             "the required deposit on the request is unpaid")
    task = store.insert("redaction_tasks", {
        "responsive_record_id": record["id"],
        "exemption_claim_id": claim["id"] if claim else None,
        "target_type": target_type,
        "clip_start_ms": clip_start_ms,
        "clip_end_ms": clip_end_ms,
        "assigned_technician_id": technician["id"],
        "qa_reviewer_id": None,
        "qa_window_start_at": None,
        "qa_window_end_at": None,
        "status": "DRAFT",
        "logged_labor_minutes": 0,
        "approved_labor_minutes": 0,
        "rework_count": 0,
        "defect_codes": [],
    })
    live = [row for row in calc.tasks_of_request(request["id"])
            if row["status"] in calc.LIVE_TASK_STATUSES]
    if len(live) == 1:
        services.advance_after_task_created(request)
    return task


@bp.route("/records/redaction-tasks/<task_id>/submit-qa", methods=["POST"])
@write_endpoint([ROLE_REDACTION_TECHNICIAN], code=200)
def submit_qa(ctx, task_id):
    data = validate.body()
    logged_labor_minutes = validate.req_int(data, "logged_labor_minutes", minimum=0)
    reviewer_id = validate.req_str(data, "qa_reviewer_id")
    window_start = validate.req_dt(data, "qa_window_start_at")
    window_end = validate.req_dt(data, "qa_window_end_at")
    task = must_get("redaction_tasks", task_id, "ERR_REDACTION_TASK_NOT_FOUND")
    reviewer = must_get("staff", reviewer_id, "ERR_STAFF_NOT_FOUND")
    if task["status"] not in ("DRAFT", "QA_REJECTED"):
        fail("ERR_TASK_STATE_INVALID",
             "a %s task cannot be submitted for review" % task["status"])
    if ctx.user_id != task["assigned_technician_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "only the assigned technician may submit this work")
    if reviewer["id"] == task["assigned_technician_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "a technician may not nominate themselves as reviewer")
    claim = store.get("exemption_claims", task["exemption_claim_id"]) \
        if task["exemption_claim_id"] else None
    _, reviewer_level = calc.certification_requirement(task["target_type"], claim)
    if reviewer["redaction_certification_level"] < reviewer_level:
        fail("ERR_CERTIFICATION_INSUFFICIENT",
             "the reviewer must hold redaction certification level %d"
             % reviewer_level)
    if window_start >= window_end:
        fail("ERR_INVALID_TIME_RANGE",
             "qa_window_start_at must fall strictly before qa_window_end_at")
    if calc.qa_window_conflicts(reviewer["id"], window_start, window_end,
                                exclude_task_id=task["id"]):
        fail("ERR_QA_WINDOW_CONFLICT",
             "the reviewer already holds a booking within the buffered window")
    if calc.qa_pending_count(reviewer["id"], exclude_task_id=task["id"]) >= \
            calc.MAX_CONCURRENT_QA_PER_REVIEWER:
        fail("ERR_QA_LOAD_EXCEEDED",
             "a reviewer may hold at most %d pending reviews"
             % calc.MAX_CONCURRENT_QA_PER_REVIEWER)
    if task["status"] == "QA_REJECTED":
        task["rework_count"] += 1
    task["status"] = "QA_PENDING"
    task["logged_labor_minutes"] = logged_labor_minutes
    task["qa_reviewer_id"] = reviewer["id"]
    task["qa_window_start_at"] = fmt_dt(window_start)
    task["qa_window_end_at"] = fmt_dt(window_end)
    return task


@bp.route("/records/redaction-tasks/<task_id>/qa-outcome", methods=["POST"])
@write_endpoint([ROLE_QUALITY_REVIEWER], code=200)
def qa_outcome(ctx, task_id):
    data = validate.body()
    outcome = validate.req_enum(data, "outcome", calc.QA_OUTCOMES)
    defect_codes = validate.opt_str_list(data, "defect_codes")
    task = must_get("redaction_tasks", task_id, "ERR_REDACTION_TASK_NOT_FOUND")
    if task["status"] != "QA_PENDING":
        fail("ERR_TASK_STATE_INVALID",
             "only a QA_PENDING task carries a verdict (currently %s)"
             % task["status"])
    if ctx.user_id == task["assigned_technician_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the technician who performed the work may not review it")
    if ctx.user_id != task["qa_reviewer_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "only the booked reviewer may record this verdict")
    claim = store.get("exemption_claims", task["exemption_claim_id"]) \
        if task["exemption_claim_id"] else None
    if outcome == "PASS" and claim is not None and claim["status"] == "ASSERTED":
        fail("ERR_UNADJUDICATED_CLAIM",
             "the exemption the task implements has not been adjudicated")
    if outcome == "PASS":
        task["status"] = "APPROVED"
        task["approved_labor_minutes"] = task["logged_labor_minutes"]
        task["defect_codes"] = []
    else:
        task["status"] = "QA_REJECTED"
        task["approved_labor_minutes"] = 0
        task["defect_codes"] = list(defect_codes)
    record = store.get("responsive_records", task["responsive_record_id"])
    request = services.request_of_record(record) if record else None
    if outcome == "PASS" and request is not None:
        reconcile_all()
        services.advance_after_tasks_settled(request)
    return task


# -- reads -----------------------------------------------------------------
@bp.route("/records/redaction-tasks/<task_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_REDACTION_TECHNICIAN, ROLE_QUALITY_REVIEWER,
                ROLE_LEGAL_COUNSEL])
def get_task(ctx, task_id):
    return must_get("redaction_tasks", task_id, "ERR_REDACTION_TASK_NOT_FOUND")


@bp.route("/records/redaction-tasks", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_REDACTION_TECHNICIAN, ROLE_QUALITY_REVIEWER,
                ROLE_LEGAL_COUNSEL])
def list_tasks(ctx):
    limit, offset = validate.pagination()
    filters = {
        "responsive_record_id": validate.query_str("responsive_record_id"),
        "exemption_claim_id": validate.query_str("exemption_claim_id"),
        "assigned_technician_id": validate.query_str("assigned_technician_id"),
        "qa_reviewer_id": validate.query_str("qa_reviewer_id"),
        "status": validate.query_enum("status", calc.TASK_STATUSES),
    }
    rows = store.all("redaction_tasks")
    for field, value in filters.items():
        if value is not None:
            rows = [row for row in rows if row[field] == value]
    return paginate(rows, limit, offset)
