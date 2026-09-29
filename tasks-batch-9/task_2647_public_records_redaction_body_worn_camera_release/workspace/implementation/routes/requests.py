"""Intake, scope clarification and responsive-record attachment (PRD 3.3, 3.4)."""
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
    ROLE_REQUESTER,
)
from response import paginate

bp = Blueprint("requests", __name__)


def owned_by_requester(ctx, request):
    """Ladder step 6: a filer may only reach their own request."""
    if ctx.role == ROLE_REQUESTER and request["requester_id"] != ctx.user_id:
        fail("ERR_REQUESTER_MISMATCH", "the request belongs to another filer")


@bp.route("/records/requests", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR], code=201)
def create_request(ctx):
    data = validate.body()
    requester_id = validate.req_str(data, "requester_id")
    received_at = validate.req_dt(data, "received_at")
    subject_incident_number = validate.req_str(data, "subject_incident_number")
    date_from = validate.req_dt(data, "requested_date_from")
    date_to = validate.req_dt(data, "requested_date_to")
    scope_narrative = validate.req_str(data, "scope_narrative")
    extension_days = validate.opt_int(data, "extension_days_granted", default=0,
                                      minimum=0, maximum=calc.MAX_EXTENSION_DAYS)
    requester = must_get("requesters", requester_id, "ERR_REQUESTER_NOT_FOUND")
    if requester["requester_type"] == "COMMERCIAL":
        open_count = 0
        for row in store.all("requests"):
            if row["requester_id"] != requester["id"]:
                continue
            if row["processing_status"] not in calc.OPEN_PROCESSING_EXCLUDED:
                open_count += 1
        if open_count >= calc.COMMERCIAL_OPEN_REQUEST_LIMIT:
            fail("ERR_OPEN_REQUEST_LIMIT",
                 "a commercial filer may hold at most %d open requests"
                 % calc.COMMERCIAL_OPEN_REQUEST_LIMIT)
    if date_from > date_to:
        fail("ERR_INVALID_TIME_RANGE",
             "requested_date_from must not fall after requested_date_to")
    request = store.insert("requests", {
        "requester_id": requester["id"],
        "received_at": fmt_dt(received_at),
        "subject_incident_number": subject_incident_number,
        "requested_date_from": fmt_dt(date_from),
        "requested_date_to": fmt_dt(date_to),
        "scope_narrative": scope_narrative,
        "scope_clarification_count": 0,
        "extension_days_granted": extension_days,
        "processing_status": "INTAKE",
        "fee_status": "NOT_ASSESSED",
        "is_critical_incident": False,
        "statutory_deadline_at": None,
        "tolled_days": 0,
        "deposit_due_at": None,
        "estimated_total_cents": 0,
        "deposit_required_cents": 0,
        "invoiced_total_cents": 0,
        "deposit_paid_cents": 0,
        "fee_recognized_cents": 0,
        "deposit_balance_cents": 0,
        "waiver_credit_total_cents": 0,
        "billable_labor_minutes": 0,
        "responsive_record_count": 0,
        "unadjudicated_claim_count": 0,
        "open_notification_count": 0,
    })
    services.restrike_deadline(request)
    return request


@bp.route("/records/requests/<request_id>/scope-clarification", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR], code=200)
def scope_clarification(ctx, request_id):
    data = validate.body()
    scope_narrative = validate.req_str(data, "scope_narrative")
    date_from = validate.req_dt(data, "requested_date_from")
    date_to = validate.req_dt(data, "requested_date_to")
    expected_version = validate.req_int(data, "expected_request_version")
    supplied_extension = validate.opt_int(data, "extension_days_granted",
                                         default=None, minimum=0,
                                         maximum=calc.MAX_EXTENSION_DAYS)
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    if expected_version != request["version"]:
        fail("ERR_STALE_REQUEST_VERSION",
             "expected_request_version %s does not match %s"
             % (expected_version, request["version"]))
    if request["processing_status"] not in ("INTAKE", "SCOPING"):
        fail("ERR_REQUEST_STATE_INVALID",
             "clarification is a scoping-phase act; the request is %s"
             % request["processing_status"])
    if request["scope_clarification_count"] >= calc.MAX_SCOPE_CLARIFICATIONS:
        fail("ERR_SCOPE_CLARIFICATION_LIMIT",
             "at most %d clarifications are accepted" % calc.MAX_SCOPE_CLARIFICATIONS)
    if date_from > date_to:
        fail("ERR_INVALID_TIME_RANGE",
             "requested_date_from must not fall after requested_date_to")
    request["scope_narrative"] = scope_narrative
    request["requested_date_from"] = fmt_dt(date_from)
    request["requested_date_to"] = fmt_dt(date_to)
    if supplied_extension is not None:
        request["extension_days_granted"] = min(supplied_extension,
                                                calc.MAX_EXTENSION_DAYS)
    request["scope_clarification_count"] += 1
    request["processing_status"] = "SCOPING"
    services.restrike_deadline(request)
    services.stale_active_estimates(request["id"])
    ctx.touch("requests", request["id"])
    return request


