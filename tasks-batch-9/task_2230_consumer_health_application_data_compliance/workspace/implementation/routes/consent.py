"""Consent records: three parallel axes plus withdrawal cascades (PRD 3.5)."""

from flask import Blueprint

import clock
import db
import response
import validators as V
from errors import fail
from middleware import STAFF_AND_CONSUMER, require
from routes.common import consumer_scope, filter_rows, load
from services import posture
from services.cascade import withdraw_axis
from validators import F, parse

bp = Blueprint("consent", __name__, url_prefix="/health-data/consent-records")

TABLE = "consent_records"

_AXIS_FIELD = {"COLLECT": "collection_state", "SHARE": "sharing_state", "SELL": "sale_state"}
_GRANTABLE = {"COLLECT": ("NOT_REQUESTED", "WITHDRAWN"),
              "SHARE": ("NOT_REQUESTED", "WITHDRAWN"),
              "SELL": ("NOT_REQUESTED", "REVOKED")}
_WITHDRAWABLE = {"COLLECT": "GRANTED", "SHARE": "GRANTED", "SELL": "AUTHORIZED"}


@bp.post("")
def create_record():
    require("PrivacyOfficer", "PlatformAdmin")
    body = parse("ConsentRecord", {
        "consumer_id": F("string"),
        "expected_consumer_version": F("int"),
    }, extra_allowed=("expected_consumer_version",))
    consumer = load("consumers", body["consumer_id"])

    # check 9: optimistic concurrency on the parent consumer.
    if body["expected_consumer_version"] != consumer.get("version"):
        fail("ERR_STALE_CONSUMER_VERSION")

    for other in db.rows_of(TABLE):
        if other.get("consumer_id") == consumer["id"] and other.get("record_state") == "ACTIVE":
            other["record_state"] = "SUPERSEDED"
            db.touch(other)

    row = db.new_row(TABLE, {
        "consumer_id": consumer["id"],
        "collection_state": "NOT_REQUESTED",
        "sharing_state": "NOT_REQUESTED",
        "sale_state": "NOT_REQUESTED",
        "record_state": "ACTIVE",
        "collection_granted_at": None,
        "sharing_granted_at": None,
        "sale_authorized_at": None,
        "last_withdrawn_axis": None,
        "last_withdrawn_at": None,
        "processing_halt_deadline_at": None,
    })
    posture.recount_share_consent(posture.product_of_consumer(consumer))
    db.touch(consumer)
    return response.created(db.serialize(row))


@bp.get("")
def list_records():
    require(STAFF_AND_CONSUMER)
    rows = filter_rows(TABLE, {"consumer_id": "consumer_id", "record_state": "record_state"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_record(row_id):
    require(STAFF_AND_CONSUMER)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.post("/<row_id>/grants")
def grants(row_id):
    user_id, role = require("Consumer")
    row = load(TABLE, row_id)
    body = parse("ConsentRecord", {"axes": F("enum_list", members=V.CONSENT_AXES)},
                 extra_allowed=("axes",))
    axes = body["axes"]

    consumer_scope(role, user_id, row.get("consumer_id"))
    consumer = load("consumers", row["consumer_id"])

    # check 8: the record itself must still be live.
    if row.get("record_state") != "ACTIVE":
        fail("ERR_ALREADY_TERMINAL")

    # check 8 continued: the named axis must admit a grant. Only meaningful for a
    # single-axis call; a bundled call is rejected by check 14 below.
    if len(axes) == 1:
        axis = axes[0]
        if row.get(_AXIS_FIELD[axis]) not in _GRANTABLE[axis]:
            fail("ERR_INVALID_STATE")

    # check 13.
    if "SELL" in axes and consumer.get("age_band") in ("MINOR_13_16", "UNDER_13"):
        fail("ERR_MINOR_SALE_PROHIBITED")

    # check 14.
    if len(axes) != 1:
        fail("ERR_CONSENT_BUNDLING_PROHIBITED")

    axis = axes[0]
    # checks 15 and 16.
    if axis == "SHARE" and row.get("collection_state") != "GRANTED":
        fail("ERR_COLLECTION_CONSENT_REQUIRED")
    if axis == "SELL" and row.get("sharing_state") != "GRANTED":
        fail("ERR_SHARING_CONSENT_REQUIRED")

    now = clock.now()
    if axis == "COLLECT":
        row["collection_state"] = "GRANTED"
        row["collection_granted_at"] = now
    elif axis == "SHARE":
        row["sharing_state"] = "GRANTED"
        row["sharing_granted_at"] = now
    else:
        row["sale_state"] = "AUTHORIZED"
        row["sale_authorized_at"] = now
    db.touch(row)
    posture.recount_share_consent(posture.product_of_consumer(consumer))
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/withdrawals")
def withdrawals(row_id):
    user_id, role = require("Consumer")
    row = load(TABLE, row_id)
    body = parse("ConsentRecord", {"axis": F("enum", members=V.CONSENT_AXES)},
                 extra_allowed=("axis",))
    axis = body["axis"]

    consumer_scope(role, user_id, row.get("consumer_id"))
    consumer = load("consumers", row["consumer_id"])

    if row.get("record_state") != "ACTIVE":
        fail("ERR_ALREADY_TERMINAL")
    if row.get(_AXIS_FIELD[axis]) != _WITHDRAWABLE[axis]:
        fail("ERR_INVALID_STATE")

    withdraw_axis(row, axis, posture.product_of_consumer(consumer))
    return response.ok(db.serialize(row))
