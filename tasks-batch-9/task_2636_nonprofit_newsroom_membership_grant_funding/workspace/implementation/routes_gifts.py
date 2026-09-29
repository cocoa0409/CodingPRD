"""Major gift cultivation: offer, negotiation, ratification and acceptance
(§3.6)."""

from flask import Blueprint

import calc
import derive
import guards
from core import (
    DB, ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
    ROLE_FINANCE_CONTROLLER, acting_user, apply_changes, authenticate, body, fail,
    iso_date, list_response, lookup, lookup_fk, new_row, object_response,
    pagination, paginate, public, q_enum, q_str, rows, v_date, v_enum, v_int,
    v_str,
)

bp = Blueprint("gifts", __name__)

GIFT_READ_ROLES = (ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
                   ROLE_FINANCE_CONTROLLER, ROLE_BOARD_OVERSIGHT)

MIN_GIFT_CENTS = 100000


def get_offer(offer_id):
    return lookup("gift_offers", offer_id, "ERR_GIFT_OFFER_NOT_FOUND")


def apply_netting(offer, funder):
    """Stewardship netting -- fee tier keyed on the GROSS amount, chosen before
    the net exists, then the ratification flag also keyed on the gross."""
    fee, net, ratify = calc.gift_stewardship_netting(
        offer["offered_amount_cents"],
        int(funder["independence_risk_score"]) if funder else 0)
    return {
        "stewardship_fee_cents": fee,
        "net_acceptable_amount_cents": net,
        "board_ratification_required": ratify,
    }


@bp.post("/gift-offers")
def create_gift_offer():
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    data = body()
    funder = lookup_fk("funders", data.get("funder_id"), "ERR_FUNDER_NOT_FOUND")
    if funder is None:
        fail("ERR_INVALID_REQUEST", "funder_id is required")
    period = lookup_fk("fiscal_periods", data.get("fiscal_period_id"),
                       "ERR_FISCAL_PERIOD_NOT_FOUND")
    if period is None:
        fail("ERR_INVALID_REQUEST", "fiscal_period_id is required")
    area = lookup_fk("coverage_areas", data.get("coverage_area_id"),
                     "ERR_COVERAGE_AREA_NOT_FOUND")
    offered_amount_cents = v_int(data, "offered_amount_cents",
                                 minimum=MIN_GIFT_CENTS)
    designation = v_enum(data, "designation", calc.DESIGNATIONS)
    donor_conditions = v_str(data, "donor_conditions", required=False, default=None,
                             min_len=0)
    guards.require_funder_not_restricted(funder)

    offer = new_row("gift_offers", {
        "funder_id": funder["id"],
        "coverage_area_id": area["id"] if area else None,
        "fiscal_period_id": period["id"],
        "offered_amount_cents": offered_amount_cents,
        "designation": designation,
        "donor_conditions": donor_conditions,
        "status": "PROPOSED",
        "stewardship_fee_cents": 0,
        "net_acceptable_amount_cents": 0,
        "board_ratification_required": False,
        "acceptance_gate_score": 0,
        "solicited_by_user_id": acting_user(),
        "cleared_by_user_id": None,
        "board_ratified_by_user_id": None,
        "conditions_round_count": 0,
    })
    return object_response(public(offer), 201)


@bp.get("/gift-offers/<offer_id>")
def read_gift_offer(offer_id):
    authenticate(*GIFT_READ_ROLES)
    return object_response(public(get_offer(offer_id)))


@bp.get("/gift-offers")
def list_gift_offers():
    authenticate(*GIFT_READ_ROLES)
    funder_id = q_str("funder_id")
    area_id = q_str("coverage_area_id")
    period_id = q_str("fiscal_period_id")
    status = q_enum("status", calc.GIFT_STATUSES)
    limit, offset = pagination()
    items = []
    for offer in rows("gift_offers"):
        if funder_id is not None and offer["funder_id"] != funder_id:
            continue
        if area_id is not None and offer["coverage_area_id"] != area_id:
            continue
        if period_id is not None and offer["fiscal_period_id"] != period_id:
            continue
        if status is not None and offer["status"] != status:
            continue
        items.append(offer)
    page, total = paginate(items, limit, offset)
    return list_response([public(o) for o in page], total, limit, offset)


