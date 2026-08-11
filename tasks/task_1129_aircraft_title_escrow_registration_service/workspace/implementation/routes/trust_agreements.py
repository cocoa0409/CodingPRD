"""TrustAgreement endpoints."""

from datetime import date

from flask import Blueprint, request

import db
from db import (
    trust_agreement_store, aircraft_store, party_store, escrow_file_store,
    make_common_fields, touch, now_iso, get_logical_now,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_TRANSITION,
    ERR_TRUSTEE_NOT_QUALIFIED, ERR_TRUST_OVERLAP, ERR_INVALID_DATE_RANGE,
    ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.escrow import recompute_posture, try_bubble_cleared, try_bubble_funded
from validators import (
    get_body, require_fields, require_string, require_enum, require_date_string,
)

bp = Blueprint("trust_agreements", __name__)

VALID_CITIZENSHIPS = ["US_CITIZEN", "NON_US_CITIZEN"]
TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}


def _parse_limit():
    try:
        v = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        v = 10
    return max(1, min(100, v))


def _parse_offset():
    try:
        v = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        v = 0
    return max(0, v)


@bp.route("/api/trust-agreements", methods=["POST"])
def create_trust_agreement():
    user_id, role = require_roles(["EscrowOfficer"])
    body = get_body()
    require_fields(
        body,
        ["aircraft_id", "trustee_party_id", "beneficiary_name", "beneficiary_citizenship",
         "effective_date", "expiry_date"],
    )

    aircraft_id = require_string(body["aircraft_id"], "aircraft_id")
    trustee_party_id = require_string(body["trustee_party_id"], "trustee_party_id")
    beneficiary_name = require_string(body["beneficiary_name"], "beneficiary_name")
    beneficiary_citizenship = require_enum(body["beneficiary_citizenship"], "beneficiary_citizenship", VALID_CITIZENSHIPS)
    effective_date = require_date_string(body["effective_date"], "effective_date")
    expiry_date = require_date_string(body["expiry_date"], "expiry_date")

    # Existence
    if not aircraft_store.get(aircraft_id):
        raise ApiError(ERR_NOT_FOUND, "Aircraft not found.", 404)
    trustee = party_store.get(trustee_party_id)
    if not trustee:
        raise ApiError(ERR_NOT_FOUND, "Trustee party not found.", 404)
    if trustee["party_type"] != "TRUSTEE":
        raise ApiError(ERR_INVALID_REQUEST, "trustee_party_id must reference a TRUSTEE party.", 400)

    # Date range check
    eff = date.fromisoformat(effective_date)
    exp = date.fromisoformat(expiry_date)
    if eff >= exp:
        raise ApiError(ERR_INVALID_DATE_RANGE, "effective_date must be strictly before expiry_date.", 422)

    fields = make_common_fields()
    ta = {
        **fields,
        "aircraft_id": aircraft_id,
        "trustee_party_id": trustee_party_id,
        "beneficiary_name": beneficiary_name,
        "beneficiary_citizenship": beneficiary_citizenship,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "status": "DRAFT",
        "submitted_at": None,
    }
    trust_agreement_store[ta["id"]] = ta
    return success_object(ta, 201)


