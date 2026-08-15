from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import ok, ok_list
from validation import body, opt_str, paginate, parse_date, req_date, req_int, req_str

bp = Blueprint("prior_authorizations", __name__)

ALL_ROLES = ("PbmAdmin", "Pharmacist", "Member", "ClinicalReviewer", "Auditor")


@bp.route("/prior-authorizations", methods=["POST"])
def create_pa():
    uid, _ = require_roles("Member")
    b = body()
    # Pipeline stage 3: the member must name themselves.
    member_id = b.get("member_id")
    if member_id is not None and member_id != uid:
        raise ApiError(
            "ERR_MEMBER_MISMATCH",
            "A member may request a prior authorization only for themselves",
            403,
        )
    # Pipeline stage 4: body FK existence, left to right (member, then drug).
    if member_id is not None and member_id not in db.members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "Member not found", 404)
    drug_id = b.get("drug_id")
    if drug_id is not None and drug_id not in db.drugs:
        raise ApiError("ERR_DRUG_NOT_FOUND", "Drug not found", 404)
    # Pipeline stage 7: request shape.
    if not isinstance(member_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'member_id' is required and must be a string", 400)
    if not isinstance(drug_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'drug_id' is required and must be a string", 400)
    requested_quantity = req_int(b, "requested_quantity", minimum=1)
    note = opt_str(b, "note")
    # Pipeline stage 8: at most one live (PENDING/APPROVED) PA per (member, drug).
    if any(
        p["member_id"] == member_id
        and p["drug_id"] == drug_id
        and p["status"] in ("PENDING", "APPROVED")
        for p in db.prior_authorizations.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_ACTIVE_PA",
            "An active prior authorization already exists for this member and drug",
            409,
        )
    rec = db.base_record()
    rec.update(
        {
            "member_id": member_id,
            "drug_id": drug_id,
            "requested_quantity": requested_quantity,
            "note": note,
            "status": "PENDING",
            "approved_quantity": None,
            "quantity_consumed": 0,
            "expires_at": None,
            "denial_reason": None,
            "decided_by": None,
        }
    )
    db.prior_authorizations[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.route("/prior-authorizations", methods=["GET"])
def list_pas():
    require_roles(*ALL_ROLES)
    rows = list(db.prior_authorizations.values())
    member_id = request.args.get("member_id")
    drug_id = request.args.get("drug_id")
    status = request.args.get("status")
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if drug_id is not None:
        rows = [r for r in rows if r["drug_id"] == drug_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


def get_pa_or_404(pa_id):
    pa = db.prior_authorizations.get(pa_id)
    if pa is None:
        raise ApiError("ERR_PA_NOT_FOUND", "Prior authorization not found", 404)
    return pa


@bp.route("/prior-authorizations/<pa_id>", methods=["GET"])
def get_pa(pa_id):
    require_roles(*ALL_ROLES)
    return ok(db.public(get_pa_or_404(pa_id)), 200)


@bp.route("/prior-authorizations/<pa_id>/approve", methods=["POST"])
def approve_pa(pa_id):
    uid, _ = require_roles("ClinicalReviewer")
    pa = get_pa_or_404(pa_id)
    if pa["status"] != "PENDING":
        raise ApiError("ERR_PA_NOT_PENDING", "Only a PENDING prior authorization can be approved", 409)
    b = body()
    approved_quantity = req_int(b, "approved_quantity", minimum=1)
    expires_at = req_date(b, "expires_at")
    pa["status"] = "APPROVED"
    pa["approved_quantity"] = approved_quantity
    pa["expires_at"] = expires_at
    pa["decided_by"] = uid
    db.touch(pa)
    return ok(db.public(pa), 200)


@bp.route("/prior-authorizations/<pa_id>/deny", methods=["POST"])
def deny_pa(pa_id):
    uid, _ = require_roles("ClinicalReviewer")
    pa = get_pa_or_404(pa_id)
    if pa["status"] != "PENDING":
        raise ApiError("ERR_PA_NOT_PENDING", "Only a PENDING prior authorization can be denied", 409)
    b = body()
    denial_reason = req_str(b, "denial_reason")
    pa["status"] = "DENIED"
    pa["denial_reason"] = denial_reason
    pa["decided_by"] = uid
    db.touch(pa)
    return ok(db.public(pa), 200)
