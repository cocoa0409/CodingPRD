"""Consumer rights requests (PRD 3.6)."""

from flask import Blueprint

import clock
import constants as K
import db
import response
import validators as V
from errors import fail
from middleware import STAFF_AND_CONSUMER, require
from routes.common import check_state, consumer_scope, filter_rows, load
from services import posture
from services.calc import add_days, deletion_task_fanout, request_response_deadline
from services.cascade import deny_request, fulfill_request
from validators import F, no_body, parse

bp = Blueprint("consumer_requests", __name__, url_prefix="/health-data/consumer-requests")

TABLE = "consumer_requests"


def _refresh_deadline(row):
    row["response_deadline_at"] = request_response_deadline(row)


def _fan_out(row, consumer):
    """verify hop: create one PENDING DeletionTask per selected vendor."""
    for vendor, hop in deletion_task_fanout(consumer):
        db.new_row("deletion_tasks", {
            "consumer_request_id": row["id"],
            "vendor_id": vendor["id"],
            "hop_distance": hop,
            "state": "PENDING",
            "attempt_count": 0,
            "due_at": None,
            "confirmed_at": None,
            "failure_reason": None,
        })
    posture.recount_outstanding_tasks(row)


@bp.post("")
def create_request():
    user_id, role = require("Consumer")
    body = parse("ConsumerRequest", {
        "consumer_id": F("string"),
        "request_kind": F("enum", members=V.REQUEST_KINDS),
        "submitted_channel": F("enum", members=V.SUBMITTED_CHANNELS),
    })
    consumer = load("consumers", body["consumer_id"])
    consumer_scope(role, user_id, consumer["id"])

    row = db.new_row(TABLE, {
        "consumer_id": consumer["id"],
        "request_kind": body["request_kind"],
        "submitted_channel": body["submitted_channel"],
        "received_at": clock.now(),
        "state": "RECEIVED",
        "verification_rounds_used": 0,
        "verification_window_ends_at": None,
        "verified_at": None,
        "extension_granted": False,
        "response_deadline_at": None,
        "outstanding_task_count": 0,
        "denial_reason": None,
    })
    _refresh_deadline(row)
    return response.created(db.serialize(row))


@bp.get("")
def list_requests():
    require(STAFF_AND_CONSUMER)
    rows = filter_rows(TABLE, {"consumer_id": "consumer_id", "state": "state",
                               "request_kind": "request_kind"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_request(row_id):
    require(STAFF_AND_CONSUMER)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.post("/<row_id>/request-more-info")
def request_more_info(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("ConsumerRequest")
    check_state(row, TABLE, ("RECEIVED",))
    # check 24.
    if row.get("verification_rounds_used", 0) >= K.MAX_VERIFICATION_ROUNDS:
        fail("ERR_VERIFICATION_ROUNDS_EXHAUSTED")
    row["state"] = "VERIFICATION_PENDING"
    row["verification_rounds_used"] = row.get("verification_rounds_used", 0) + 1
    row["verification_window_ends_at"] = add_days(clock.now(), K.VERIFICATION_WINDOW_DAYS)
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/resubmit-identity")
def resubmit_identity(row_id):
    user_id, role = require("Consumer")
    row = load(TABLE, row_id)
    no_body("ConsumerRequest")
    consumer_scope(role, user_id, row.get("consumer_id"))
    check_state(row, TABLE, ("VERIFICATION_PENDING",))
    # check 40.
    window_end = row.get("verification_window_ends_at")
    if window_end is not None and clock.now() > window_end:
        fail("ERR_VERIFICATION_WINDOW_EXPIRED")
    row["state"] = "RECEIVED"
    row["verification_window_ends_at"] = None
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/verify")
def verify(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    body = parse("ConsumerRequest", {"verification_token": F("string")},
                 extra_allowed=("verification_token",))
    check_state(row, TABLE, ("RECEIVED",))
    consumer = load("consumers", row["consumer_id"])
    # check 41.
    if body["verification_token"] != consumer.get("verification_token"):
        fail("ERR_VERIFICATION_TOKEN_MISMATCH")

    row["state"] = "VERIFIED"
    row["verified_at"] = clock.now()
    _refresh_deadline(row)
    db.touch(row)

    if row["request_kind"] == "DELETE":
        _fan_out(row, consumer)
        if row.get("outstanding_task_count", 0) == 0:
            fulfill_request(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/extend")
def extend(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("ConsumerRequest")
    # check 26.
    if row.get("extension_granted"):
        fail("ERR_EXTENSION_ALREADY_GRANTED")
    row["extension_granted"] = True
    _refresh_deadline(row)
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/fulfill")
def fulfill(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("ConsumerRequest")
    check_state(row, TABLE, ("VERIFIED",))
    # check 42.
    deadline = row.get("response_deadline_at")
    if deadline is not None and clock.now() > deadline:
        fail("ERR_RESPONSE_DEADLINE_PASSED")
    # check 43.
    if row.get("outstanding_task_count", 0) != 0:
        fail("ERR_DELETION_TASKS_OUTSTANDING")
    fulfill_request(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/deny")
def deny(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    body = parse("ConsumerRequest", {"denial_reason": F("string")},
                 extra_allowed=("denial_reason",))
    check_state(row, TABLE, ("RECEIVED", "VERIFICATION_PENDING", "VERIFIED"))
    deny_request(row, body["denial_reason"])
    return response.ok(db.serialize(row))
