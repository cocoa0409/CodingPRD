"""Attendees: identity rules and verification decision (PRD §3.3)."""
from flask import Blueprint, request

import db
from db import appointments, attendees, homebuyers
from errors import (
    err_attendee_identity, err_invalid_state, err_not_found, err_poa_document_required,
    err_referenced_entity_not_found, err_self_verification,
)
from middleware import (
    ROLE_BUYER, ROLE_MANAGER, ROLE_REP, require_roles,
)
from response import paginate, success_list, success_object
from validation import json_body, opt_str, req_enum, req_str

bp = Blueprint("attendees", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)
ATTENDEE_TYPES = ("BUYER", "CO_BUYER", "POA_PROXY")
DECISIONS = ("VERIFIED", "REJECTED")


def _get_attendee_or_404(attendee_id):
    rec = attendees.get(attendee_id)
    if rec is None:
        raise err_not_found("Attendee %s not found." % attendee_id)
    return rec


@bp.post("/api/attendees")
def create_attendee():
    require_roles(ROLE_REP)
    body = json_body()
    appointment_id = req_str(body, "appointment_id")
    attendee_type = req_enum(body, "attendee_type", ATTENDEE_TYPES)
    buyer_id = body.get("buyer_id")
    proxy_name = body.get("proxy_name")
    poa_document_ref = body.get("poa_document_ref")
    if buyer_id is not None and not isinstance(buyer_id, str):
        from errors import err_validation
        raise err_validation("Field 'buyer_id' must be a string.")
    if proxy_name is not None and not isinstance(proxy_name, str):
        from errors import err_validation
        raise err_validation("Field 'proxy_name' must be a string.")
    if poa_document_ref is not None and not isinstance(poa_document_ref, str):
        from errors import err_validation
        raise err_validation("Field 'poa_document_ref' must be a string.")

    # Body foreign keys (priority 6)
    appt = appointments.get(appointment_id)
    if appt is None:
        raise err_referenced_entity_not_found("appointment_id does not resolve.")
    if attendee_type in ("BUYER", "CO_BUYER") and buyer_id is not None:
        if buyer_id not in homebuyers:
            raise err_referenced_entity_not_found("buyer_id does not resolve.")

    # Compliance / identity rules (priority 8)
    if attendee_type == "POA_PROXY":
        if not proxy_name or not poa_document_ref:
            raise err_poa_document_required()
        if buyer_id is not None:
            raise err_attendee_identity("buyer_id is forbidden on a POA_PROXY attendee.")
    else:  # BUYER / CO_BUYER
        if buyer_id is None:
            raise err_attendee_identity("buyer_id is required for BUYER/CO_BUYER attendees.")
        if proxy_name is not None or poa_document_ref is not None:
            raise err_attendee_identity("Proxy fields are forbidden on BUYER/CO_BUYER attendees.")

    rec = db.stamp({
        "id": db.new_id(),
        "appointment_id": appointment_id,
        "attendee_type": attendee_type,
        "buyer_id": buyer_id if attendee_type in ("BUYER", "CO_BUYER") else None,
        "proxy_name": proxy_name if attendee_type == "POA_PROXY" else None,
        "poa_document_ref": poa_document_ref if attendee_type == "POA_PROXY" else None,
        "verification_status": "PENDING",
        "decided_by_user_id": None,
        "rejection_reason": None,
    })
    attendees[rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.get("/api/attendees/<attendee_id>")
def get_attendee(attendee_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_attendee_or_404(attendee_id)))


@bp.get("/api/attendees")
def list_attendees():
    require_roles(*READ_ROLES)
    items = list(attendees.values())
    for f in ("appointment_id", "buyer_id", "verification_status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(a) for a in page], pagination)


@bp.post("/api/attendees/<attendee_id>/decide-verification")
def decide_verification(attendee_id):
    actor = require_roles(ROLE_REP, ROLE_MANAGER)
    body = json_body()
    decision = req_enum(body, "decision", DECISIONS)
    rejection_reason = opt_str(body, "rejection_reason")

    rec = _get_attendee_or_404(attendee_id)
    appt = appointments[rec["appointment_id"]]
    if rec["verification_status"] != "PENDING":
        raise err_invalid_state("Attendee verification has already been decided.")
    if appt["status"] not in ("CONFIRMED", "IN_PROGRESS"):
        raise err_invalid_state("Attendees can only be decided on a CONFIRMED or IN_PROGRESS appointment.")
    # Segregation of duties: the conducting rep may not decide; managers exempt.
    if actor.role == ROLE_REP and actor.user_id == appt["rep_id"]:
        raise err_self_verification()

    rec["verification_status"] = decision
    rec["decided_by_user_id"] = actor.user_id
    rec["rejection_reason"] = rejection_reason if decision == "REJECTED" else None
    db.touch(rec)
    return success_object(db.public(rec))
