"""Flat filtered-list / by-id GET endpoints directly under /easement-cases
(PRD 2.9) — alternative access paths to the nested sub-resources."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import (
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_LITIGATION_COUNSEL as LC,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_TITLE_EXAMINER as TE,
    ROLE_VEGETATION_INSPECTOR as VI,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services.serializers import (
    serialize_document,
    serialize_encroachment,
    serialize_list,
    serialize_offer,
    serialize_permit,
    serialize_referral,
    serialize_task,
    serialize_violation,
    serialize_zone,
)
from util import apply_filters, paginate, parse_pagination, sort_by_created_at

bp = Blueprint("flat", __name__)

DOC_READERS = (RoWA, TE, LC, DD)
ENC_READERS = (RoWA, VI, LC, DD)
OFFER_READERS = (RoWA, DD, LC)
PERMIT_READERS = (RoWA, VI, DD)
ZONE_READERS = (VI, RoWA, DD)
TASK_READERS = (TE, RoWA, DD)
REF_READERS = (LC, RoWA, DD)


def _flat_get(store: dict, entity_id: str, error_id: str):
    entity = store.get(entity_id)
    if entity is None:
        raise_err(error_id, f"Resource {entity_id} does not exist")
    return entity


def _flat_list(store: dict, filters: list[str]):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(store.values()))
    items = apply_filters(items, filters)
    page, total = paginate(items, limit, offset)
    return page, total, limit, offset


# --- documents ---
@bp.route("/easement-cases/documents/<doc_id>", methods=["GET"])
@require_roles(*DOC_READERS)
def flat_get_document(doc_id: str, _user_id: str, _role: str):
    return success_object(serialize_document(_flat_get(db.documents, doc_id, "ERR_DOCUMENT_NOT_FOUND")))


@bp.route("/easement-cases/documents", methods=["GET"])
@require_roles(*DOC_READERS)
def flat_list_documents(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(
        db.documents, ["case_id", "supersedes_document_id", "status", "doc_kind"]
    )
    return success_list(serialize_list(page, serialize_document), limit, offset, total)


# --- encroachments ---
@bp.route("/easement-cases/encroachments/<enc_id>", methods=["GET"])
@require_roles(*ENC_READERS)
def flat_get_encroachment(enc_id: str, _user_id: str, _role: str):
    return success_object(serialize_encroachment(_flat_get(db.encroachments, enc_id, "ERR_ENCROACHMENT_NOT_FOUND")))


@bp.route("/easement-cases/encroachments", methods=["GET"])
@require_roles(*ENC_READERS)
def flat_list_encroachments(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(
        db.encroachments, ["case_id", "encroaches_document_id", "status", "severity_tier"]
    )
    return success_list(serialize_list(page, serialize_encroachment), limit, offset, total)


# --- offers ---
@bp.route("/easement-cases/offers/<offer_id>", methods=["GET"])
@require_roles(*OFFER_READERS)
def flat_get_offer(offer_id: str, _user_id: str, _role: str):
    return success_object(serialize_offer(_flat_get(db.offers, offer_id, "ERR_OFFER_NOT_FOUND")))


@bp.route("/easement-cases/offers", methods=["GET"])
@require_roles(*OFFER_READERS)
def flat_list_offers(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(db.offers, ["case_id", "status"])
    return success_list(serialize_list(page, serialize_offer), limit, offset, total)


# --- permits ---
@bp.route("/easement-cases/permits/<permit_id>", methods=["GET"])
@require_roles(*PERMIT_READERS)
def flat_get_permit(permit_id: str, _user_id: str, _role: str):
    return success_object(serialize_permit(_flat_get(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")))


@bp.route("/easement-cases/permits", methods=["GET"])
@require_roles(*PERMIT_READERS)
def flat_list_permits(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(
        db.permits, ["case_id", "encroachment_id", "approval_status", "permit_type"]
    )
    return success_list(serialize_list(page, serialize_permit), limit, offset, total)


# --- vegetation zones ---
@bp.route("/easement-cases/vegetation-zones/<zone_id>", methods=["GET"])
@require_roles(*ZONE_READERS)
def flat_get_zone(zone_id: str, _user_id: str, _role: str):
    return success_object(serialize_zone(_flat_get(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")))


@bp.route("/easement-cases/vegetation-zones", methods=["GET"])
@require_roles(*ZONE_READERS)
def flat_list_zones(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(db.zones, ["case_id", "status"])
    return success_list(serialize_list(page, serialize_zone), limit, offset, total)


# --- violations ---
@bp.route("/easement-cases/violations/<viol_id>", methods=["GET"])
@require_roles(*ZONE_READERS)
def flat_get_violation(viol_id: str, _user_id: str, _role: str):
    return success_object(serialize_violation(_flat_get(db.violations, viol_id, "ERR_VIOLATION_NOT_FOUND")))


@bp.route("/easement-cases/violations", methods=["GET"])
@require_roles(*ZONE_READERS)
def flat_list_violations(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(db.violations, ["zone_id", "case_id", "status"])
    return success_list(serialize_list(page, serialize_violation), limit, offset, total)


# --- title searches ---
@bp.route("/easement-cases/title-searches/<task_id>", methods=["GET"])
@require_roles(*TASK_READERS)
def flat_get_task(task_id: str, _user_id: str, _role: str):
    return success_object(serialize_task(_flat_get(db.title_tasks, task_id, "ERR_TITLE_TASK_NOT_FOUND")))


@bp.route("/easement-cases/title-searches", methods=["GET"])
@require_roles(*TASK_READERS)
def flat_list_tasks(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(db.title_tasks, ["case_id", "status"])
    return success_list(serialize_list(page, serialize_task), limit, offset, total)


# --- litigation referrals ---
@bp.route("/easement-cases/litigation-referrals/<ref_id>", methods=["GET"])
@require_roles(*REF_READERS)
def flat_get_referral(ref_id: str, _user_id: str, _role: str):
    return success_object(serialize_referral(_flat_get(db.referrals, ref_id, "ERR_REFERRAL_NOT_FOUND")))


@bp.route("/easement-cases/litigation-referrals", methods=["GET"])
@require_roles(*REF_READERS)
def flat_list_referrals(_user_id: str, _role: str):
    page, total, limit, offset = _flat_list(
        db.referrals, ["case_id", "encroachment_id", "status"]
    )
    return success_list(serialize_list(page, serialize_referral), limit, offset, total)
