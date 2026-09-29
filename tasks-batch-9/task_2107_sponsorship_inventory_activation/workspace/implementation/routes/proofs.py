"""Proof of performance capture and adjudication (PRD 3.8)."""

from flask import Blueprint, request, g

import db
from db import store, new_row, touch
from errors import ApiError
from middleware import endpoint
from response import ok, created, paginate
from services.cascade import (refresh_booking_evidence, rollup_entitlement,
                              rollup_contract, rollup_property)
from services.serialize import proof_out
from routes.bookings import get_booking_or_404
from util import body_of, fail, v_str, v_int, v_enum, v_pagination

bp = Blueprint("proofs", __name__)

EVIDENCE_TYPES = {"PHOTO", "IMPRESSIONS", "SOCIAL"}
DECISIONS = {"VERIFIED", "REJECTED"}
READ_ROLES = ["PropertyAdmin", "ContractApprover", "ActivationManager", "PerformanceAuditor"]


def get_proof_or_404(proof_id):
    proof = store.proofs.get(proof_id)
    if proof is None:
        raise ApiError("ERR_PROOF_NOT_FOUND", 404)
    return proof


@bp.post("/asset-bookings/<booking_id>/proofs")
@endpoint(["ActivationManager"])
def create_proof(booking_id):
    booking = get_booking_or_404(booking_id)
    body = body_of(request)
    evidence_type = v_enum(body, "evidence_type", EVIDENCE_TYPES)
    measured_value = v_int(body, "measured_value", min_v=0)
    media_uri = v_str(body, "media_uri", required=False, default=None)
    if evidence_type == "PHOTO" and measured_value != 0:
        fail("PHOTO evidence must carry a measured_value of 0.")

    row = new_row()
    row.update({
        "asset_booking_id": booking["id"],
        "evidence_type": evidence_type,
        "measured_value": measured_value,
        "media_uri": media_uri,
        "status": "SUBMITTED",
        "captured_by_user_id": g.user_id,
        "adjudicated_by_user_id": None,
        "reject_reason": None,
    })
    store.proofs[row["id"]] = row

    refresh_booking_evidence(booking)
    return created(proof_out(row))


@bp.get("/asset-bookings/<booking_id>/proofs")
@endpoint(READ_ROLES)
def list_proofs(booking_id):
    booking = get_booking_or_404(booking_id)
    limit, offset = v_pagination(request)
    return paginate(db.proofs_of_booking(booking["id"]), limit, offset, proof_out)


@bp.post("/proofs/<proof_id>/adjudicate")
@endpoint(["PerformanceAuditor"])
def adjudicate_proof(proof_id):
    proof = get_proof_or_404(proof_id)
    body = body_of(request)
    decision = v_enum(body, "decision", DECISIONS)
    reject_reason = v_str(body, "reject_reason", required=False, default=None)
    if decision == "REJECTED" and not reject_reason:
        fail("reject_reason is required when the decision is REJECTED.")

    if proof["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    booking = store.bookings.get(proof["asset_booking_id"])
    if booking is None or booking["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409)

    if g.user_id == proof["captured_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)

    proof["status"] = decision
    proof["adjudicated_by_user_id"] = g.user_id
    if decision == "REJECTED":
        proof["reject_reason"] = reject_reason
    touch(proof)

    refresh_booking_evidence(booking)

    if decision == "REJECTED":
        ent = store.entitlements.get(booking["entitlement_id"])
        contract = db.contract_of_booking(booking)
        if ent is not None:
            rollup_entitlement(ent)
        if contract is not None:
            rollup_contract(contract)
            prop = store.properties.get(contract["property_id"])
            if prop is not None:
                rollup_property(prop)
    return ok(proof_out(proof))
