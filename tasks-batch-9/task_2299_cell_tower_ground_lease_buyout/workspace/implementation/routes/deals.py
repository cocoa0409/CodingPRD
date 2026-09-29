"""Deals, offers, clearance, escrow and closing (PRD 3.5 - 3.7)."""

from flask import Blueprint

import calc
import engine as E
import validate as V
from auth import principal
from db import db
from errors import fail
from response import created, ok, ok_list

bp = Blueprint("deals", __name__)

EASEMENT_TYPES = ("PERPETUAL_EASEMENT", "LONG_TERM_EASEMENT")
STAGES = ("ORIGINATION", "OUTREACH", "CAPITAL_HOLD", "NEGOTIATION", "DILIGENCE",
          "CLEAR_TO_CLOSE", "CLOSED", "DEAD", "ROFR_LOST", "TERMINATED")
CAPITAL_STATES = ("UNCOMMITTED", "RESERVED", "ESCROWED", "DISBURSED", "RELEASED")
OFFER_TYPES = ("LUMP_SUM", "PREPAID_RENT")
OFFER_STATUSES = ("DRAFT", "SENT", "COUNTERED", "ACCEPTED", "REJECTED", "LAPSED", "WITHDRAWN")

ANALYST_ACTIONS = ("SEND", "REVISE", "WITHDRAW")
LANDOWNER_ACTIONS = ("COUNTER", "ACCEPT", "REJECT")
OFFER_ACTIONS = ANALYST_ACTIONS + LANDOWNER_ACTIONS

DEAL_LIST_ROLES = ("AcquisitionAnalyst", "PortfolioManager", "PlatformAdmin",
                   "TreasuryOfficer", "TitleOfficer")
DEAL_GET_ROLES = DEAL_LIST_ROLES + ("Lender", "Landowner", "TowerCompanyAgent")
SETTLEMENT_ROLES = ("AcquisitionAnalyst", "PortfolioManager", "PlatformAdmin", "TreasuryOfficer")
OFFER_READ_ROLES = ("AcquisitionAnalyst", "PortfolioManager", "PlatformAdmin", "Landowner")

OFFER_TRANSITIONS = {
    "SEND": ("DRAFT",),
    "REVISE": ("COUNTERED",),
    "WITHDRAW": ("SENT", "COUNTERED"),
    "COUNTER": ("SENT",),
    "ACCEPT": ("SENT",),
    "REJECT": ("SENT", "COUNTERED"),
}


def _landowner_of(deal):
    stream = db.lease_streams.get(deal["lease_stream_id"])
    if stream is None:
        return None
    return db.landowners.get(stream["landowner_id"])


def _rofr_required(deal):
    stream = db.lease_streams.get(deal["lease_stream_id"])
    if stream is None:
        return False
    company = E.tower_company_of_stream(stream)
    return bool(company and company["rofr_required"])


# ------------------------------------------------------------------------ deals

