"""AcquisitionOffer endpoints."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from constants import (
    CASE_RECORDABLE,
    DIRECTOR_APPROVAL_THRESHOLD_CENTS,
    MAX_NEGOTIATION_ROUNDS,
    NEGOTIATION_WINDOW_DAYS,
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_LITIGATION_COUNSEL as LC,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain
from services.serializers import serialize_offer, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_int,
    paginate,
    parse_pagination,
    parse_ts_stored,
    require_int,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("offers", __name__)

READERS = (RoWA, DD, LC)


def _recompute_offer_totals(offer: dict) -> None:
    offer["total_compensation_cents"] = (
        offer["negotiated_compensation_cents"] + offer["severance_damages_cents"]
    )
    offer["requires_director_approval"] = (
        offer["total_compensation_cents"] >= DIRECTOR_APPROVAL_THRESHOLD_CENTS
    )


@bp.route("/easement-cases/<case_id>/offers", methods=["POST"])
@require_roles(RoWA)
def create_offer(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    landowner_name = require_string(body, "landowner_name")
    landowner_contact = require_string(body, "landowner_contact")
    offered_area_sqft = require_number(body, "offered_area_sqft")
    severance = optional_int(body, "severance_damages_cents", 0)

    base = calculations.base_compensation_cents(
        offered_area_sqft, Decimal(str(case["fair_market_value_per_sqft"]))
    )
    offer = {
        "case_id": case_id,
        "landowner_name": landowner_name,
        "landowner_contact": landowner_contact,
        "offered_area_sqft": float(offered_area_sqft) if offered_area_sqft % 1 else int(offered_area_sqft),
        "base_compensation_cents": base,
        "negotiated_compensation_cents": base,
        "severance_damages_cents": severance,
        "total_compensation_cents": 0,
        "negotiation_round": 0,
        "negotiation_deadline": None,
        "requires_director_approval": False,
        "status": "DRAFT",
        "_created_by": _user_id,
    }
    _recompute_offer_totals(offer)
    db.stamp_new(offer)
    db.offers[offer["id"]] = offer
    return success_object(serialize_offer(offer), 201)


@bp.route("/easement-cases/<case_id>/offers", methods=["GET"])
@require_roles(*READERS)
def list_offers(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = [o for o in db.offers.values() if o["case_id"] == case_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_offer), limit, offset, total)


@bp.route("/easement-cases/<case_id>/offers/<offer_id>", methods=["GET"])
@require_roles(*READERS)
def get_offer(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    return success_object(serialize_offer(offer))


@bp.route("/easement-cases/<case_id>/offers/<offer_id>/tender", methods=["POST"])
@require_roles(RoWA)
def tender_offer(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    domain.ensure_case_not_closed(case)
    if case["status"] not in CASE_RECORDABLE:
        raise_err("ERR_CASE_NOT_OPEN_FOR_RECORDING", "Case status not in {MAPPING, ACTIVE_MONITORING, RESOLUTION_PENDING}")
    body = get_json_body()
    domain.check_expected_case_version(case, body)
    if offer["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "tender requires offer DRAFT")
    if not case["title_cleared"]:
        raise_err("ERR_TITLE_NOT_CLEARED", "Latest TitleSearchTask is not COMPLETED_CLEAN or no RECORDED document exists")
    if offer["requires_director_approval"] and offer.get("_created_by") == _user_id:
        raise_err(
            "ERR_NEGOTIATOR_CANNOT_APPROVE_OWN_OFFER",
            "Creator of an offer requiring director approval cannot tender it themselves",
        )
    if offer["total_compensation_cents"] > case["compensation_balance_cents"]:
        raise_err("ERR_COMPENSATION_EXCEEDS_BUDGET", "total_compensation_cents exceeds compensation_balance_cents")

    offer["status"] = "TENDERED"
    offer["negotiation_deadline"] = db.fmt_dt(
        db.get_clock_dt() + timedelta(days=NEGOTIATION_WINDOW_DAYS)
    )
    db.touch(offer)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_offer(offer))


@bp.route("/easement-cases/<case_id>/offers/<offer_id>/counter", methods=["POST"])
@require_roles(RoWA)
def counter_offer(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    counter_amount = require_int(body, "counter_amount_cents")
    if offer["status"] != "TENDERED":
        raise_err("ERR_OFFER_NOT_TENDERED", "Offer must be TENDERED to counter")
    deadline = parse_ts_stored(offer.get("negotiation_deadline"))
    if deadline is not None and db.get_clock_dt() > deadline:
        raise_err("ERR_DEADLINE_PASSED", "negotiation_deadline has passed")
    if offer["negotiation_round"] >= MAX_NEGOTIATION_ROUNDS:
        raise_err("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "negotiation_round has reached MAX_NEGOTIATION_ROUNDS")

    old_total = offer["total_compensation_cents"]
    new_total = counter_amount + offer["severance_damages_cents"]
    committed_after = case["compensation_committed_cents"] - old_total + new_total
    if committed_after > case["acquisition_budget_cents"]:
        raise_err("ERR_COMPENSATION_EXCEEDS_BUDGET", "total_compensation_cents exceeds compensation_balance_cents")

    offer["negotiated_compensation_cents"] = counter_amount
    offer["negotiation_round"] += 1
    _recompute_offer_totals(offer)
    offer["status"] = "COUNTERED"
    db.touch(offer)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_offer(offer))


@bp.route("/easement-cases/<case_id>/offers/<offer_id>/re-tender", methods=["POST"])
@require_roles(RoWA)
def retender_offer(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    new_amount = require_int(body, "new_amount_cents")
    if offer["status"] != "COUNTERED":
        raise_err("ERR_OFFER_NOT_TENDERED", "Offer must be COUNTERED to re-tender")

    old_total = offer["total_compensation_cents"]
    new_total = new_amount + offer["severance_damages_cents"]
    committed_after = case["compensation_committed_cents"] - old_total + new_total
    if committed_after > case["acquisition_budget_cents"]:
        raise_err("ERR_COMPENSATION_EXCEEDS_BUDGET", "total_compensation_cents exceeds compensation_balance_cents")

    offer["negotiated_compensation_cents"] = new_amount
    _recompute_offer_totals(offer)
    offer["status"] = "TENDERED"
    db.touch(offer)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_offer(offer))


@bp.route("/easement-cases/<case_id>/offers/<offer_id>/accept", methods=["POST"])
@require_roles(RoWA, DD)
def accept_offer(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    domain.ensure_case_not_closed(case)
    if offer["status"] not in ("TENDERED", "COUNTERED"):
        raise_err("ERR_OFFER_NOT_TENDERED", "Offer must be TENDERED or COUNTERED to accept")
    if offer["requires_director_approval"] and _role != DD:
        raise_err(
            "ERR_DIRECTOR_APPROVAL_REQUIRED",
            "Offer requires DepartmentDirector acceptance due to compensation threshold",
        )
    offer["status"] = "ACCEPTED"
    db.touch(offer)

    # A new EasementDocument of kind=DEED is auto-created in DRAFT for the
    # acquired strip.
    doc = {
        "case_id": case_id,
        "doc_kind": "DEED",
        "instrument_number": f"AUTO-{offer['id']}",
        "recording_date": db.now_iso(),
        "grantor_name": offer["landowner_name"],
        "grantee_name": "UTILITY",
        "gis_polygon_wkt": "",
        "encumbrance_rank": None,
        "width_ft": case["easement_width_ft"],
        "supersedes_document_id": None,
        "status": "DRAFT",
    }
    db.stamp_new(doc)
    db.documents[doc["id"]] = doc
    return success_object(serialize_offer(offer))


@bp.route("/easement-cases/<case_id>/offers/<offer_id>/reject", methods=["POST"])
@require_roles(RoWA)
def reject_offer(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    domain.ensure_case_not_closed(case)
    if offer["status"] not in ("TENDERED", "COUNTERED"):
        raise_err("ERR_OFFER_NOT_TENDERED", "Offer must be TENDERED or COUNTERED to reject")
    offer["status"] = "REJECTED_BY_OWNER"
    db.touch(offer)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_offer(offer))


@bp.route("/easement-cases/<case_id>/offers/<offer_id>/withdraw", methods=["POST"])
@require_roles(RoWA)
def withdraw_offer(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    domain.ensure_case_not_closed(case)
    if offer["status"] not in ("DRAFT", "TENDERED"):
        raise_err("ERR_INVALID_STATE", "withdraw requires offer DRAFT or TENDERED")
    was_tendered = offer["status"] == "TENDERED"
    offer["status"] = "WITHDRAWN"
    db.touch(offer)
    domain.reconcile_case(case, bump=was_tendered)
    return success_object(serialize_offer(offer))


@bp.route("/easement-cases/<case_id>/offers/<offer_id>/refer-to-condemnation", methods=["POST"])
@require_roles(DD)
def refer_to_condemnation(case_id: str, offer_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    offer = domain.get_offer_or_404(case, offer_id)
    domain.ensure_case_not_closed(case)
    if offer["status"] not in ("EXPIRED", "REJECTED_BY_OWNER"):
        raise_err("ERR_INVALID_STATE", "refer-to-condemnation requires offer EXPIRED or REJECTED_BY_OWNER")
    offer["status"] = "CONDEMNATION_REFERRED"
    db.touch(offer)
    domain.auto_referral(case, "CONDEMNATION", offer_id=offer["id"])
    return success_object(serialize_offer(offer))
