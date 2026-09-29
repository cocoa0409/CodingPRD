"""Interconnection agreement negotiation and lifecycle (PRD 3.1, 3.2)."""
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE,
                  INTERCONNECTION_MANAGER, NETWORK_PLANNER, PLATFORM_ADMIN,
                  REVENUE_ASSURANCE_CONTROLLER, authenticate,
                  carrier_of_offer, check_agreement_version, scope_check,
                  scope_filter)
from constants import (AGREEMENT_TERM_MAX_MONTHS, AGREEMENT_TERM_MIN_MONTHS,
                       BILL_AND_KEEP_RATIO_CEILING, BILL_AND_KEEP_RATIO_FLOOR,
                       MAX_NEGOTIATION_ROUNDS, OFFER_TYPES,
                       POI_FINANCIAL_RESPONSIBILITIES,
                       RECIPROCAL_RATE_CAP_PER_MOU_USD)
from dec import q2, q4
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_agreement, get_carrier, get_offer
from services.sizing import recompute_posture
from services.tariff import effective_filing_for
from store import base_record, db, now, ordered, touch

bp = Blueprint("agreements", __name__)

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")


def standing_offer(agreement_id):
    for offer in ordered(db.offers):
        if offer["agreement_id"] == agreement_id and offer["status"] == "OPEN":
            return offer
    return None


def acting_party(role):
    return "CLEC_SIDE" if role == INTERCONNECTION_MANAGER else "COUNTERPARTY_SIDE"


@bp.post("/agreements")
def open_agreement():
    authenticate((INTERCONNECTION_MANAGER,))
    payload = v.body()
    carrier_id = v.string(payload, "carrier_id")
    agreement_label = v.string(payload, "agreement_label")
    proposed_rate = v.number(payload, "proposed_reciprocal_rate_per_mou_usd", 6, gt=0)
    proposed_term_months = v.integer(payload, "proposed_term_months",
                                     ge=AGREEMENT_TERM_MIN_MONTHS,
                                     le=AGREEMENT_TERM_MAX_MONTHS)
    transit_traffic_allowed = v.boolean(payload, "transit_traffic_allowed",
                                        required=False, default=False)
    effective_date = v.timestamp(payload, "effective_date")
    capacity = v.integer(payload, "poi_facility_capacity_trunks", ge=24,
                         multiple_of=24)

    carrier = get_carrier(carrier_id)

    for existing in db.agreements.values():
        if (existing["carrier_id"] == carrier["id"]
                and existing["agreement_label"] == agreement_label):
            raise ApiError("ERR_DUPLICATE_AGREEMENT_LABEL",
                           "agreement_label is already used for this carrier")

    agreement = base_record()
    agreement.update({
        "carrier_id": carrier["id"],
        "agreement_label": agreement_label,
        "status": "DRAFT",
        "proposed_reciprocal_rate_per_mou_usd": proposed_rate,
        "proposed_term_months": proposed_term_months,
        "transit_traffic_allowed": transit_traffic_allowed,
        "effective_date": effective_date,
        "reciprocal_rate_per_mou_usd": None,
        "term_months": None,
        "poi_financial_responsibility": None,
        "poi_facility_capacity_trunks": capacity,
        "negotiation_round": 0,
        "capacity_posture": "NORMAL",
        "poi_augment_pending_count": 0,
        "total_in_service_trunks": 0,
        "executed_at": None,
        "terminated_at": None,
    })
    db.agreements[agreement["id"]] = agreement
    return object_response(agreement, 201)


@bp.get("/agreements/<agreement_id>")
def read_agreement(agreement_id):
    actor = authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER, NETWORK_PLANNER,
                          ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE))
    agreement = get_agreement(agreement_id)
    scope_check(actor, agreement["carrier_id"])
    return object_response(agreement)


@bp.get("/agreements")
def list_agreements():
    authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER, NETWORK_PLANNER,
                  ACCESS_BILLING_ANALYST, REVENUE_ASSURANCE_CONTROLLER))
    rows = ordered(db.agreements)
    carrier_id = request.args.get("carrier_id")
    if carrier_id:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    posture = request.args.get("capacity_posture")
    if posture:
        rows = [r for r in rows if r["capacity_posture"] == posture]
    return paginate(rows, request.args, lambda r: r)