@bp.route("/api/trust-agreements/<id>/submit", methods=["POST"])
def submit_trust(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ta = trust_agreement_store.get(id)
    if not ta:
        raise ApiError(ERR_NOT_FOUND, "TrustAgreement not found.", 404)

    if ta["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot submit trust in status {ta['status']}.", 409)

    # Trustee qualification check
    trustee = party_store.get(ta["trustee_party_id"])
    if not trustee or not trustee.get("is_citizenship_verified"):
        raise ApiError(ERR_TRUSTEE_NOT_QUALIFIED, "Trustee party lacks citizenship verification.", 422)

    ta["status"] = "SUBMITTED"
    ta["submitted_at"] = now_iso()
    touch(ta)
    return success_object(ta)


@bp.route("/api/trust-agreements/<id>/accept", methods=["POST"])
def accept_trust(id):
    user_id, role = require_roles(["EscrowManager"])
    ta = trust_agreement_store.get(id)
    if not ta:
        raise ApiError(ERR_NOT_FOUND, "TrustAgreement not found.", 404)

    if ta["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot accept trust in status {ta['status']}.", 409)

    # Overlap check: no ACCEPTED trust for same aircraft with strict interior overlap
    eff = date.fromisoformat(ta["effective_date"])
    exp = date.fromisoformat(ta["expiry_date"])
    for other in trust_agreement_store.values():
        if other["id"] == ta["id"]:
            continue
        if other["aircraft_id"] != ta["aircraft_id"]:
            continue
        if other["status"] != "ACCEPTED":
            continue
        o_eff = date.fromisoformat(other["effective_date"])
        o_exp = date.fromisoformat(other["expiry_date"])
        # Strict interior overlap: NOT (touching endpoints)
        # Overlap iff eff < o_exp AND o_eff < exp
        if eff < o_exp and o_eff < exp:
            raise ApiError(ERR_TRUST_OVERLAP, "Overlaps with an existing ACCEPTED trust.", 409)

    ta["status"] = "ACCEPTED"
    touch(ta)

    # Posture recompute on requires_trust files for this aircraft
    for ef in escrow_file_store.values():
        if ef["aircraft_id"] == ta["aircraft_id"] and ef.get("requires_trust"):
            recompute_posture(ef)
            touch(ef)
            try_bubble_cleared(ef)
            try_bubble_funded(ef)

    return success_object(ta)


@bp.route("/api/trust-agreements/<id>/reject", methods=["POST"])
def reject_trust(id):
    user_id, role = require_roles(["EscrowManager"])
    ta = trust_agreement_store.get(id)
    if not ta:
        raise ApiError(ERR_NOT_FOUND, "TrustAgreement not found.", 404)

    if ta["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot reject trust in status {ta['status']}.", 409)

    ta["status"] = "REJECTED"
    touch(ta)
    return success_object(ta)


@bp.route("/api/trust-agreements/<id>/revise", methods=["POST"])
def revise_trust(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ta = trust_agreement_store.get(id)
    if not ta:
        raise ApiError(ERR_NOT_FOUND, "TrustAgreement not found.", 404)

    if ta["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot revise trust in status {ta['status']}.", 409)

    body = get_body()
    require_fields(body, [], ["effective_date", "expiry_date"])

    new_eff = body.get("effective_date")
    new_exp = body.get("expiry_date")

    if new_eff is not None:
        require_date_string(new_eff, "effective_date")
    if new_exp is not None:
        require_date_string(new_exp, "expiry_date")

    # Determine final dates
    final_eff = new_eff if new_eff is not None else ta["effective_date"]
    final_exp = new_exp if new_exp is not None else ta["expiry_date"]

    if date.fromisoformat(final_eff) >= date.fromisoformat(final_exp):
        raise ApiError(ERR_INVALID_DATE_RANGE, "effective_date must be strictly before expiry_date.", 422)

    ta["effective_date"] = final_eff
    ta["expiry_date"] = final_exp
    ta["status"] = "DRAFT"
    ta["submitted_at"] = None
    touch(ta)
    return success_object(ta)


@bp.route("/api/trust-agreements", methods=["GET"])
def list_trust_agreements():
    user_id, role = require_roles(ALL_ROLES)
    items = list(trust_agreement_store.values())

    aircraft_id = request.args.get("aircraft_id")
    trustee_party_id = request.args.get("trustee_party_id")
    status = request.args.get("status")

    if aircraft_id:
        items = [t for t in items if t["aircraft_id"] == aircraft_id]
    if trustee_party_id:
        items = [t for t in items if t["trustee_party_id"] == trustee_party_id]
    if status:
        items = [t for t in items if t["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


@bp.route("/api/trust-agreements/<id>", methods=["GET"])
def get_trust_agreement(id):
    user_id, role = require_roles(ALL_ROLES)
    ta = trust_agreement_store.get(id)
    if not ta:
        raise ApiError(ERR_NOT_FOUND, "TrustAgreement not found.", 404)
    return success_object(ta)
