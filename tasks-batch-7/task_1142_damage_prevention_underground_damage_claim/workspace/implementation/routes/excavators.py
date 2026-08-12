"""Excavator endpoints."""

from flask import Blueprint, request

import clock
from db import db
from errors import err_invalid_request, err_not_found
from middleware import get_auth, require_roles
from serializers import excavator_out
from services.core import evaluate_program, recompute_offender_points
from util import (get_pagination, new_id, paginate, parse_body,
                  require_string, success_envelope)

bp = Blueprint("excavators", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/excavators", methods=["POST"])
def create_excavator():
    require_roles("RecoveryManager")
    body = parse_body(required_fields=["company_name", "contact_email"])
    company_name = require_string(body["company_name"], "company_name")
    contact_email = require_string(body["contact_email"], "contact_email")
    now = clock.get_current_utc()
    eid = new_id()
    exc = {
        "id": eid,
        "company_name": company_name,
        "contact_email": contact_email,
        "program_status": "GOOD_STANDING",
        "offender_points": 0,
        "credit_balance_cents": 0,
        "total_outstanding_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.excavators[eid] = exc
    return success_envelope(excavator_out(exc), "object", 201)


@bp.route("/damage-recovery/excavators/<eid>", methods=["GET"])
def get_excavator(eid):
    require_roles(*ALL_ROLES)
    exc = db.excavators.get(eid)
    if exc is None:
        raise err_not_found("excavator not found")
    recompute_offender_points(exc)
    return success_envelope(excavator_out(exc), "object", 200)


@bp.route("/damage-recovery/excavators", methods=["GET"])
def list_excavators():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.excavators.values())
    status = request.args.get("program_status")
    if status is not None:
        items = [e for e in items if e["program_status"] == status]
    for e in items:
        recompute_offender_points(e)
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([excavator_out(e) for e in page], "array", 200, meta)


@bp.route("/damage-recovery/excavators/<eid>/evaluate-program", methods=["POST"])
def evaluate_program_endpoint(eid):
    require_roles("RecoveryManager")
    exc = db.excavators.get(eid)
    if exc is None:
        raise err_not_found("excavator not found")
    evaluate_program(exc)
    return success_envelope(excavator_out(exc), "object", 200)