@bp.post("/deals")
def create_deal():
    principal("AcquisitionAnalyst")
    b = V.body()
    portfolio = E.fk(b, "portfolio_id", "portfolios", "ERR_PORTFOLIO_NOT_FOUND")
    stream = E.fk(b, "lease_stream_id", "lease_streams", "ERR_LEASE_STREAM_NOT_FOUND")
    valuation = E.fk(b, "valuation_id", "valuations", "ERR_VALUATION_NOT_FOUND")
    if portfolio is None or stream is None or valuation is None:
        V.bad()
    easement_type = V.req_enum(b, "easement_type", EASEMENT_TYPES)
    term_years = V.opt_int(b, "easement_term_years", default=0, minimum=0, maximum=99)
    revenue_share = V.opt_int(b, "revenue_share_bps", default=2500, minimum=0, maximum=5000)

    if E.active_deal_of_stream(stream["id"]) is not None:
        fail("ERR_DUPLICATE_ACTIVE_DEAL")

    company = E.tower_company_of_stream(stream)
    deal = E.new_entity(
        portfolio_id=portfolio["id"],
        lease_stream_id=stream["id"],
        valuation_id=valuation["id"],
        easement_type=easement_type,
        easement_term_years=term_years,
        revenue_share_bps=revenue_share,
        stage="ORIGINATION",
        capital_state="UNCOMMITTED",
        rofr_state="PENDING" if (company and company["rofr_required"]) else "NOT_REQUIRED",
        negotiation_rounds=0,
        agreed_consideration_cents=None,
        broker_fee_bps=0,
        broker_fee_cents=0,
        holdback_cents=0,
        net_landowner_proceeds_cents=0,
        total_commitment_cents=0,
        escrow_funded_cents=0,
        escrow_disbursed_cents=0,
        escrow_holdback_cents=0,
        escrow_refunded_cents=0,
        easement_status="NOT_DRAFTED",
        recording_ref=None,
        recorded_at=None,
        closed_by_user_id=None,
    )
    db.deals[deal["id"]] = deal
    E.recompute_portfolio(portfolio)
    return created(E.deal_json(deal))


@bp.get("/deals")
def list_deals():
    principal(*DEAL_LIST_ROLES)
    limit, offset = V.pagination()
    portfolio_id = V.str_filter("portfolio_id")
    stream_id = V.str_filter("lease_stream_id")
    valuation_id = V.str_filter("valuation_id")
    stage = V.enum_filter("stage", STAGES)
    capital_state = V.enum_filter("capital_state", CAPITAL_STATES)
    rows = E.ordered(list(db.deals.values()))
    if portfolio_id is not None:
        rows = [r for r in rows if r["portfolio_id"] == portfolio_id]
    if stream_id is not None:
        rows = [r for r in rows if r["lease_stream_id"] == stream_id]
    if valuation_id is not None:
        rows = [r for r in rows if r["valuation_id"] == valuation_id]
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    if capital_state is not None:
        rows = [r for r in rows if r["capital_state"] == capital_state]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.deal_json(r) for r in page], total, limit, offset)


@bp.get("/deals/<did>")
def get_deal(did):
    principal(*DEAL_GET_ROLES)
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    return ok(E.deal_json(deal))


@bp.get("/deals/<did>/settlement")
def get_settlement(did):
    principal(*SETTLEMENT_ROLES)
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    return ok(E.settlement_json(deal))


@bp.post("/deals/<did>/outreach")
def start_outreach(did):
    principal("AcquisitionAnalyst")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")

    if deal["stage"] != "ORIGINATION":
        fail("ERR_INVALID_DEAL_STAGE")

    valuation = db.valuations.get(deal["valuation_id"])
    status = valuation["status"] if valuation else "DRAFT"
    if status == "DRAFT":
        fail("ERR_VALUATION_NOT_APPROVED")
    if status in ("STALE", "SUPERSEDED"):
        fail("ERR_VALUATION_STALE")

    landowner = _landowner_of(deal)
    if landowner is not None and E.outreach_status(landowner) == "DO_NOT_CONTACT":
        fail("ERR_LANDOWNER_DO_NOT_CONTACT")

    deal["stage"] = "OUTREACH"
    E.touch(deal)
    stream = db.lease_streams.get(deal["lease_stream_id"])
    if stream is not None:
        E.set_stream_acquisition(stream, "UNDER_OFFER")
    # keeps the CAPITAL_HOLD invariant when the portfolio is already FROZEN
    E.recompute_portfolio(db.portfolios.get(deal["portfolio_id"]))
    return ok(E.deal_json(deal))


