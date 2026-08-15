"""EasementCase endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import (
    CASE_TERMINAL,
    ENCROACHMENT_TERMINAL,
    OFFER_OPEN_STATUSES,
    REFERRAL_PENDING_STATUSES,
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_LITIGATION_COUNSEL as LC,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_TITLE_EXAMINER as TE,
    ROLE_VEGETATION_INSPECTOR as VI,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_case, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("cases", __name__)

ALL = (RoWA, TE, VI, LC, DD)


@bp.route("/easement-cases", methods=["POST"])
@require_roles(RoWA)
def create_case(_user_id: str, _role: str):
    body = get_json_body()
    case_code = require_string(body, "case_code")
    utility_district = require_string(body, "utility_district")
    county = require_string(body, "county")
    parcel_id = require_string(body, "parcel_id")
    easement_width_ft = require_number(body, "easement_width_ft")
    easement_area_sqft = require_number(body, "easement_area_sqft")
    fmv = require_number(body, "fair_market_value_per_sqft")
    budget = require_int(body, "acquisition_budget_cents")

    case = {
        "case_code": case_code,
        "utility_district": utility_district,
        "county": county,
        "parcel_id": parcel_id,
        "easement_width_ft": float(easement_width_ft) if easement_width_ft % 1 else int(easement_width_ft),
        "easement_area_sqft": float(easement_area_sqft) if easement_area_sqft % 1 else int(easement_area_sqft),
        "fair_market_value_per_sqft": float(fmv) if fmv % 1 else int(fmv),
        "acquisition_budget_cents": budget,
        "compensation_committed_cents": 0,
        "compensation_balance_cents": budget,
        "open_encroachment_count": 0,
        "encroachment_pressure_score": 0.0,
        "title_cleared": False,
        "active_permit_count": 0,
        "status": "INTAKE",
    }
    db.stamp_new(case)
    db.cases[case["id"]] = case
    return success_object(serialize_case(case), 201)


@bp.route("/easement-cases", methods=["GET"])
@require_roles(*ALL)
def list_cases(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.cases.values()))
    items = apply_filters(items, ["status", "county"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_case), limit, offset, total)


@bp.route("/easement-cases/<case_id>", methods=["GET"])
@require_roles(*ALL)
def get_case(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    return success_object(serialize_case(case))


@bp.route("/easement-cases/<case_id>/begin-mapping", methods=["POST"])
@require_roles(RoWA)
def begin_mapping(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    if case["status"] != "INTAKE":
        raise_err("ERR_INVALID_STATE", "begin-mapping requires case INTAKE")
    if not any(d["case_id"] == case_id for d in db.documents.values()):
        raise_err("ERR_NO_DOCUMENTS_ON_CASE", "begin-mapping requires at least one document")
    case["status"] = "MAPPING"
    db.touch(case)
    return success_object(serialize_case(case))


@bp.route("/easement-cases/<case_id>/activate-monitoring", methods=["POST"])
@require_roles(RoWA)
def activate_monitoring(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    if case["status"] != "MAPPING":
        raise_err("ERR_INVALID_STATE", "activate-monitoring requires case MAPPING")
    if not any(
        d["case_id"] == case_id and d["status"] == "RECORDED"
        for d in db.documents.values()
    ):
        raise_err("ERR_NO_RECORDED_DOCUMENT", "activate-monitoring requires a RECORDED document")
    from services import calculations
    cleared = calculations.title_cleared(case_id)
    if not cleared:
        raise_err("ERR_TITLE_NOT_CLEARED", "Latest TitleSearchTask is not COMPLETED_CLEAN")
    case["title_cleared"] = True
    case["status"] = "ACTIVE_MONITORING"
    db.touch(case)
    return success_object(serialize_case(case))


@bp.route("/easement-cases/<case_id>/close-case", methods=["POST"])
@require_roles(DD)
def close_case(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    if case["status"] not in ("ACTIVE_MONITORING", "RESOLUTION_PENDING"):
        raise_err("ERR_INVALID_STATE", "close-case requires case ACTIVE_MONITORING")

    # Closure gate (PRD 2.8 step 15), in declared order.
    open_encs = [
        e for e in db.encroachments.values()
        if e["case_id"] == case_id and e["status"] not in ENCROACHMENT_TERMINAL
    ]
    if open_encs:
        raise_err("ERR_OPEN_ENCROACHMENTS_REMAIN", "open_encroachment_count > 0 at case close")
    open_offers = [
        o for o in db.offers.values()
        if o["case_id"] == case_id and o["status"] in OFFER_OPEN_STATUSES
    ]
    if open_offers:
        raise_err("ERR_OPEN_OFFERS_EXIST", "Offer in DRAFT/TENDERED/COUNTERED exists at case close")
    pending_permits = [
        p for p in db.permits.values()
        if p["case_id"] == case_id and p["approval_status"] == "PENDING"
    ]
    if pending_permits:
        raise_err("ERR_PENDING_PERMITS_EXIST", "Permit with approval_status=PENDING exists at case close")
    pending_refs = [
        r for r in db.referrals.values()
        if r["case_id"] == case_id and r["status"] in REFERRAL_PENDING_STATUSES
    ]
    if pending_refs:
        raise_err("ERR_PENDING_LITIGATION_EXISTS", "LitigationReferral in REFERRED/ACCEPTED exists at case close")

    # Side effects: all vegetation zones -> CLEARED; compensation finalized
    # (accepted offers remain committed; everything else already released).
    for zone in db.zones.values():
        if zone["case_id"] == case_id and zone["status"] != "CLEARED":
            zone["status"] = "CLEARED"
            db.touch(zone)
    committed = sum(
        o["total_compensation_cents"]
        for o in db.offers.values()
        if o["case_id"] == case_id and o["status"] == "ACCEPTED"
    )
    case["compensation_committed_cents"] = committed
    case["compensation_balance_cents"] = case["acquisition_budget_cents"] - committed
    case["status"] = "CLOSED_RESOLVED"
    db.touch(case)
    return success_object(serialize_case(case))


@bp.route("/easement-cases/<case_id>/condemn", methods=["POST"])
@require_roles(DD)
def condemn_case(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    if case["status"] != "RESOLUTION_PENDING":
        raise_err("ERR_INVALID_STATE", "condemn requires case RESOLUTION_PENDING")
    if not any(
        o["case_id"] == case_id and o["status"] == "CONDEMNATION_REFERRED"
        for o in db.offers.values()
    ):
        raise_err("ERR_INVALID_STATE", "condemn requires an offer in CONDEMNATION_REFERRED")
    latest = None
    for task in db.title_tasks.values():
        if task["case_id"] != case_id:
            continue
        if latest is None or (task["created_at"], task["_seq"]) > (latest["created_at"], latest["_seq"]):
            latest = task
    if latest is None or latest["status"] not in ("COMPLETED_CLEAN", "COMPLETED_WITH_DEFECTS"):
        raise_err("ERR_TITLE_NOT_CLEARED", "condemn requires a completed title search")

    # Side effects: every still-open encroachment escalates; non-accepted
    # offers release their committed compensation.
    for enc in db.encroachments.values():
        if enc["case_id"] == case_id and enc["status"] not in ENCROACHMENT_TERMINAL:
            enc["status"] = "ESCALATED_TO_LEGAL"
            db.touch(enc)
    case["open_encroachment_count"] = 0
    case["encroachment_pressure_score"] = 0.0
    committed = sum(
        o["total_compensation_cents"]
        for o in db.offers.values()
        if o["case_id"] == case_id and o["status"] == "ACCEPTED"
    )
    case["compensation_committed_cents"] = committed
    case["compensation_balance_cents"] = case["acquisition_budget_cents"] - committed
    case["status"] = "CLOSED_CONDEMNED"
    db.touch(case)
    return success_object(serialize_case(case))


@bp.route("/easement-cases/<case_id>/abandon", methods=["POST"])
@require_roles(DD)
def abandon_case(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    if case["status"] != "INTAKE":
        raise_err("ERR_INVALID_STATE", "abandon requires case INTAKE")
    if any(
        d["case_id"] == case_id and d["status"] == "RECORDED"
        for d in db.documents.values()
    ):
        raise_err("ERR_RECORDED_DOCUMENT_EXISTS", "abandon requires zero RECORDED documents")
    case["status"] = "CLOSED_ABANDONED"
    db.touch(case)
    return success_object(serialize_case(case))
