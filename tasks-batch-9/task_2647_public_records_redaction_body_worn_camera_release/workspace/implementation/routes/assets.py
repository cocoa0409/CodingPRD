"""Recordings, depicted individuals, retention and litigation holds (PRD 3.2)."""
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
from response import paginate

bp = Blueprint("assets", __name__)


@bp.route("/records/video-assets", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR], code=201)
def create_video_asset(ctx):
    data = validate.body()
    incident_number = validate.req_str(data, "incident_number")
    device_serial = validate.req_str(data, "device_serial")
    officer_badge = validate.req_str(data, "officer_badge")
    recorded_start_at = validate.req_dt(data, "recorded_start_at")
    duration_ms = validate.req_int(data, "duration_ms", minimum=1)
    classification = validate.req_enum(data, "classification", calc.CLASSIFICATIONS)
    retention_category = validate.req_enum(data, "retention_category",
                                          calc.RETENTION_CATEGORIES)
    scheduled_purge_at = validate.req_dt(data, "scheduled_purge_at")
    critical = validate.opt_bool(data, "is_critical_incident", default=False)
    # disposition_state / retention_locked / suspended_by_hold_id are settled by
    # reconciliation, which applies the litigation-hold cascade of PRD 3.2.
    return store.insert("video_assets", {
        "incident_number": incident_number,
        "device_serial": device_serial,
        "officer_badge": officer_badge,
        "recorded_start_at": fmt_dt(recorded_start_at),
        "duration_ms": duration_ms,
        "is_critical_incident": critical,
        "classification": classification,
        "retention_category": retention_category,
        "scheduled_purge_at": fmt_dt(scheduled_purge_at),
        "disposition_state": "SCHEDULED",
        "suspended_by_hold_id": None,
        "retention_locked": False,
        "depicted_individual_count": 0,
    })


@bp.route("/records/video-assets/<asset_id>/depicted-individuals", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_LEGAL_COUNSEL], code=201)
def create_depicted_individual(ctx, asset_id):
    data = validate.body()
    display_label = validate.req_str(data, "display_label")
    relationship = validate.req_enum(data, "relationship", calc.RELATIONSHIPS)
    asset = must_get("video_assets", asset_id, "ERR_VIDEO_ASSET_NOT_FOUND")
    for existing in calc.individuals_of_asset(asset["id"]):
        if existing["display_label"] == display_label:
            fail("ERR_DUPLICATE_DEPICTED_LABEL",
                 "display_label %r already used on this recording" % display_label)
    required = relationship in calc.NOTIFICATION_REQUIRED_RELATIONSHIPS
    return store.insert("depicted_individuals", {
        "video_asset_id": asset["id"],
        "display_label": display_label,
        "relationship": relationship,
        "notification_required": required,
        "notification_status": "PENDING" if required else "NOT_REQUIRED",
        "notice_method": None,
        "notified_at": None,
        "objection_deadline_at": None,
        "objection_basis": None,
    })


@bp.route("/records/video-assets/<asset_id>/purge", methods=["POST"])
@write_endpoint([ROLE_RECORDS_SUPERVISOR], code=200)
def purge_video_asset(ctx, asset_id):
    data = validate.body()
    validate.opt_str(data, "destruction_note")
    asset = must_get("video_assets", asset_id, "ERR_VIDEO_ASSET_NOT_FOUND")
    if asset["disposition_state"] != "SCHEDULED":
        fail("ERR_ASSET_STATE_INVALID",
             "a recording at %s cannot be destroyed" % asset["disposition_state"])
    if asset["retention_locked"]:
        fail("ERR_RETENTION_HOLD_ACTIVE", "the recording is retention locked")
    from db import parse_dt
    due_at = parse_dt(asset["scheduled_purge_at"])
    if due_at is None or store.now() < due_at:
        fail("ERR_PURGE_NOT_DUE", "scheduled_purge_at has not been reached")
    asset["disposition_state"] = "PURGED"
    return asset


