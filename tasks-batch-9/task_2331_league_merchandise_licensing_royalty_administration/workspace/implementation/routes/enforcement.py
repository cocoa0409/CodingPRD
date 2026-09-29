"""Counterfeit enforcement actions (PRD 3.9)."""

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, touch
from errors import ApiError
from middleware import (ROLE_AUDITOR, ROLE_CLUB, ROLE_COMPLIANCE, ROLE_FINANCE,
                        ROLE_MANAGER, guard, paginate, pagination)
from services import domain

bp = Blueprint("enforcement", __name__)

READ_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR, ROLE_CLUB]


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def _find(action_id):
    row = S.enforcements.get(action_id)
    if row is None:
        raise ApiError("ERR_ENFORCEMENT_NOT_FOUND")
    return row


@bp.post("/licensing/enforcement-actions")
def create_action():
    ctx = guard([ROLE_COMPLIANCE, ROLE_CLUB])
    body = ctx.body

    suspected = body.get("suspected_licensee_id")
    if suspected is not None and suspected not in S.licensees:
        raise ApiError("ERR_LICENSEE_NOT_FOUND")

    venue_type = V.req_enum(body, "venue_type", K.VENUE_TYPES)
    venue_reference = V.req_string(body, "venue_reference", 1, 200)
    target_name = V.req_string(body, "target_name", 1, 200)
    suspected_id = V.opt_string(body, "suspected_licensee_id")
    estimated_units = V.req_int(body, "estimated_units")
    if estimated_units < 0:
        _bad("estimated_units must be at least 0.")
    estimated_retail = V.req_cents(body, "estimated_retail_cents")

    row = db.base_row()
    row.update({
        "venue_type": venue_type,
        "venue_reference": venue_reference,
        "target_name": target_name,
        "suspected_licensee_id": suspected_id,
        "estimated_units": estimated_units,
        "estimated_retail_cents": estimated_retail,
        "seized_units": 0,
        "seizure_authority": None,
        "status": "REPORTED",
        "occurrence_quarter": None,
        "disposition": None,
        "recovered_cents": 0,
        "dismissal_reason": None,
    })
    S.enforcements[row["id"]] = row
    return response.created(serializers.dump("EnforcementAction", row))


@bp.get("/licensing/enforcement-actions")
def list_actions():
    guard(READ_ROLES)
    limit, offset = pagination()
    suspected = mw.filter_str("suspected_licensee_id")
    venue_type = mw.filter_enum("venue_type", K.VENUE_TYPES)
    status = mw.filter_enum("status", K.ENFORCEMENT_STATUSES)
    quarter = mw.filter_str("occurrence_quarter")

    rows = list(S.enforcements.values())
    if suspected is not None:
        rows = [r for r in rows if r["suspected_licensee_id"] == suspected]
    if venue_type is not None:
        rows = [r for r in rows if r["venue_type"] == venue_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if quarter is not None:
        rows = [r for r in rows if r["occurrence_quarter"] == quarter]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("EnforcementAction", page),
                            limit, offset, total)


@bp.get("/licensing/enforcement-actions/<action_id>")
def get_action(action_id):
    guard(READ_ROLES)
    action = _find(action_id)
    return response.ok(serializers.dump("EnforcementAction", action))


@bp.post("/licensing/enforcement-actions/<action_id>/status")
def action_status(action_id):
    ctx = guard([ROLE_COMPLIANCE])
    action = _find(action_id)
    body = ctx.body
    verb = V.req_enum(body, "action",
                      ("INVESTIGATE", "ORDER_SEIZURE", "RESOLVE", "DISMISS"))

    seized_units = None
    seizure_authority = None
    disposition = None
    recovered = None
    reason = None
    if verb == "ORDER_SEIZURE":
        seized_units = V.req_int(body, "seized_units")
        seizure_authority = V.req_string(body, "seizure_authority", 1, 200)
    elif verb == "RESOLVE":
        disposition = V.req_enum(body, "disposition", K.DISPOSITIONS)
        recovered = V.req_cents(body, "recovered_cents")
    elif verb == "DISMISS":
        reason = V.req_string(body, "reason", 1, 500)

    status = action["status"]
    if verb == "INVESTIGATE":
        if status != "REPORTED":
            raise ApiError("ERR_INVALID_STATE")
    elif verb == "ORDER_SEIZURE":
        if status != "INVESTIGATING":
            raise ApiError("ERR_INVALID_STATE")
    elif verb == "RESOLVE":
        if status != "SEIZURE_ORDERED":
            raise ApiError("ERR_INVALID_STATE")
    else:
        if status not in ("REPORTED", "INVESTIGATING"):
            raise ApiError("ERR_INVALID_STATE")

    if verb == "INVESTIGATE":
        action["status"] = "INVESTIGATING"
        touch(action)

    elif verb == "ORDER_SEIZURE":
        if seized_units < 1 or seized_units > action["estimated_units"]:
            _bad("seized_units must be between 1 and estimated_units.")
        action["status"] = "SEIZURE_ORDERED"
        action["seized_units"] = seized_units
        action["seizure_authority"] = seizure_authority
        action["occurrence_quarter"] = db.current_quarter()
        touch(action)
        _refresh_named_licensee(action)

    elif verb == "RESOLVE":
        action["status"] = "RESOLVED"
        action["disposition"] = disposition
        action["recovered_cents"] = recovered
        touch(action)

    else:
        action["status"] = "DISMISSED"
        action["dismissal_reason"] = reason
        touch(action)
        if status == "INVESTIGATING":
            _refresh_named_licensee(action)

    return response.ok(serializers.dump("EnforcementAction", action))


def _refresh_named_licensee(action):
    licensee_id = action["suspected_licensee_id"]
    if not licensee_id:
        return
    licensee = S.licensees.get(licensee_id)
    if licensee is None:
        return
    domain.refresh_risk_index(licensee)