@bp.post("/agreements/<agreement_id>/offers")
def append_offer(agreement_id):
    actor = authenticate((INTERCONNECTION_MANAGER, CARRIER_REPRESENTATIVE))
    agreement = get_agreement(agreement_id)
    payload = v.body()
    expected_version = v.integer(payload, "expected_agreement_version")
    offer_type = v.enum(payload, "offer_type", OFFER_TYPES)
    rate = v.number(payload, "reciprocal_rate_per_mou_usd", 6, gt=0)
    term_months = v.integer(payload, "term_months", ge=AGREEMENT_TERM_MIN_MONTHS,
                            le=AGREEMENT_TERM_MAX_MONTHS)
    responsibility = v.enum(payload, "poi_financial_responsibility",
                            POI_FINANCIAL_RESPONSIBILITIES)
    transit = v.boolean(payload, "transit_traffic_allowed")

    scope_check(actor, agreement["carrier_id"])
    check_agreement_version(agreement, expected_version)

    if agreement["status"] not in ("DRAFT", "PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "offers may only be appended while the agreement is under negotiation")

    if rate > RECIPROCAL_RATE_CAP_PER_MOU_USD:
        raise ApiError("ERR_RECIPROCAL_RATE_CAP_EXCEEDED",
                       "reciprocal rate exceeds the regulatory cap")

    round_number = agreement["negotiation_round"] + 1
    if round_number > MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT",
                       "the negotiation round limit has been reached")

    party = acting_party(actor.role)
    standing = standing_offer(agreement["id"])
    if agreement["status"] == "DRAFT":
        if offer_type != "PROPOSAL" or party != "CLEC_SIDE":
            raise ApiError("ERR_OFFER_PARTY_SEQUENCE",
                           "the first offer must be a PROPOSAL from the CLEC side")
    else:
        if standing is not None and standing["offering_party"] == party:
            raise ApiError("ERR_OFFER_PARTY_SEQUENCE",
                           "a party may not counter its own standing offer")

    if standing is not None:
        standing["status"] = "SUPERSEDED"
        standing["responded_at"] = now()

    offer = base_record(with_version=False)
    offer.update({
        "agreement_id": agreement["id"],
        "round_number": round_number,
        "offering_party": party,
        "offer_type": offer_type,
        "reciprocal_rate_per_mou_usd": rate,
        "term_months": term_months,
        "poi_financial_responsibility": responsibility,
        "transit_traffic_allowed": transit,
        "status": "OPEN",
        "responded_at": None,
    })
    db.offers[offer["id"]] = offer

    agreement["negotiation_round"] = round_number
    agreement["status"] = "PROPOSED" if party == "CLEC_SIDE" else "COUNTERED"
    touch(agreement)
    return object_response(offer, 201)


@bp.get("/agreements/<agreement_id>/offers")
def list_agreement_offers(agreement_id):
    actor = authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER,
                          CARRIER_REPRESENTATIVE))
    agreement = get_agreement(agreement_id)
    scope_check(actor, agreement["carrier_id"])
    rows = [o for o in ordered(db.offers) if o["agreement_id"] == agreement["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/negotiation-offers/<offer_id>")
def read_offer(offer_id):
    actor = authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER,
                          CARRIER_REPRESENTATIVE))
    offer = get_offer(offer_id)
    scope_check(actor, carrier_of_offer(offer))
    return object_response(offer)


@bp.get("/negotiation-offers")
def list_offers():
    actor = authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER,
                          CARRIER_REPRESENTATIVE))
    rows = ordered(db.offers)
    agreement_id = request.args.get("agreement_id")
    if agreement_id:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    party = request.args.get("offering_party")
    if party:
        rows = [r for r in rows if r["offering_party"] == party]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = scope_filter(actor, rows, carrier_of_offer)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/negotiation-offers/<offer_id>/accept")
def accept_offer(offer_id):
    actor = authenticate((INTERCONNECTION_MANAGER, CARRIER_REPRESENTATIVE))
    offer = get_offer(offer_id)
    agreement = db.agreements.get(offer["agreement_id"])
    scope_check(actor, agreement["carrier_id"])

    if agreement["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "the agreement is not awaiting an acceptance")
    if offer["status"] != "OPEN":
        raise ApiError("ERR_INVALID_OFFER_STATE", "only an OPEN offer may be accepted")
    if acting_party(actor.role) == offer["offering_party"]:
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "the offering party may not accept its own offer")

    offer["status"] = "ACCEPTED"
    offer["responded_at"] = now()

    agreement["reciprocal_rate_per_mou_usd"] = offer["reciprocal_rate_per_mou_usd"]
    agreement["term_months"] = offer["term_months"]
    agreement["poi_financial_responsibility"] = offer["poi_financial_responsibility"]
    agreement["transit_traffic_allowed"] = offer["transit_traffic_allowed"]
    agreement["status"] = "EXECUTED"
    agreement["executed_at"] = now()
    touch(agreement)
    return object_response(agreement)