@bp.post("/deals/<did>/terminate")
def terminate_deal(did):
    principal("PortfolioManager")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    b = V.body()
    V.req_str(b, "reason")

    if deal["stage"] not in ("DILIGENCE", "CLEAR_TO_CLOSE"):
        fail("ERR_INVALID_DEAL_STAGE")

    deal["stage"] = "TERMINATED"
    E.release_capital(deal, refund_escrow=True)
    E.touch(deal)
    stream = db.lease_streams.get(deal["lease_stream_id"])
    if stream is not None:
        E.set_stream_acquisition(stream, "PROSPECT")
    E.recompute_portfolio(db.portfolios.get(deal["portfolio_id"]))
    return ok(E.deal_json(deal))


@bp.post("/deals/<did>/clear-to-close")
def clear_to_close(did):
    principal("PortfolioManager", "AcquisitionAnalyst")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")

    if deal["stage"] != "DILIGENCE":
        fail("ERR_INVALID_DEAL_STAGE")

    blocker = E.join_conditions(deal)
    if blocker is not None:
        fail(blocker)

    deal["stage"] = "CLEAR_TO_CLOSE"
    deal["easement_status"] = "DRAFTED"
    E.touch(deal)
    return ok(E.deal_json(deal))


@bp.post("/deals/<did>/escrow-funding")
def fund_escrow(did):
    principal("TreasuryOfficer")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")

    if deal["stage"] != "CLEAR_TO_CLOSE":
        fail("ERR_INVALID_DEAL_STAGE")
    if deal["capital_state"] != "RESERVED":
        fail("ERR_INVALID_CAPITAL_STATE")

    deal["capital_state"] = "ESCROWED"
    deal["escrow_funded_cents"] = deal["total_commitment_cents"]
    E.touch(deal)
    E.recompute_portfolio(db.portfolios.get(deal["portfolio_id"]))
    return ok(E.deal_json(deal))


