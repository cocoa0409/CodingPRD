"""DistributionRecord routes: send, acknowledge."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, PROJECT_ENGINEER, SUBCONTRACTOR_REP, require_roles
from db import store
from errors import (
    distribution_not_found,
    distribution_not_queued,
    distribution_not_sent,
    project_not_found,
    submittal_not_found,
    wrong_subcontractor,
)
from respond import success
from serialize import ser_distribution
from services import require_active
from store_ops import (
    json_body,
    paginate,
    sorted_by_creation,
    touch,
)

bp = Blueprint("distribution_records", __name__)


def get_record_or_404(record_id):
    r = store.distribution_records.get(record_id)
    if r is None:
        raise distribution_not_found()
    return r


@bp.route("/v1/projects/<projectId>/distribution-records", methods=["GET"])
def list_project_records(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [d for d in store.distribution_records.values() if d["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_distribution(d) for d in page], response_type="array", pagination=pagination)


@bp.route("/v1/distribution-records", methods=["GET"])
def list_records():
    require_roles(ALL_ROLES)
    items = list(store.distribution_records.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [d for d in items if d["project_id"] == project_id]
    subcontractor_id = request.args.get("subcontractor_id")
    if subcontractor_id:
        items = [d for d in items if d["subcontractor_id"] == subcontractor_id]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    source_type = request.args.get("source_type")
    if source_type:
        items = [d for d in items if d["source_type"] == source_type]
    source_id = request.args.get("source_id")
    if source_id:
        items = [d for d in items if d["source_id"] == source_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_distribution(d) for d in page], response_type="array", pagination=pagination)


@bp.route("/v1/distribution-records/<recordId>", methods=["GET"])
def get_record(recordId):
    require_roles(ALL_ROLES)
    rec = get_record_or_404(recordId)
    return success(ser_distribution(rec))


@bp.route("/v1/distribution-records/<recordId>/send", methods=["POST"])
def send_record(recordId):
    require_roles([PROJECT_ENGINEER])
    rec = get_record_or_404(recordId)
    project = store.projects.get(rec["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rec["status"] != "QUEUED":
        raise distribution_not_queued()
    sent = calc.clock_date()
    rec["sent_date"] = sent
    rec["ack_due_date"] = calc.add_business_days(sent, project["ack_required_days"], calc.holidays_set(project))
    rec["status"] = "SENT"
    touch(rec)
    return success(ser_distribution(rec))


@bp.route("/v1/distribution-records/<recordId>/acknowledge", methods=["POST"])
def acknowledge_record(recordId):
    uid, role = require_roles([SUBCONTRACTOR_REP])
    rec = get_record_or_404(recordId)
    project = store.projects.get(rec["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rec["status"] != "SENT":
        raise distribution_not_sent()
    if uid != rec["subcontractor_id"]:
        raise wrong_subcontractor()
    rec["acknowledged_date"] = calc.clock_date()
    rec["status"] = "ACKNOWLEDGED"
    touch(rec)
    # Submittal RELEASED -> DISTRIBUTED when all sibling records are ACKNOWLEDGED
    if rec["source_type"] == "SUBMITTAL":
        siblings = [
            d for d in store.distribution_records.values()
            if d["source_type"] == "SUBMITTAL" and d["source_id"] == rec["source_id"]
        ]
        if all(d["status"] == "ACKNOWLEDGED" for d in siblings):
            sub = store.submittals.get(rec["source_id"])
            if sub is not None and sub["review_status"] == "RELEASED":
                sub["review_status"] = "DISTRIBUTED"
                touch(sub)
    return success(ser_distribution(rec))
