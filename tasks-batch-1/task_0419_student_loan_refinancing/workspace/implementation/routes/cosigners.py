"""Cosigner routes: invite, fetch, list, consent, decline, release.

PRD §3.3 (bringing a cosigner aboard), §3.10 (release).
"""
from decimal import Decimal

from flask import Blueprint, request

import calc
import db
import serialize
from auth import authorize
from errors import err
from response import object_response, array_response
from store_helpers import get_or_404, sorted_by_created, paginate, append_audit
from validate import (
    get_json_body,
    require_str,
    require_nonneg_int,
    parse_pagination,
)

bp = Blueprint("cosigners", __name__)


def _recompute_dti_with_cosigner(app, borrower, cosigner):
    """with-cosigner DTI variant (PRD §3.3)."""
    combined = borrower["annual_income_cents"] + cosigner["cosigner_annual_income_cents"]
    ratio = calc.dti_ratio(
        app["requested_principal_cents"],
        app["requested_term_months"],
        combined,
    )
    app["dti_ratio"] = float(ratio)
    db.touch(app)


@bp.route("/cosigners", methods=["POST"])
def invite_cosigner():
    authorize(("POST", "/cosigners"))
    body = get_json_body()
    application_id = require_str(body, "application_id")
    cosigner_email = require_str(body, "cosigner_email")
    cosigner_annual_income_cents = require_nonneg_int(body, "cosigner_annual_income_cents")

    with db.lock():
        get_or_404(db.applications, application_id)
        # At most one cosigner per application (PRD §3.3).
        for c in db.cosigners.values():
            if c["application_id"] == application_id:
                raise err("ERR_COSIGNER_ALREADY_ATTACHED", "application already has a cosigner")
        record = {
            "application_id": application_id,
            "cosigner_email": cosigner_email,
            "cosigner_annual_income_cents": cosigner_annual_income_cents,
            "consent_status": "INVITED",
            "on_time_streak": 0,
        }
        db.stamp_create(record)
        db.cosigners[record["id"]] = record
    return object_response(serialize.cosigner(record), 201)


@bp.route("/cosigners/<rid>", methods=["GET"])
def get_cosigner(rid):
    authorize(("GET", "/cosigners/{id}"))
    record = get_or_404(db.cosigners, rid)
    return object_response(serialize.cosigner(record), 200)


@bp.route("/cosigners", methods=["GET"])
def list_cosigners():
    authorize(("GET", "/cosigners"))
    limit, offset = parse_pagination()
    f_app = request.args.get("application_id")
    records = list(db.cosigners.values())
    if f_app is not None:
        records = [r for r in records if r["application_id"] == f_app]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.cosigner(r) for r in page], limit, offset, total)


@bp.route("/cosigners/<rid>/consent", methods=["POST"])
def consent(rid):
    user_id, role = authorize(("POST", "/cosigners/{id}/consent"))
    with db.lock():
        cosigner = get_or_404(db.cosigners, rid)
        app = get_or_404(db.applications, cosigner["application_id"])
        # Defined only from INVITED and only while parent in DRAFT/PREQUALIFIED.
        if cosigner["consent_status"] != "INVITED" or app["status"] not in {"DRAFT", "PREQUALIFIED"}:
            raise err("ERR_INVALID_STATE", "consent not permitted in current state")
        cosigner["consent_status"] = "CONSENTED"
        db.touch(cosigner)
        # Recompute parent DTI with cosigner income (with-cosigner variant).
        borrower = db.borrowers[app["borrower_id"]]
        _recompute_dti_with_cosigner(app, borrower, cosigner)
        append_audit("COSIGNER", cosigner["id"], "COSIGNER_CONSENTED", role, user_id)
    return object_response(serialize.cosigner(cosigner), 200)


@bp.route("/cosigners/<rid>/decline", methods=["POST"])
def decline(rid):
    user_id, role = authorize(("POST", "/cosigners/{id}/decline"))
    with db.lock():
        cosigner = get_or_404(db.cosigners, rid)
        # Defined only from INVITED (PRD §3.3).
        if cosigner["consent_status"] != "INVITED":
            raise err("ERR_INVALID_STATE", "decline only from INVITED")
        cosigner["consent_status"] = "DECLINED"
        db.touch(cosigner)
        append_audit("COSIGNER", cosigner["id"], "COSIGNER_DECLINED", role, user_id)
    return object_response(serialize.cosigner(cosigner), 200)


@bp.route("/cosigners/<rid>/release", methods=["POST"])
def release(rid):
    user_id, role = authorize(("POST", "/cosigners/{id}/release"))
    with db.lock():
        cosigner = get_or_404(db.cosigners, rid)
        # Release defined only when consent_status == CONSENTED (state) (PRD §3.10).
        if cosigner["consent_status"] != "CONSENTED":
            raise err("ERR_INVALID_STATE", "release only from CONSENTED")
        # The funded loan for this application must be ELIGIBLE.
        loan = None
        for ln in db.loans.values():
            if ln["application_id"] == cosigner["application_id"]:
                loan = ln
                break
        if loan is None or loan["cosigner_release_status"] != "ELIGIBLE":
            raise err("ERR_RELEASE_NOT_ELIGIBLE", "loan is not release-eligible")
        cosigner["consent_status"] = "RELEASED"
        db.touch(cosigner)
        loan["cosigner_release_status"] = "RELEASED"
        db.touch(loan)
        append_audit("COSIGNER", cosigner["id"], "COSIGNER_RELEASED", role, user_id)
    return object_response(serialize.cosigner(cosigner), 200)