@bp.post("/deals/<did>/close")
def close_deal(did):
    user_id, _role = principal("PortfolioManager")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    b = V.body()
    recording_ref = V.req_str(b, "recording_ref")

    valuation = db.valuations.get(deal["valuation_id"])
    if valuation is not None and valuation["approved_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    if deal["stage"] != "CLEAR_TO_CLOSE":
        fail("ERR_INVALID_DEAL_STAGE")
    if deal["capital_state"] != "ESCROWED":
        fail("ERR_INVALID_CAPITAL_STATE")

    if deal["rofr_state"] == "PENDING":
        fail("ERR_ROFR_WINDOW_OPEN")
    if E.open_disputes_count(deal["lease_stream_id"]) > 0:
        fail("ERR_OPEN_DISPUTE_BLOCKS_CLOSE")
    report = E.title_report_of(deal["id"])
    if report is not None and report["mortgage_present"] and report["consent_status"] != "GRANTED":
        fail("ERR_MORTGAGE_CONSENT_MISSING")
    if report is None or report["review_status"] != "CLEARED" or report["open_exception_count"] > 0:
        fail("ERR_TITLE_EXCEPTIONS_OPEN")

    deal["stage"] = "CLOSED"
    deal["closed_by_user_id"] = user_id
    deal["capital_state"] = "DISBURSED"
    deal["escrow_disbursed_cents"] = (deal["net_landowner_proceeds_cents"]
                                      + deal["broker_fee_cents"])
    deal["escrow_holdback_cents"] = deal["holdback_cents"]
    deal["easement_status"] = "RECORDED"
    deal["recording_ref"] = recording_ref
    deal["recorded_at"] = E.now()
    E.touch(deal)

    stream = db.lease_streams.get(deal["lease_stream_id"])
    if stream is not None:
        E.set_stream_acquisition(stream, "ACQUIRED")
        E.set_servicing_status(stream, "PERFORMING")
        for tenancy in E.tenancies_of(stream["id"]):
            if tenancy["status"] in ("ACTIVE", "HOLDOVER"):
                if tenancy["redirection_notice_status"] != "SENT":
                    tenancy["redirection_notice_status"] = "SENT"
                    E.touch(tenancy)
        if stream["rent_redirection_status"] != "SENT":
            stream["rent_redirection_status"] = "SENT"
            E.touch(stream)

    landowner = _landowner_of(deal)
    if landowner is not None:
        E.set_derived_outreach(landowner, "CLOSED")

    E.recompute_portfolio(db.portfolios.get(deal["portfolio_id"]))
    return ok(E.deal_json(deal))


# ----------------------------------------------------------------------- offers

@bp.post("/deals/<did>/offers")
def create_offer(did):
    principal("AcquisitionAnalyst")
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    b = V.body()
    offer_type = V.req_enum(b, "offer_type", OFFER_TYPES)
    amount = V.req_int(b, "amount_cents", minimum=1)
    expires_at = V.req_dt(b, "expires_at")
    prepaid_months = V.opt_int(b, "prepaid_term_months", default=0, minimum=0, maximum=600)

    valuation = db.valuations.get(deal["valuation_id"])
    method = valuation["method"] if valuation else None
    if ((offer_type == "LUMP_SUM" and method != "LUMP_SUM_PERPETUAL")
            or (offer_type == "PREPAID_RENT" and method != "PREPAID_RENT_TERM")):
        fail("ERR_VALUATION_METHOD_MISMATCH")

    offer = E.new_entity(
        deal_id=deal["id"],
        offer_type=offer_type,
        amount_cents=amount,
        prepaid_term_months=prepaid_months,
        expires_at=expires_at,
        round_number=0,
        counter_amount_cents=None,
        status="DRAFT",
        sent_at=None,
        decided_at=None,
        decided_by_user_id=None,
    )
    db.offers[offer["id"]] = offer
    return created(E.offer_json(offer))


@bp.get("/deals/<did>/offers")
def list_offers(did):
    principal(*OFFER_READ_ROLES)
    deal = E.find("deals", did, "ERR_DEAL_NOT_FOUND")
    limit, offset = V.pagination()
    status = V.enum_filter("status", OFFER_STATUSES)
    rows = E.offers_of(deal["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.offer_json(r) for r in page], total, limit, offset)


@bp.post("/offers/<oid>/transitions")
def offer_transition(oid):
    user_id, role = principal("AcquisitionAnalyst", "Landowner")
    offer = E.find("offers", oid, "ERR_OFFER_NOT_FOUND")
    deal = db.deals.get(offer["deal_id"])
    b = V.body()
    action = V.req_enum(b, "action", OFFER_ACTIONS)
    counter_amount = None
    revised_amount = None
    if action == "COUNTER":
        counter_amount = V.req_int(b, "counter_amount_cents", minimum=1)
    if action == "REVISE":
        revised_amount = V.opt_int(b, "amount_cents", minimum=1)

    stream = db.lease_streams.get(deal["lease_stream_id"]) if deal else None
    landowner = db.landowners.get(stream["landowner_id"]) if stream else None

    # step 6: landowner ownership
    if role == "Landowner":
        if landowner is None or landowner["id"] != user_id:
            fail("ERR_NOT_DEAL_LANDOWNER")
    # step 8: action-to-role
    if role == "AcquisitionAnalyst" and action not in ANALYST_ACTIONS:
        fail("ERR_ACTION_ROLE_MISMATCH")
    if role == "Landowner" and action not in LANDOWNER_ACTIONS:
        fail("ERR_ACTION_ROLE_MISMATCH")

    # steps 12-13: offer state and expiry.  A SENT offer past expires_at has
    # already lapsed lazily; the landowner verbs report the expiry explicitly.
    if action in LANDOWNER_ACTIONS and offer["status"] == "LAPSED":
        fail("ERR_OFFER_EXPIRED")
    if offer["status"] not in OFFER_TRANSITIONS[action]:
        fail("ERR_INVALID_OFFER_STATE")
    if action in LANDOWNER_ACTIONS and E.now() >= offer["expires_at"]:
        fail("ERR_OFFER_EXPIRED")

    valuation = db.valuations.get(deal["valuation_id"]) if deal else None

    if action == "SEND":
        if deal["stage"] not in ("OUTREACH", "NEGOTIATION"):
            fail("ERR_INVALID_DEAL_STAGE")
        if valuation is not None and valuation["status"] in ("STALE", "SUPERSEDED"):
            fail("ERR_VALUATION_STALE")
        if landowner is not None and E.outreach_status(landowner) == "DO_NOT_CONTACT":
            fail("ERR_LANDOWNER_DO_NOT_CONTACT")
        for other in E.offers_of(deal["id"]):
            if other["id"] != offer["id"] and other["status"] in ("SENT", "COUNTERED"):
                fail("ERR_OFFER_ALREADY_OUTSTANDING")
        if valuation is not None and offer["amount_cents"] > valuation["max_bid_cents"]:
            fail("ERR_OFFER_EXCEEDS_GUARDRAIL")

        offer["status"] = "SENT"
        offer["sent_at"] = E.now()
        deal["negotiation_rounds"] += 1
        offer["round_number"] = deal["negotiation_rounds"]
        if deal["stage"] == "OUTREACH":
            deal["stage"] = "NEGOTIATION"
        E.touch(deal)
        if landowner is not None and landowner["derived_outreach_status"] == "NEW":
            E.set_derived_outreach(landowner, "CONTACTED")

    elif action == "REVISE":
        if deal["negotiation_rounds"] >= calc.MAX_NEGOTIATION_ROUNDS:
            fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")
        amount = revised_amount if revised_amount is not None else offer["amount_cents"]
        if valuation is not None and amount > valuation["max_bid_cents"]:
            fail("ERR_OFFER_EXCEEDS_GUARDRAIL")

        offer["status"] = "SENT"
        offer["amount_cents"] = amount
        offer["counter_amount_cents"] = None
        offer["sent_at"] = E.now()
        deal["negotiation_rounds"] += 1
        offer["round_number"] = deal["negotiation_rounds"]
        E.touch(deal)

    elif action == "WITHDRAW":
        offer["status"] = "WITHDRAWN"
        offer["decided_at"] = E.now()

    elif action == "COUNTER":
        offer["status"] = "COUNTERED"
        offer["counter_amount_cents"] = counter_amount
        if landowner is not None:
            E.set_derived_outreach(landowner, "NEGOTIATING")

    elif action == "REJECT":
        offer["status"] = "REJECTED"
        offer["decided_at"] = E.now()
        offer["decided_by_user_id"] = user_id

    elif action == "ACCEPT":
        if deal["stage"] != "NEGOTIATION":
            fail("ERR_INVALID_DEAL_STAGE")
        portfolio = db.portfolios.get(deal["portfolio_id"])
        figures = calc.settlement(offer["amount_cents"],
                                 E.open_disputes_count(deal["lease_stream_id"]))
        if portfolio is not None:
            if portfolio["capital_posture"] == "FROZEN":
                fail("ERR_PORTFOLIO_CAPITAL_FROZEN")
            if portfolio["available_capital_cents"] < figures["total_commitment_cents"]:
                fail("ERR_INSUFFICIENT_PORTFOLIO_CAPITAL")

        offer["status"] = "ACCEPTED"
        offer["decided_at"] = E.now()
        offer["decided_by_user_id"] = user_id
        deal["agreed_consideration_cents"] = offer["amount_cents"]
        deal.update(figures)
        deal["capital_state"] = "RESERVED"
        deal["stage"] = "DILIGENCE"
        deal["rofr_state"] = "PENDING" if _rofr_required(deal) else "NOT_REQUIRED"
        E.touch(deal)
        if landowner is not None:
            E.set_derived_outreach(landowner, "UNDER_CONTRACT")
        E.recompute_portfolio(portfolio)

    E.touch(offer)
    return ok(E.offer_json(offer))