@bp.route("/records/requests/<request_id>/responsive-records", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR], code=201)
def create_responsive_record(ctx, request_id):
    data = validate.body()
    video_asset_id = validate.req_str(data, "video_asset_id")
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    asset = must_get("video_assets", video_asset_id, "ERR_VIDEO_ASSET_NOT_FOUND")
    if request["processing_status"] == "CLOSED":
        fail("ERR_REQUEST_STATE_INVALID",
             "a CLOSED request accepts no further recordings")
    if asset["disposition_state"] == "PURGED":
        fail("ERR_ASSET_STATE_INVALID",
             "a destroyed recording can never be attached to a request")
    for existing in calc.records_of_request(request["id"]):
        if existing["video_asset_id"] == asset["id"]:
            fail("ERR_DUPLICATE_RESPONSIVE_RECORD",
                 "the recording is already attached to this request")
    baseline = calc.baseline_obscuration_minutes(asset)
    return store.insert("responsive_records", {
        "request_id": request["id"],
        "video_asset_id": asset["id"],
        "inclusion_status": "CANDIDATE",
        "release_posture": "OPEN",
        "estimated_review_minutes": calc.record_review_minutes(asset),
        "presumptive_burden_minutes": baseline,
        "adjudicated_burden_minutes": baseline,
        "approved_labor_minutes": 0,
        "unadjudicated_claim_count": 0,
        "redacted_segment_ms": 0,
        "released_at": None,
    })


# -- reads -----------------------------------------------------------------
@bp.route("/records/requests/<request_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_REDACTION_TECHNICIAN, ROLE_QUALITY_REVIEWER,
                ROLE_LEGAL_COUNSEL, ROLE_REQUESTER])
def get_request(ctx, request_id):
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    owned_by_requester(ctx, request)
    return request


@bp.route("/records/requests", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_LEGAL_COUNSEL, ROLE_REQUESTER])
def list_requests(ctx):
    limit, offset = validate.pagination()
    requester_id = validate.query_str("requester_id")
    processing_status = validate.query_enum("processing_status",
                                            calc.PROCESSING_STATUSES)
    fee_status = validate.query_enum("fee_status", calc.FEE_STATUSES)
    if ctx.role == ROLE_REQUESTER:
        if requester_id is not None and requester_id != ctx.user_id:
            fail("ERR_REQUESTER_MISMATCH", "a filer may only list their own requests")
        requester_id = ctx.user_id
    rows = store.all("requests")
    if requester_id is not None:
        rows = [row for row in rows if row["requester_id"] == requester_id]
    if processing_status is not None:
        rows = [row for row in rows if row["processing_status"] == processing_status]
    if fee_status is not None:
        rows = [row for row in rows if row["fee_status"] == fee_status]
    return paginate(rows, limit, offset)


@bp.route("/records/responsive-records/<record_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_REDACTION_TECHNICIAN, ROLE_QUALITY_REVIEWER,
                ROLE_LEGAL_COUNSEL])
def get_responsive_record(ctx, record_id):
    return must_get("responsive_records", record_id,
                    "ERR_RESPONSIVE_RECORD_NOT_FOUND")


@bp.route("/records/responsive-records", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_REDACTION_TECHNICIAN, ROLE_QUALITY_REVIEWER,
                ROLE_LEGAL_COUNSEL])
def list_responsive_records(ctx):
    limit, offset = validate.pagination()
    request_id = validate.query_str("request_id")
    video_asset_id = validate.query_str("video_asset_id")
    inclusion_status = validate.query_enum("inclusion_status", calc.INCLUSION_STATUSES)
    release_posture = validate.query_enum("release_posture", calc.RELEASE_POSTURES)
    rows = store.all("responsive_records")
    if request_id is not None:
        rows = [row for row in rows if row["request_id"] == request_id]
    if video_asset_id is not None:
        rows = [row for row in rows if row["video_asset_id"] == video_asset_id]
    if inclusion_status is not None:
        rows = [row for row in rows if row["inclusion_status"] == inclusion_status]
    if release_posture is not None:
        rows = [row for row in rows if row["release_posture"] == release_posture]
    return paginate(rows, limit, offset)
