"""Routes: insurance certificates (PRD §3.6)."""

from flask import Blueprint, g, request

from httpkit import (api_err, as_date, as_enum, as_pos_int, as_str, body_json,
                     get_or_404, req_field, require_roles, respond_object,
                     respond_paginated, sort_created)
from serializers import ser_certificate
from store import db, mutate, new_record

bp = Blueprint("insurance", __name__)


@bp.route("/charter-agreements/<aid>/insurance-certificates", methods=["POST"])
def create_certificate(aid):
    require_roles("CentralAgent")
    agr = get_or_404("charter_agreements", aid, "CharterAgreement")
    if g.user_id != agr["central_agent_id"]:
        raise api_err(
            "ERR_FORBIDDEN", "Caller is not the agreement's central agent"
        )
    # No second filing while one is PENDING or VERIFIED
    if any(
        c["charter_agreement_id"] == agr["id"]
        and c["status"] in ("PENDING", "VERIFIED")
        for c in db["insurance_certificates"].values()
    ):
        raise api_err(
            "ERR_INVALID_STATE",
            "A PENDING or VERIFIED certificate already exists for this agreement",
        )
    body = body_json()
    insurer = as_str(req_field(body, "insurer_name"), "insurer_name")
    policy_no = as_str(req_field(body, "policy_no"), "policy_no")
    coverage = as_pos_int(
        req_field(body, "coverage_amount_cents"), "coverage_amount_cents"
    )
    valid_from = as_date(req_field(body, "valid_from"), "valid_from")
    valid_until = as_date(req_field(body, "valid_until"), "valid_until")
    if valid_from > valid_until:
        raise api_err(
            "ERR_INVALID_REQUEST", "valid_from must be on or before valid_until"
        )
    if coverage < agr["charter_fee_cents"]:
        raise api_err(
            "ERR_INSURANCE_COVERAGE_INSUFFICIENT",
            "Coverage must be at least the agreement's charter fee",
        )
    if valid_from > agr["start_date"] or valid_until < agr["end_date"]:
        raise api_err(
            "ERR_INSURANCE_WINDOW_INVALID",
            "Coverage window must contain the charter window (closed bounds)",
        )
    c = new_record()
    c.update({
        "charter_agreement_id": agr["id"],
        "insurer_name": insurer,
        "policy_no": policy_no,
        "coverage_amount_cents": coverage,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "PENDING",
    })
    db["insurance_certificates"][c["id"]] = c
    return respond_object(ser_certificate(c), 201)


@bp.route("/charter-agreements/<aid>/insurance-certificates", methods=["GET"])
def list_certificates(aid):
    agr = get_or_404("charter_agreements", aid, "CharterAgreement")
    items = [
        c for c in db["insurance_certificates"].values()
        if c["charter_agreement_id"] == agr["id"]
    ]
    v = request.args.get("status")
    if v is not None:
        items = [c for c in items if c["status"] == v]
    return respond_paginated([ser_certificate(c) for c in sort_created(items)])


@bp.route("/insurance-certificates/<cid>/verify", methods=["POST"])
def verify_certificate(cid):
    require_roles("PlatformAdmin")
    c = get_or_404("insurance_certificates", cid, "InsuranceCertificate")
    if c["status"] != "PENDING":
        raise api_err("ERR_INVALID_STATE", "Certificate is not PENDING")
    body = body_json()
    outcome = as_enum(req_field(body, "outcome"), ("VERIFIED", "REJECTED"), "outcome")
    c["status"] = outcome
    mutate(c)
    return respond_object(ser_certificate(c))
