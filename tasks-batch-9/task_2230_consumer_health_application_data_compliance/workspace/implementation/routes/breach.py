"""Breach incidents and the dual notification clocks (PRD 3.9)."""

from flask import Blueprint

import clock
import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services import posture
from services.calc import breach_deadlines
from validators import F, no_body, parse

bp = Blueprint("breach", __name__, url_prefix="/health-data/breach-incidents")

TABLE = "breach_incidents"


@bp.post("")
def create_incident():
    require("SecurityEngineer")
    body = parse("BreachIncident", {
        "app_product_id": F("string"),
        "incident_label": F("string"),
        "discovered_at": F("datetime"),
        "breach_scope": F("enum", members=V.BREACH_SCOPES),
        "protection_state": F("enum", members=V.PROTECTION_STATES),
        "affected_consumer_count": F("int", minimum=0),
        "affected_state_max_count": F("int", minimum=0),
    })
    product = load("app_products", body["app_product_id"])
    if body["affected_state_max_count"] > body["affected_consumer_count"]:
        fail("ERR_INVALID_REQUEST",
             "affected_state_max_count may not exceed affected_consumer_count.")

    row = db.new_row(TABLE, {
        "app_product_id": product["id"],
        "incident_label": body["incident_label"],
        "discovered_at": body["discovered_at"],
        "breach_scope": body["breach_scope"],
        "protection_state": body["protection_state"],
        "affected_consumer_count": body["affected_consumer_count"],
        "affected_state_max_count": body["affected_state_max_count"],
        "state": "DISCOVERED",
        "health_rule_deadline_at": None,
        "general_rule_deadline_at": None,
        "governing_deadline_at": None,
        "media_notice_required": False,
        "media_notice_sent": False,
        "notified_at": None,
        "exposure_contribution_cents": 0,
    })
    return response.created(db.serialize(row))


@bp.get("")
def list_incidents():
    require(STAFF)
    rows = filter_rows(TABLE, {"app_product_id": "app_product_id", "state": "state"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_incident(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.post("/<row_id>/assess")
def assess(row_id):
    require("SecurityEngineer")
    row = load(TABLE, row_id)
    no_body("BreachIncident")
    check_state(row, TABLE, ("DISCOVERED",))

    if row["protection_state"] == "ENCRYPTED_SECURED":
        # branch 2: no deadlines, no exposure.
        row["state"] = "NOT_REPORTABLE"
        db.touch(row)
        return response.ok(db.serialize(row))

    result = breach_deadlines(row)
    row["state"] = "REPORTABLE"
    row["health_rule_deadline_at"] = result["health_rule_deadline_at"]
    row["general_rule_deadline_at"] = result["general_rule_deadline_at"]
    row["governing_deadline_at"] = result["governing_deadline_at"]
    row["media_notice_required"] = result["media_notice_required"]
    row["exposure_contribution_cents"] = result["exposure_contribution_cents"]
    db.touch(row)
    posture.recount_exposure(db.get("app_products", row["app_product_id"]))
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/notify")
def notify(row_id):
    require("SecurityEngineer")
    row = load(TABLE, row_id)
    body = parse("BreachIncident", {"media_notice_sent": F("bool")},
                 extra_allowed=("media_notice_sent",))
    check_state(row, TABLE, ("REPORTABLE",))
    # check 44.
    deadline = row.get("governing_deadline_at")
    if deadline is not None and clock.now() > deadline:
        fail("ERR_NOTIFICATION_DEADLINE_PASSED")
    # check 45.
    if row.get("media_notice_required") and not body["media_notice_sent"]:
        fail("ERR_MEDIA_NOTICE_REQUIRED")

    row["state"] = "NOTIFIED"
    row["notified_at"] = clock.now()
    row["media_notice_sent"] = body["media_notice_sent"]
    db.touch(row)
    posture.recount_exposure(db.get("app_products", row["app_product_id"]))
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/retract")
def retract(row_id):
    require("SecurityEngineer")
    row = load(TABLE, row_id)
    no_body("BreachIncident")
    check_state(row, TABLE, ("REPORTABLE",))
    row["state"] = "DISCOVERED"
    row["health_rule_deadline_at"] = None
    row["general_rule_deadline_at"] = None
    row["governing_deadline_at"] = None
    row["media_notice_required"] = False
    row["exposure_contribution_cents"] = 0
    db.touch(row)
    posture.recount_exposure(db.get("app_products", row["app_product_id"]))
    return response.ok(db.serialize(row))
