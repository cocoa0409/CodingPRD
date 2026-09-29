"""Downstream deletion tasks -- created only by the verify fan-out (PRD 3.7)."""

from flask import Blueprint

import clock
import constants as K
import db
import response
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services import posture
from services.calc import add_days
from services.cascade import fulfill_request
from validators import F, no_body, parse

bp = Blueprint("deletion_tasks", __name__, url_prefix="/health-data/deletion-tasks")

TABLE = "deletion_tasks"


def _vendor_executed(row):
    """Part of check 8: notify and reissue require an executed agreement."""
    vendor = db.get("vendors", row.get("vendor_id"))
    if vendor is None or vendor.get("agreement_state") != "EXECUTED":
        fail("ERR_VENDOR_AGREEMENT_NOT_EXECUTED")
    return vendor


def _send(row, vendor):
    row["state"] = "NOTIFIED"
    row["attempt_count"] = row.get("attempt_count", 0) + 1
    row["due_at"] = add_days(clock.now(), vendor.get("deletion_sla_days", 30))


@bp.get("")
def list_tasks():
    require(STAFF)
    rows = filter_rows(TABLE, {"consumer_request_id": "consumer_request_id",
                               "vendor_id": "vendor_id", "state": "state"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_task(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.post("/<row_id>/notify")
def notify(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("DeletionTask")
    vendor = _vendor_executed(row)
    check_state(row, TABLE, ("PENDING",))
    # check 25.
    if row.get("attempt_count", 0) >= K.MAX_TASK_ATTEMPTS:
        fail("ERR_TASK_ATTEMPT_LIMIT")
    _send(row, vendor)
    db.touch(row)
    posture.recount_outstanding_tasks(db.get("consumer_requests", row["consumer_request_id"]))
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/reissue")
def reissue(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("DeletionTask")
    vendor = _vendor_executed(row)
    check_state(row, TABLE, ("FAILED",))
    # check 25.
    if row.get("attempt_count", 0) >= K.MAX_TASK_ATTEMPTS:
        fail("ERR_TASK_ATTEMPT_LIMIT")
    _send(row, vendor)
    row["failure_reason"] = None
    db.touch(row)
    posture.recount_outstanding_tasks(db.get("consumer_requests", row["consumer_request_id"]))
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/confirm")
def confirm(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("DeletionTask")
    check_state(row, TABLE, ("NOTIFIED",))
    row["state"] = "CONFIRMED"
    row["confirmed_at"] = clock.now()
    db.touch(row)

    # cascade hops 1 and 2.
    request_row = db.get("consumer_requests", row.get("consumer_request_id"))
    posture.recount_outstanding_tasks(request_row)
    if request_row is not None and request_row.get("outstanding_task_count", 0) == 0 \
            and request_row.get("state") == "VERIFIED":
        fulfill_request(request_row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/fail")
def fail_task(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    body = parse("DeletionTask", {"failure_reason": F("string")},
                 extra_allowed=("failure_reason",))
    check_state(row, TABLE, ("NOTIFIED",))
    row["state"] = "FAILED"
    row["failure_reason"] = body["failure_reason"]
    db.touch(row)
    posture.recount_outstanding_tasks(db.get("consumer_requests", row["consumer_request_id"]))
    return response.ok(db.serialize(row))
