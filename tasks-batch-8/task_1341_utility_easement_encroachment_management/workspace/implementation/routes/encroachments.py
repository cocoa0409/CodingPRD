"""Encroachment endpoints."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from constants import (
    CASE_MONITORING,
    DISCOVERED_VIA,
    ENCROACHMENT_TYPES,
    MAX_NEGOTIATION_ROUNDS,
    OWNER_RESPONSE_WINDOW_DAYS,
    REMEDIATION_WINDOW_DAYS,
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_LITIGATION_COUNSEL as LC,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_VEGETATION_INSPECTOR as VI,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain
from services.serializers import serialize_encroachment, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("encroachments", __name__)

READERS = (RoWA, VI, LC, DD)


@bp.route("/easement-cases/<case_id>/encroachments", methods=["POST"])
@require_roles(RoWA)
def create_encroachment(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    discovered_via = require_enum(body, "discovered_via", DISCOVERED_VIA)
    encroachment_type = require_enum(body, "encroachment_type", ENCROACHMENT_TYPES)
    area_sqft = require_number(body, "encroachment_area_sqft")
    depth_ft = require_number(body, "depth_into_easement_ft")
    encroaches_document_id = require_string(body, "encroaches_document_id")
    removal_cost = require_int(body, "estimated_removal_cost_cents")

    # Referenced document: must exist, belong to this case, be RECORDED.
    doc = db.documents.get(encroaches_document_id)
    if doc is None:
        raise_err("ERR_DOCUMENT_NOT_FOUND", "encroaches_document_id does not exist")
    if doc["case_id"] != case_id:
        raise_err("ERR_CROSS_CASE_REFERENCE", "Referenced document belongs to a different case")
    if doc["status"] != "RECORDED":
        raise_err("ERR_DOCUMENT_NOT_RECORDED", "encroaches_document_id must be RECORDED")

    tier = calculations.severity_tier(
        encroachment_type,
        area_sqft,
        depth_ft,
        Decimal(str(doc["width_ft"])),
        Decimal(str(case["easement_area_sqft"])),
    )

    enc = {
        "case_id": case_id,
        "discovered_via": discovered_via,
        "encroachment_type": encroachment_type,
        "encroachment_area_sqft": float(area_sqft) if area_sqft % 1 else int(area_sqft),
        "depth_into_easement_ft": float(depth_ft) if depth_ft % 1 else int(depth_ft),
        "encroaches_document_id": encroaches_document_id,
        "severity_tier": tier,
        "estimated_removal_cost_cents": removal_cost,
        "owner_response_due_date": None,
        "negotiation_round": 0,
        "status": "DISCOVERED",
    }
    db.stamp_new(enc)
    db.encroachments[enc["id"]] = enc

    # Arrival reconciles the case (count, pressure, monitoring pull).
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_encroachment(enc), 201)


@bp.route("/easement-cases/<case_id>/encroachments", methods=["GET"])
@require_roles(*READERS)
def list_encroachments(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = [e for e in db.encroachments.values() if e["case_id"] == case_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status", "severity_tier"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_encroachment), limit, offset, total)


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>", methods=["GET"])
@require_roles(*READERS)
def get_encroachment(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/notify", methods=["POST"])
@require_roles(RoWA)
def notify_encroachment(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if case["status"] not in CASE_MONITORING:
        raise_err("ERR_CASE_NOT_MONITORING", "Case status not in {ACTIVE_MONITORING, RESOLUTION_PENDING}")
    body = get_json_body()
    domain.check_expected_case_version(case, body)
    if enc["status"] != "DISCOVERED":
        raise_err("ERR_INVALID_STATE", "notify requires encroachment DISCOVERED")
    enc["status"] = "NOTIFIED"
    enc["owner_response_due_date"] = db.fmt_dt(
        db.get_clock_dt() + timedelta(days=OWNER_RESPONSE_WINDOW_DAYS)
    )
    db.touch(enc)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/begin-negotiation", methods=["POST"])
@require_roles(RoWA)
def begin_negotiation(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if enc["status"] != "NOTIFIED":
        raise_err("ERR_INVALID_STATE", "begin-negotiation requires encroachment NOTIFIED")
    enc["status"] = "NEGOTIATING"
    enc["negotiation_round"] = 1
    db.touch(enc)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/counter", methods=["POST"])
@require_roles(RoWA)
def counter_encroachment(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if enc["status"] != "NEGOTIATING":
        raise_err("ERR_INVALID_STATE", "counter requires encroachment NEGOTIATING")
    if enc["negotiation_round"] >= MAX_NEGOTIATION_ROUNDS:
        raise_err("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "negotiation_round has reached MAX_NEGOTIATION_ROUNDS")
    enc["status"] = "COUNTERED"
    enc["negotiation_round"] += 1
    db.touch(enc)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/resume-negotiation", methods=["POST"])
@require_roles(RoWA)
def resume_negotiation(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if enc["status"] != "COUNTERED":
        raise_err("ERR_INVALID_STATE", "resume-negotiation requires encroachment COUNTERED")
    enc["status"] = "NEGOTIATING"
    db.touch(enc)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/agree-removal", methods=["POST"])
@require_roles(RoWA)
def agree_removal(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if enc["status"] not in ("NEGOTIATING", "COUNTERED"):
        raise_err("ERR_ENCROACHMENT_NOT_NEGOTIATING", "Encroachment must be NEGOTIATING or COUNTERED")
    enc["status"] = "REMOVAL_AGREED"
    db.touch(enc)
    # VEGETATION encroachments advance linked violations on the case.
    if enc["encroachment_type"] == "VEGETATION":
        deadline = db.fmt_dt(db.get_clock_dt() + timedelta(days=REMEDIATION_WINDOW_DAYS))
        for viol in db.violations.values():
            if viol["case_id"] == case_id and viol["status"] == "DETECTED":
                viol["status"] = "NOTIFIED"
                viol["remediation_deadline"] = deadline
                db.touch(viol)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/confirm-removal", methods=["POST"])
@require_roles(RoWA)
def confirm_removal(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if case["status"] not in CASE_MONITORING:
        raise_err("ERR_CASE_NOT_MONITORING", "Case status not in {ACTIVE_MONITORING, RESOLUTION_PENDING}")
    if enc["status"] != "REMOVAL_AGREED":
        raise_err("ERR_INVALID_STATE", "confirm-removal requires encroachment REMOVAL_AGREED")
    enc["status"] = "REMOVED"
    db.touch(enc)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/escalate", methods=["POST"])
@require_roles(RoWA)
def escalate_encroachment(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if enc["status"] not in ("NEGOTIATING", "COUNTERED"):
        raise_err("ERR_ENCROACHMENT_NOT_NEGOTIATING", "Encroachment must be NEGOTIATING or COUNTERED")
    if enc["negotiation_round"] < MAX_NEGOTIATION_ROUNDS:
        raise_err(
            "ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED",
            "Escalation requires negotiation_round >= MAX_NEGOTIATION_ROUNDS",
        )
    enc["status"] = "ESCALATED_TO_LEGAL"
    db.touch(enc)
    domain.auto_referral(case, "NEGOTIATION_FAILED", encroachment_id=enc["id"])
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_encroachment(enc))


@bp.route("/easement-cases/<case_id>/encroachments/<enc_id>/waive", methods=["POST"])
@require_roles(DD)
def waive_encroachment(case_id: str, enc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    enc = domain.get_encroachment_or_404(case, enc_id)
    domain.ensure_case_not_closed(case)
    if enc["status"] != "NEGOTIATING":
        raise_err("ERR_INVALID_STATE", "waive requires encroachment NEGOTIATING")
    if enc["severity_tier"] != "MINOR":
        raise_err("ERR_ONLY_MINOR_WAIVABLE", "Only encroachments with severity_tier=MINOR can be waived")
    enc["status"] = "WAIVED"
    db.touch(enc)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_encroachment(enc))
