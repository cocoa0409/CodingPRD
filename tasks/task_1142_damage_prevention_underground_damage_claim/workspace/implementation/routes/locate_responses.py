"""LocateResponse endpoints."""

from flask import Blueprint, request

import clock
from db import db
from errors import (err_invalid_state, err_locator_inactive, err_not_found,
                    err_ownership, err_ticket_expired)
from middleware import require_roles
from serializers import response_out
from services.core import recompute_locator_performance
from util import (get_pagination, new_id, paginate, parse_body, parse_dt,
                  require_enum, require_string, success_envelope)

bp = Blueprint("locate_responses", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/locate-responses", methods=["POST"])
def create_response():
    user_id, _ = require_roles("Locator")
    body = parse_body(required_fields=["locate_ticket_id", "locator_id", "response_code", "marks_completed_at"])
    locator_id = require_string(body["locator_id"], "locator_id")
    if locator_id != user_id:
        raise err_ownership("locator_id must equal X-User-ID")
    ticket = db.locate_tickets.get(body["locate_ticket_id"])
    if ticket is None:
        raise err_not_found("locate ticket not found")
    locator = db.locators.get(locator_id)
    if locator is None:
        raise err_not_found("locator not found")
    response_code = require_enum(body["response_code"], ("MARKED", "CLEAR", "PARTIAL"), "response_code")
    marks_completed_at = parse_dt(body["marks_completed_at"], "marks_completed_at")
    notes = body.get("notes", "")
    if not isinstance(notes, str):
        from errors import err_invalid_request
        raise err_invalid_request("notes must be a string")
    if ticket["status"] == "EXPIRED":
        raise err_ticket_expired()
    if locator["contract_status"] == "SUSPENDED":
        raise err_locator_inactive()
    now = clock.get_current_utc()
    rid = new_id()
    resp = {
        "id": rid,
        "locate_ticket_id": ticket["id"],
        "locator_id": locator_id,
        "response_code": response_code,
        "marks_completed_at": marks_completed_at,
        "accuracy_verdict": "UNAUDITED",
        "notes": notes,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.locate_responses[rid] = resp
    # first response flips the ticket OPEN -> COMPLETED
    if ticket["status"] == "OPEN":
        ticket["status"] = "COMPLETED"
        ticket["updated_at"] = now
        ticket["version"] += 1
    locator["total_responses"] += 1
    locator["updated_at"] = now
    locator["version"] += 1
    return success_envelope(response_out(resp), "object", 201)


@bp.route("/damage-recovery/locate-responses/<rid>", methods=["GET"])
def get_response(rid):
    require_roles(*ALL_ROLES)
    r = db.locate_responses.get(rid)
    if r is None:
        raise err_not_found("locate response not found")
    return success_envelope(response_out(r), "object", 200)


@bp.route("/damage-recovery/locate-responses", methods=["GET"])
def list_responses():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.locate_responses.values())
    ticket_id = request.args.get("locate_ticket_id")
    locator_id = request.args.get("locator_id")
    verdict = request.args.get("accuracy_verdict")
    if ticket_id is not None:
        items = [r for r in items if r["locate_ticket_id"] == ticket_id]
    if locator_id is not None:
        items = [r for r in items if r["locator_id"] == locator_id]
    if verdict is not None:
        items = [r for r in items if r["accuracy_verdict"] == verdict]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([response_out(r) for r in page], "array", 200, meta)


@bp.route("/damage-recovery/locate-responses/<rid>/audit", methods=["POST"])
def audit_response(rid):
    require_roles("DamageInvestigator")
    r = db.locate_responses.get(rid)
    if r is None:
        raise err_not_found("locate response not found")
    body = parse_body(required_fields=["verdict"])
    verdict = require_enum(body["verdict"], ("ACCURATE", "INACCURATE"), "verdict")
    if r["accuracy_verdict"] != "UNAUDITED":
        raise err_invalid_state("response has already been audited")
    r["accuracy_verdict"] = verdict
    r["updated_at"] = clock.get_current_utc()
    r["version"] += 1
    locator = db.locators.get(r["locator_id"])
    if locator is not None:
        recompute_locator_performance(locator)
        locator["updated_at"] = clock.get_current_utc()
        locator["version"] += 1
    return success_envelope(response_out(r), "object", 200)