@bp.post("/gift-offers/<offer_id>/submit-for-review")
def submit_gift_offer(offer_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    offer = get_offer(offer_id)
    data = body()
    # Supplying donor_conditions replaces the stored conditions; omitting the
    # field clears them to null -- the mechanism by which a donor withdraws.
    donor_conditions = v_str(data, "donor_conditions", required=False, default=None,
                             min_len=0)
    funder = DB["funders"].get(offer["funder_id"])

    guards.require_not_terminal(offer["status"], calc.GIFT_TERMINAL, "gift offer")
    guards.require_state(offer["status"], ("PROPOSED", "CONDITIONS_REQUESTED"),
                         "gift offer")
    if funder is not None:
        guards.require_funder_not_restricted(funder)
    if offer["status"] == "PROPOSED" and calc.is_designated(offer["designation"]):
        guards.require_publication_gate_open(offer["coverage_area_id"])

    changes = {"status": "INDEPENDENCE_REVIEW", "donor_conditions": donor_conditions}
    changes.update(apply_netting(offer, funder))
    apply_changes(offer, changes, force=True)
    return object_response(public(offer))


@bp.post("/gift-offers/<offer_id>/independence-review")
def review_gift_offer(offer_id):
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    offer = get_offer(offer_id)
    data = body()
    decision = v_enum(data, "decision", ("CLEAR", "REQUEST_CONDITIONS", "DECLINE"))
    review_note = v_str(data, "review_note", required=False, default=None, min_len=0)
    funder = DB["funders"].get(offer["funder_id"])

    guards.require_not_terminal(offer["status"], calc.GIFT_TERMINAL, "gift offer")
    if decision == "DECLINE":
        guards.require_state(offer["status"],
                             ("INDEPENDENCE_REVIEW", "CONDITIONS_REQUESTED"),
                             "gift offer")
    else:
        guards.require_state(offer["status"], ("INDEPENDENCE_REVIEW",), "gift offer")
    guards.require_dual_control(offer.get("solicited_by_user_id"))

    if decision == "REQUEST_CONDITIONS":
        if int(offer["conditions_round_count"]) >= calc.MAX_CONDITION_ROUNDS:
            fail("ERR_CONDITION_ROUNDS_EXHAUSTED",
                 "the offer has already used %s condition rounds"
                 % offer["conditions_round_count"])
        apply_changes(offer, {
            "status": "CONDITIONS_REQUESTED",
            "conditions_round_count": int(offer["conditions_round_count"]) + 1,
            "donor_conditions": review_note,
        }, force=True)
    elif decision == "CLEAR":
        guards.require_funder_cleared(funder or {})
        guards.require_risk_below_hard_bar(int(funder["independence_risk_score"]))
        if calc.is_designated(offer["designation"]):
            guards.require_active_disclosure(offer["funder_id"],
                                             offer["coverage_area_id"])
            guards.require_no_stale_disclosure(offer["funder_id"],
                                               offer["coverage_area_id"])
        if offer.get("donor_conditions"):
            fail("ERR_EDITORIAL_CONDITION_PRESENT",
                 "the offer still carries donor conditions")
        apply_changes(offer, {
            "status": "CLEARED",
            "acceptance_gate_score": int(funder["independence_risk_score"]),
            "cleared_by_user_id": acting_user(),
        }, force=True)
    else:
        apply_changes(offer, {
            "status": "DECLINED",
            "cleared_by_user_id": acting_user(),
        }, force=True)
    return object_response(public(offer))


@bp.post("/gift-offers/<offer_id>/board-ratification")
def ratify_gift_offer(offer_id):
    authenticate(ROLE_BOARD_OVERSIGHT)
    offer = get_offer(offer_id)
    data = body()
    v_str(data, "ratification_note", required=False, default=None, min_len=0)

    guards.require_not_terminal(offer["status"], calc.GIFT_TERMINAL, "gift offer")
    guards.require_state(offer["status"], ("CLEARED",), "gift offer")
    if not offer["board_ratification_required"]:
        fail("ERR_INVALID_STATE", "the offer does not require board ratification")
    if offer.get("board_ratified_by_user_id") is not None:
        fail("ERR_INVALID_STATE", "the offer has already been ratified")
    guards.require_dual_control(offer.get("solicited_by_user_id"),
                                offer.get("cleared_by_user_id"))

    apply_changes(offer, {"board_ratified_by_user_id": acting_user()}, force=True)
    return object_response(public(offer))


@bp.post("/gift-offers/<offer_id>/accept")
def accept_gift_offer(offer_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    offer = get_offer(offer_id)
    data = body()
    received_date = v_date(data, "received_date")
    funder = DB["funders"].get(offer["funder_id"])
    period = DB["fiscal_periods"].get(offer["fiscal_period_id"])

    guards.require_period_open(period)
    guards.require_not_terminal(offer["status"], calc.GIFT_TERMINAL, "gift offer")
    guards.require_state(offer["status"], ("CLEARED",), "gift offer")
    guards.require_dual_control(offer.get("solicited_by_user_id"))
    guards.require_funder_cleared(funder or {})
    if calc.is_designated(offer["designation"]):
        guards.require_publication_gate_open(offer["coverage_area_id"])
    if (offer["board_ratification_required"]
            and offer.get("board_ratified_by_user_id") is None):
        fail("ERR_BOARD_RATIFICATION_REQUIRED",
             "the offer must be ratified by board oversight before acceptance")

    amount_cents = int(offer["net_acceptable_amount_cents"])
    qpq, deductible = calc.contribution_deductible_split("MAJOR_GIFT", amount_cents,
                                                         None)
    new_row("contributions", {
        "fiscal_period_id": offer["fiscal_period_id"],
        "member_id": None,
        "funder_id": offer["funder_id"],
        "gift_offer_id": offer["id"],
        "collaboration_id": None,
        "revenue_stream": "MAJOR_GIFT",
        "amount_cents": amount_cents,
        "received_date": iso_date(received_date),
        "source_label": funder["legal_name"] if funder else None,
        "settlement_status": "INITIATED",
        "acknowledgment_status": "UNACKNOWLEDGED",
        "quid_pro_quo_cents": qpq,
        "deductible_cents": deductible,
        "receipt_number": None,
        "refunded_at": None,
    })
    apply_changes(offer, {"status": "ACCEPTED"}, force=True)
    if funder is not None:
        derive.recompute_funder(funder)
    return object_response(public(offer))
