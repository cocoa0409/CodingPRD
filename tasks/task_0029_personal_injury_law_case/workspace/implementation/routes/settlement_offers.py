"""Settlement-offer routes (PRD §3.5, §3.6)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from db import (
    settlement_offers, cases, medical_liens, stamp_common, bump,
)
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_CROSS_ENTITY_STATE,
    ERR_INVALID_COUNTER,
    ERR_DISPUTED_LIEN_BLOCKS_SETTLEMENT,
    ERR_STALE_CASE_VERSION,
    ERR_FK_NOT_FOUND,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_str, require_int, require_enum,
    get_or_404_path, get_or_fk_404,
    assert_sol_not_expired,
)
from services.cascades import (
    cascade_case_to_in_negotiation,
    cascade_case_to_settled,
    expire_pending_offers,
)


bp = Blueprint("settlement_offers", __name__)


VALID_BY_PARTY = {"CARRIER", "FIRM"}


def _view(o: dict) -> dict:
    return {
        "id": o["id"],
        "case_id": o["case_id"],
        "offer_amount_cents": o["offer_amount_cents"],
        "by_party": o["by_party"],
        "counter_to_offer_id": o.get("counter_to_offer_id"),
        "round_number": o["round_number"],
        "status": o["status"],
        "responded_at": o.get("responded_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.post("/settlement-offers")
def create_offer():
    require_auth({"Attorney"})()
    body = get_json_body()
    case_id = require_str(body, "case_id")
    offer_amount = require_int(body, "offer_amount_cents", min_value=0)
    by_party = require_enum(body, "by_party", VALID_BY_PARTY)
    counter_to = body.get("counter_to_offer_id")

    case = get_or_fk_404(cases, case_id, "Case")

    # If counter_to provided, that prior offer must exist.
    prior = None
    if counter_to is not None:
        if not isinstance(counter_to, str):
            raise APIError(ERR_FK_NOT_FOUND, 404,
                           "counter_to_offer_id must reference an existing offer")
        prior = settlement_offers.get(counter_to)
        if prior is None:
            raise APIError(ERR_FK_NOT_FOUND, 404,
                           f"SettlementOffer not found: {counter_to}")

    # Validate state of case for offer creation. PRD §3.5:
    #   * First offer on a case requires DEMAND_SENT — produces transition to
    #     IN_NEGOTIATION.
    #   * Counters allowed only while case is IN_NEGOTIATION or LITIGATION.
    if prior is None:
        # Opening offer
        if case["status"] != "DEMAND_SENT":
            raise APIError(
                ERR_CROSS_ENTITY_STATE, 409,
                "First settlement offer requires Case.status == DEMAND_SENT",
            )
    else:
        # Counter offer — must be on same case, prior PENDING, opposite party.
        if prior["case_id"] != case_id:
            raise APIError(ERR_INVALID_COUNTER, 422,
                           "counter_to_offer_id is on a different case")
        if prior["status"] != "PENDING":
            raise APIError(ERR_INVALID_COUNTER, 422,
                           "counter_to_offer_id must reference a PENDING offer")
        if prior["by_party"] == by_party:
            raise APIError(ERR_INVALID_COUNTER, 422,
                           "Counter must be by the opposite party")
        if case["status"] not in ("IN_NEGOTIATION", "LITIGATION"):
            raise APIError(
                ERR_CROSS_ENTITY_STATE, 409,
                "Counter offers require Case.status IN_NEGOTIATION or LITIGATION",
            )

    # Build the new offer.
    round_number = 1 if prior is None else int(prior["round_number"]) + 1
    new_offer = {
        "case_id": case_id,
        "offer_amount_cents": offer_amount,
        "by_party": by_party,
        "counter_to_offer_id": counter_to,
        "round_number": round_number,
        "status": "PENDING",
        "responded_at": None,
    }
    stamp_common(new_offer)
    settlement_offers[new_offer["id"]] = new_offer

    # If countering, prior offer transitions PENDING -> COUNTERED.
    if prior is not None:
        prior["status"] = "COUNTERED"
        prior["responded_at"] = db.get_current_utc()
        bump(prior)

    # First-offer cascade: case DEMAND_SENT -> IN_NEGOTIATION (per PRD §3.5).
    # The "first offer on the case" detector counts every settlement offer
    # (including this newly inserted row); if this row is the only one, it's
    # the first.
    case_offers = [o for o in settlement_offers.values() if o["case_id"] == case_id]
    if len(case_offers) == 1 and prior is None and case["status"] == "DEMAND_SENT":
        cascade_case_to_in_negotiation(case)

    return ok_object(_view(new_offer), 201)


@bp.get("/settlement-offers/<oid>")
def get_offer(oid):
    require_auth({"Attorney", "ManagingPartner", "Paralegal"})()
    o = get_or_404_path(settlement_offers, oid, "SettlementOffer")
    return ok_object(_view(o), 200)


@bp.get("/settlement-offers")
def list_offers():
    require_auth({"Attorney", "ManagingPartner", "Paralegal"})()
    limit, offset = paginate_params(request.args)
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    by_party = request.args.get("by_party")
    counter_to = request.args.get("counter_to_offer_id")
    items = list(settlement_offers.values())
    if case_id is not None:
        items = [o for o in items if o["case_id"] == case_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if by_party is not None:
        items = [o for o in items if o["by_party"] == by_party]
    if counter_to is not None:
        items = [o for o in items if o.get("counter_to_offer_id") == counter_to]
    items.sort(key=lambda o: o["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(o) for o in page], limit, offset, total, 200)


@bp.post("/settlement-offers/<oid>/accept")
def accept(oid):
    require_auth({"ManagingPartner"})()
    o = get_or_404_path(settlement_offers, oid, "SettlementOffer")
    if o["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Offer must be PENDING to accept")
    case = cases.get(o["case_id"])
    if case is None:
        raise APIError(ERR_INVALID_STATE, 409, "Parent case not found")
    if case["status"] not in ("IN_NEGOTIATION", "LITIGATION"):
        raise APIError(
            ERR_CROSS_ENTITY_STATE, 409,
            "Case must be IN_NEGOTIATION or LITIGATION to accept",
        )
    # SOL check (priority 7).
    assert_sol_not_expired(case)
    # Disputed lien check (priority 18).
    for l in medical_liens.values():
        if l["case_id"] == case["id"] and l["status"] == "DISPUTED":
            raise APIError(
                ERR_DISPUTED_LIEN_BLOCKS_SETTLEMENT, 422,
                "A MedicalLien on this case is DISPUTED; cannot accept",
            )
    # OCC (priority 19).
    body = get_json_body()
    expected_v = body.get("expected_case_version")
    if expected_v is None or isinstance(expected_v, bool) or not isinstance(expected_v, int):
        raise APIError(ERR_INVALID_REQUEST, 400,
                       "expected_case_version (integer) is required")
    if expected_v != int(case["version"]):
        raise APIError(
            ERR_STALE_CASE_VERSION, 412,
            f"expected_case_version {expected_v} does not match {case['version']}",
        )

    # Transition offer
    o["status"] = "ACCEPTED"
    o["responded_at"] = db.get_current_utc()
    bump(o)
    # Cascade case to SETTLED with full lien/court/disbursement cascade.
    cascade_case_to_settled(case, o)
    return ok_object(_view(o), 200)


@bp.post("/settlement-offers/<oid>/reject")
def reject(oid):
    require_auth({"ManagingPartner"})()
    o = get_or_404_path(settlement_offers, oid, "SettlementOffer")
    if o["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Offer must be PENDING to reject")
    o["status"] = "REJECTED"
    o["responded_at"] = db.get_current_utc()
    bump(o)
    return ok_object(_view(o), 200)
