"""LitigationReferral endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from constants import (
    FILING_WINDOW_DAYS,
    REFERRAL_REASONS,
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_LITIGATION_COUNSEL as LC,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_list, serialize_referral
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("referrals", __name__)

READERS = (LC, RoWA, DD)


@bp.route("/easement-cases/<case_id>/litigation-referrals", methods=["POST"])
@require_roles(RoWA)
def create_referral(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    encroachment_id = require_string(body, "encroachment_id")
    referral_reason = require_enum(body, "referral_reason", REFERRAL_REASONS)

    enc = db.encroachments.get(encroachment_id)
    if enc is None:
        raise_err("ERR_ENCROACHMENT_NOT_FOUND", "encroachment_id does not exist")
    if enc["case_id"] != case_id:
        raise_err("ERR_CROSS_CASE_REFERENCE", "Referenced encroachment belongs to a different case")

    ref = {
        "case_id": case_id,
        "encroachment_id": encroachment_id,
        "referral_reason": referral_reason,
        "referred_by": _user_id,
        "accepted_by": None,
        "filing_deadline": None,
        "status": "REFERRED",
        "_violation_id": None,
        "_offer_id": None,
    }
    db.stamp_new(ref)
    db.referrals[ref["id"]] = ref
    return success_object(serialize_referral(ref), 201)


@bp.route("/easement-cases/<case_id>/litigation-referrals", methods=["GET"])
@require_roles(*READERS)
def list_referrals(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = [r for r in db.referrals.values() if r["case_id"] == case_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_referral), limit, offset, total)


@bp.route("/easement-cases/<case_id>/litigation-referrals/<ref_id>", methods=["GET"])
@require_roles(*READERS)
def get_referral(case_id: str, ref_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    ref = domain.get_referral_or_404(case, ref_id)
    return success_object(serialize_referral(ref))


@bp.route("/easement-cases/<case_id>/litigation-referrals/<ref_id>/accept", methods=["POST"])
@require_roles(LC)
def accept_referral(case_id: str, ref_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    ref = domain.get_referral_or_404(case, ref_id)
    domain.ensure_case_not_closed(case)
    if ref["status"] != "REFERRED":
        raise_err("ERR_INVALID_STATE", "accept requires referral REFERRED")
    ref["status"] = "ACCEPTED"
    ref["accepted_by"] = _user_id
    ref["filing_deadline"] = db.fmt_dt(db.get_clock_dt() + timedelta(days=FILING_WINDOW_DAYS))
    db.touch(ref)
    return success_object(serialize_referral(ref))


@bp.route("/easement-cases/<case_id>/litigation-referrals/<ref_id>/file", methods=["POST"])
@require_roles(LC)
def file_referral(case_id: str, ref_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    ref = domain.get_referral_or_404(case, ref_id)
    domain.ensure_case_not_closed(case)
    if ref["status"] != "ACCEPTED":
        raise_err("ERR_REFERRAL_NOT_ACCEPTED", "Referral must be ACCEPTED to file")
    ref["status"] = "FILED"
    db.touch(ref)
    return success_object(serialize_referral(ref))


def _remove_linked_encroachment(ref: dict) -> None:
    enc_id = ref.get("encroachment_id")
    if not enc_id:
        return
    enc = db.encroachments.get(enc_id)
    if enc is not None and enc["status"] != "REMOVED":
        enc["status"] = "REMOVED"
        db.touch(enc)
        case = db.cases.get(enc["case_id"])
        if case is not None:
            domain.reconcile_case(case)


@bp.route("/easement-cases/<case_id>/litigation-referrals/<ref_id>/settle", methods=["POST"])
@require_roles(LC)
def settle_referral(case_id: str, ref_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    ref = domain.get_referral_or_404(case, ref_id)
    domain.ensure_case_not_closed(case)
    if ref["status"] != "FILED":
        raise_err("ERR_REFERRAL_NOT_FILED", "Referral must be FILED to settle")
    ref["status"] = "SETTLED"
    db.touch(ref)
    if ref["referral_reason"] == "NEGOTIATION_FAILED":
        # Court-brokered removal of the linked encroachment.
        _remove_linked_encroachment(ref)
    # CONDEMNATION settlement: compensation already finalized by the ledger
    # membership rule (the offer left the committed set when it expired or was
    # rejected); the case may proceed toward CLOSED_CONDEMNED via /condemn.
    return success_object(serialize_referral(ref))


@bp.route("/easement-cases/<case_id>/litigation-referrals/<ref_id>/record-judgment", methods=["POST"])
@require_roles(LC)
def record_judgment(case_id: str, ref_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    ref = domain.get_referral_or_404(case, ref_id)
    domain.ensure_case_not_closed(case)
    if ref["status"] != "FILED":
        raise_err("ERR_REFERRAL_NOT_FILED", "Referral must be FILED to record judgment")
    ref["status"] = "JUDGMENT_OBTAINED"
    db.touch(ref)

    reason = ref["referral_reason"]
    if reason == "NEGOTIATION_FAILED":
        _remove_linked_encroachment(ref)
    elif reason == "VEGETATION_REMEDIATION_FAILED":
        viol_id = ref.get("_violation_id")
        viol = db.violations.get(viol_id) if viol_id else None
        if viol is not None and viol["status"] != "REMEDIATED":
            viol["status"] = "REMEDIATED"
            db.touch(viol)
            zone = db.zones.get(viol["zone_id"])
            if zone is not None:
                domain.reconcile_zone(zone)
                db.touch(zone)
    elif reason == "CONDEMNATION":
        if case["status"] not in ("CLOSED_RESOLVED", "CLOSED_CONDEMNED", "CLOSED_ABANDONED"):
            case["status"] = "CLOSED_CONDEMNED"
            db.touch(case)
    return success_object(serialize_referral(ref))


@bp.route("/easement-cases/<case_id>/litigation-referrals/<ref_id>/withdraw", methods=["POST"])
@require_roles(LC)
def withdraw_referral(case_id: str, ref_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    ref = domain.get_referral_or_404(case, ref_id)
    domain.ensure_case_not_closed(case)
    if ref["status"] != "REFERRED":
        raise_err("ERR_INVALID_STATE", "withdraw requires referral REFERRED")
    ref["status"] = "WITHDRAWN"
    db.touch(ref)
    return success_object(serialize_referral(ref))
