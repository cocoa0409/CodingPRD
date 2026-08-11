"""Referral endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch, clock
from middleware import require_roles
from response import success_object

bp = Blueprint("referrals", __name__)


@bp.post("/api/referrals")
def create_referral():
    require_roles(["IntakeCoordinator"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"client_id", "source_type", "referring_party"})
    client_id = v.req_string(body, "client_id")
    source_type = v.req_enum(body, "source_type", {"PHYSICIAN", "VR_AGENCY", "INSURANCE", "SELF"})
    referring_party = v.req_string(body, "referring_party")

    client = store.clients.get(client_id)
    if client is None:
        raise errors.not_found("Client not found")

    referral = new_entity()
    referral.update({
        "client_id": client_id,
        "source_type": source_type,
        "referring_party": referring_party,
        "status": "RECEIVED",
        "decided_at": None,
    })
    store.referrals[referral["id"]] = referral
    return success_object(referral, status=201)


@bp.post("/api/referrals/<rid>/decide")
def decide_referral(rid):
    require_roles(["IntakeCoordinator"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"decision"})
    decision = v.req_enum(body, "decision", {"ACCEPT", "DECLINE"})

    referral = store.referrals.get(rid)
    if referral is None:
        raise errors.not_found("Referral not found")
    if referral["status"] != "RECEIVED":
        raise errors.invalid_state("Referral already decided")

    referral["status"] = "ACCEPTED" if decision == "ACCEPT" else "DECLINED"
    referral["decided_at"] = clock.now_iso()
    touch(referral)

    if decision == "ACCEPT":
        client = store.clients.get(referral["client_id"])
        if client is not None and client["status"] == "INTAKE":
            client["status"] = "ACTIVE"
            touch(client)

    return success_object(referral)