@bp.post("/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate((INTERCONNECTION_MANAGER,))
    agreement = get_agreement(agreement_id)

    if agreement["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "only an EXECUTED agreement may be activated")
    if now() < agreement["effective_date"]:
        raise ApiError("ERR_EFFECTIVE_DATE_NOT_REACHED",
                       "the logical clock has not reached the effective date")
    if effective_filing_for("LOCAL_RECIPROCAL_COMP", agreement["effective_date"]) is None:
        raise ApiError("ERR_NO_EFFECTIVE_RECIPROCAL_RATE",
                       "no effective LOCAL_RECIPROCAL_COMP filing covers the effective date")

    agreement["status"] = "EFFECTIVE"
    recompute_posture(agreement)
    touch(agreement)
    return object_response(agreement)


@bp.post("/agreements/<agreement_id>/withdraw")
def withdraw_agreement(agreement_id):
    authenticate((INTERCONNECTION_MANAGER,))
    agreement = get_agreement(agreement_id)
    payload = v.body()
    reason = v.string(payload, "withdrawal_reason")

    if agreement["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "only an agreement under negotiation may be withdrawn")

    standing = standing_offer(agreement["id"])
    if standing is not None:
        standing["status"] = "WITHDRAWN"
        standing["responded_at"] = now()

    agreement["status"] = "WITHDRAWN"
    agreement["_withdrawal_reason"] = reason
    touch(agreement)
    return object_response(agreement)


@bp.post("/agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    authenticate((INTERCONNECTION_MANAGER,))
    agreement = get_agreement(agreement_id)
    payload = v.body()
    reason = v.string(payload, "termination_reason")

    if agreement["status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "only an EFFECTIVE agreement may be terminated")
    for batch in db.usage_batches.values():
        if (batch["carrier_id"] == agreement["carrier_id"]
                and batch["status"] in ("SUBMITTED", "JURISDICTIONALIZED")):
            raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                           "usage remains unrated for this carrier")

    agreement["status"] = "TERMINATED"
    agreement["terminated_at"] = now()
    agreement["_termination_reason"] = reason

    trunk_groups = [tg for tg in ordered(db.trunk_groups)
                    if tg["agreement_id"] == agreement["id"]]
    for trunk_group in trunk_groups:
        if trunk_group["service_status"] not in ("REQUESTED", "PROVISIONED", "IN_SERVICE"):
            continue
        trunk_group["service_status"] = "DISCONNECT_PENDING"
        orders = [o for o in ordered(db.augment_orders)
                  if o["trunk_group_id"] == trunk_group["id"]
                  and o["status"] in ("PENDING", "ACCEPTED")]
        for order in orders:
            order["status"] = "REJECTED"
            order["rejection_reason"] = "AGREEMENT_TERMINATED"
            touch(order)
            trunk_group["open_augment_order_count"] -= 1
            agreement["poi_augment_pending_count"] -= 1
        touch(trunk_group)

    recompute_posture(agreement)
    agreement["total_in_service_trunks"] = 0
    touch(agreement)
    return object_response(agreement)


@bp.get("/agreements/<agreement_id>/reciprocal-settlement")
def reciprocal_settlement(agreement_id):
    actor = authenticate((INTERCONNECTION_MANAGER, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    agreement = get_agreement(agreement_id)
    scope_check(actor, agreement["carrier_id"])

    inbound = ZERO4
    outbound = ZERO4
    for batch in db.usage_batches.values():
        if batch["carrier_id"] != agreement["carrier_id"]:
            continue
        if batch["status"] not in ("RATED", "INVOICED"):
            continue
        if batch["direction"] == "TERMINATING_TO_US":
            inbound += batch["total_billable_minutes"]
        elif batch["direction"] == "ORIGINATING_FROM_US":
            outbound += batch["total_billable_minutes"]
    inbound = q4(inbound)
    outbound = q4(outbound)
    rate = agreement["reciprocal_rate_per_mou_usd"]

    if outbound == ZERO4:
        ratio = None
        mode = "UNDETERMINED"
        net = ZERO2
    else:
        ratio = q4(inbound / outbound)
        if BILL_AND_KEEP_RATIO_FLOOR <= ratio <= BILL_AND_KEEP_RATIO_CEILING:
            mode = "BILL_AND_KEEP"
            net = ZERO2
        else:
            mode = "METERED"
            net = ZERO2 if rate is None else q2((inbound - outbound) * rate)

    return object_response({
        "inbound_minutes": inbound,
        "outbound_minutes": outbound,
        "traffic_balance_ratio": ratio,
        "settlement_mode": mode,
        "net_settlement_usd": net,
        "reciprocal_rate_per_mou_usd": rate,
    })
