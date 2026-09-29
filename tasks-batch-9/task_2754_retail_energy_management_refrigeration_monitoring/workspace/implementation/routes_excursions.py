"""Food-safety documentation, closure and posture release (PRD 3.4)."""

from flask import Blueprint, g

import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import DISPOSITIONS
from db import db
from errors import ApiError
from routes_cases import open_excursion_of
from security import (FOOD_SAFETY_OFFICER, NON_GATEWAY_ROLES, STORE_MANAGER,
                      roles, require_store_scope)
from util import fmt_iso

bp = Blueprint("excursions", __name__)


@bp.route("/excursions/<excursion_id>", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def get_excursion(excursion_id):
    excursion = common.get_excursion(excursion_id)
    return envelope.ok(serial.excursion(excursion))


@bp.route("/excursions/<excursion_id>/acknowledge", methods=["POST"])
@roles(STORE_MANAGER)
def acknowledge(excursion_id):
    excursion = common.get_excursion(excursion_id)
    store = derive.store_of_excursion(excursion)
    require_store_scope(store["id"] if store is not None else None)
    if excursion["state"] != "OPEN":
        raise ApiError("ERR_EXCURSION_STATE_INVALID")
    excursion["state"] = "ACKNOWLEDGED"
    excursion["acknowledged_by_user_id"] = g.user_id
    cascade.touch(excursion)
    return envelope.ok(serial.excursion(excursion))


@bp.route("/excursions/<excursion_id>/document-disposition", methods=["POST"])
@roles(FOOD_SAFETY_OFFICER)
def document_disposition(excursion_id):
    body = v.body()
    disposition = v.get_enum(body, "disposition", DISPOSITIONS)
    note = v.get_str(body, "corrective_action_note", min_len=1)
    excursion = common.get_excursion(excursion_id)
    if excursion["state"] == "CLOSED":
        raise ApiError("ERR_EXCURSION_STATE_INVALID")
    if excursion["mandatory_disposition"] == "DISCARD" and disposition != "DISCARD":
        raise ApiError("ERR_DISPOSITION_MANDATE_VIOLATION")
    excursion["disposition"] = disposition
    excursion["corrective_action_note"] = note
    excursion["documented_by_user_id"] = g.user_id
    excursion["documented_at_iso"] = db.clock
    cascade.touch(excursion)
    return envelope.ok(serial.excursion(excursion))


@bp.route("/excursions/<excursion_id>/close", methods=["POST"])
@roles(FOOD_SAFETY_OFFICER)
def close_excursion(excursion_id):
    excursion = common.get_excursion(excursion_id)
    if excursion["state"] == "CLOSED":
        raise ApiError("ERR_EXCURSION_STATE_INVALID")
    if (excursion["disposition"] is None
            or excursion["corrective_action_note"] is None):
        raise ApiError("ERR_FOOD_SAFETY_DOC_INCOMPLETE")
    excursion["state"] = "CLOSED"
    excursion["closed_at_iso"] = db.clock
    cascade.touch(excursion)
    case = derive.case_of_excursion(excursion)
    store = derive.store_of_case(case) if case is not None else None
    if (case is not None and case["monitoring_state"] == "ALARM"
            and open_excursion_of(case) is None):
        case["monitoring_state"] = "ARMED"
        case["consecutive_breach_count"] = 0
        case["_run"] = []
        cascade.touch(case)
        cascade.touch(store)
    cascade.recompute_posture(store)
    return envelope.ok(serial.excursion(excursion))