@bp.route("/records/litigation-holds", methods=["POST"])
@write_endpoint([ROLE_LEGAL_COUNSEL], code=201)
def create_litigation_hold(ctx):
    data = validate.body()
    matter_number = validate.req_str(data, "matter_number")
    scope_incident_number = validate.req_str(data, "scope_incident_number")
    hold_type = validate.req_enum(data, "hold_type", calc.HOLD_TYPES)
    for existing in store.all("litigation_holds"):
        if existing["matter_number"] == matter_number:
            fail("ERR_DUPLICATE_MATTER_NUMBER",
                 "matter_number %r already exists" % matter_number)
    return store.insert("litigation_holds", {
        "matter_number": matter_number,
        "scope_incident_number": scope_incident_number,
        "hold_type": hold_type,
        "status": "ACTIVE",
        "placed_at": store.now_str(),
        "released_at": None,
        "suspended_asset_count": 0,
    })


@bp.route("/records/litigation-holds/<hold_id>/release", methods=["POST"])
@write_endpoint([ROLE_LEGAL_COUNSEL], code=200)
def release_litigation_hold(ctx, hold_id):
    data = validate.body()
    validate.opt_str(data, "release_note")
    hold = must_get("litigation_holds", hold_id, "ERR_LITIGATION_HOLD_NOT_FOUND")
    if hold["status"] != "ACTIVE":
        fail("ERR_HOLD_STATE_INVALID", "the hold is already RELEASED")
    hold["status"] = "RELEASED"
    hold["released_at"] = store.now_str()
    hold["suspended_asset_count"] = 0
    return hold


# -- reads -----------------------------------------------------------------
@bp.route("/records/video-assets/<asset_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_REDACTION_TECHNICIAN, ROLE_QUALITY_REVIEWER,
                ROLE_LEGAL_COUNSEL])
def get_video_asset(ctx, asset_id):
    return must_get("video_assets", asset_id, "ERR_VIDEO_ASSET_NOT_FOUND")


@bp.route("/records/video-assets", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL])
def list_video_assets(ctx):
    limit, offset = validate.pagination()
    incident_number = validate.query_str("incident_number")
    suspended_by_hold_id = validate.query_str("suspended_by_hold_id")
    disposition_state = validate.query_enum("disposition_state",
                                            calc.DISPOSITION_STATES)
    rows = store.all("video_assets")
    if incident_number is not None:
        rows = [row for row in rows if row["incident_number"] == incident_number]
    if suspended_by_hold_id is not None:
        rows = [row for row in rows
                if row["suspended_by_hold_id"] == suspended_by_hold_id]
    if disposition_state is not None:
        rows = [row for row in rows if row["disposition_state"] == disposition_state]
    return paginate(rows, limit, offset)


@bp.route("/records/video-assets/<asset_id>/depicted-individuals", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL])
def list_depicted_individuals(ctx, asset_id):
    limit, offset = validate.pagination()
    notification_status = validate.query_enum("notification_status",
                                              calc.NOTIFICATION_STATUSES)
    asset = must_get("video_assets", asset_id, "ERR_VIDEO_ASSET_NOT_FOUND")
    rows = calc.individuals_of_asset(asset["id"])
    if notification_status is not None:
        rows = [row for row in rows
                if row["notification_status"] == notification_status]
    return paginate(rows, limit, offset)


@bp.route("/records/depicted-individuals/<individual_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL])
def get_depicted_individual(ctx, individual_id):
    return must_get("depicted_individuals", individual_id,
                    "ERR_DEPICTED_INDIVIDUAL_NOT_FOUND")


@bp.route("/records/litigation-holds/<hold_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL])
def get_litigation_hold(ctx, hold_id):
    return must_get("litigation_holds", hold_id, "ERR_LITIGATION_HOLD_NOT_FOUND")
