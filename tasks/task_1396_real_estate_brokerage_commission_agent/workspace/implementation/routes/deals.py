"""Deal routes (PRD §3.5-§3.6): pipeline, close/void, payout estimate, settle."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN_RESOURCE, ERR_AGENT_INVALID_STATE,
    ERR_DEAL_INVALID_STATE, ERR_DEAL_HAS_SETTLEMENT, ERR_DEAL_BEFORE_JOIN,
    ERR_FUTURE_CLOSING, ERR_NONPOSITIVE_GROSS, ERR_COBROKE_EXCEEDS_GROSS,
    ERR_PCT_OUT_OF_RANGE, ERR_REFERRAL_INCOMPLETE, ERR_COBROKE_PAYEE_MISSING,
    ERR_SELF_REFERENCE, ERR_NO_PLAN_ENROLLMENT, ERR_WINDOW_CLOSED,
)
from middleware import (
    body, req_str, opt_str, req_int, opt_int, opt_num, req_date, opt_date,
    forbid_unless_owner, parse_enum_filter, parse_str_filter,
)
from response import success_obj
from routes.helpers import guard, public, list_response, by_created
from services.common import new_id, stamp_new, touch
from services.trust import post_trust
from services.deal_svc import settle_deal, unsettle_deal, active_settlement_for_deal
from services.waterfall import run_waterfall
from timeutil import window_index_for

bp = Blueprint("deals", __name__)

DEAL_STATUSES = {"DRAFT", "PENDING_CLOSING", "CLOSED", "SETTLED", "DISBURSED",
                 "FELL_THROUGH", "VOIDED"}


def _get_deal(deal_id):
    deal = db.deals.get(deal_id)
    if deal is None:
        raise ApiError(ERR_NOT_FOUND, 404, "deal not found")
    return deal


def _parse_terms(data, for_update=False):
    """Parse deal terms from a request body (step-5 schema checks)."""
    out = {}
    if not for_update:
        out["agent_id"] = req_str(data, "agent_id")
    out["address"] = req_str(data, "address")
    out["gross_commission_cents"] = req_int(data, "gross_commission_cents")
    out["closing_date"] = req_date(data, "closing_date")
    out["cobroke_payout_cents"] = opt_int(data, "cobroke_payout_cents", 0)
    out["cobroke_payee_name"] = opt_str(data, "cobroke_payee_name")
    out["referral_pct"] = opt_num(data, "referral_pct", 0)
    out["referral_agent_id"] = opt_str(data, "referral_agent_id")
    return out


def _validate_terms(terms, agent):
    """Business validations for deal economics (guard steps 10, 14, 17)."""
    gross = terms["gross_commission_cents"]
    cobroke = terms["cobroke_payout_cents"]
    referral_pct = terms["referral_pct"]
    referral_agent_id = terms["referral_agent_id"]

    # Temporal: closing_date must not precede the agent's joined_at
    if terms["closing_date"] < agent["_joined_date"]:
        raise ApiError(ERR_DEAL_BEFORE_JOIN, 422,
                       "closing_date precedes the agent's joined_at")

    # Referential: referral agent
    if referral_agent_id is not None:
        if referral_agent_id not in db.agents:
            raise ApiError(ERR_NOT_FOUND, 404, "referral_agent_id does not reference an existing Agent")
        if referral_agent_id == agent["id"]:
            raise ApiError(ERR_SELF_REFERENCE, 422,
                           "referral_agent_id must differ from the deal's agent_id")
    # Referral pair completeness
    if referral_agent_id is not None and not (referral_pct and referral_pct > 0):
        raise ApiError(ERR_REFERRAL_INCOMPLETE, 422,
                       "referral_agent_id requires referral_pct > 0")
    if referral_agent_id is None and referral_pct and referral_pct > 0:
        raise ApiError(ERR_REFERRAL_INCOMPLETE, 422,
                       "referral_pct > 0 requires referral_agent_id")

    # Co-broke payee required when a payout is present
    if cobroke and cobroke > 0 and not terms["cobroke_payee_name"]:
        raise ApiError(ERR_COBROKE_PAYEE_MISSING, 422,
                       "cobroke_payout_cents > 0 requires cobroke_payee_name")

    # Fiscal ranges (checked last)
    if gross <= 0:
        raise ApiError(ERR_NONPOSITIVE_GROSS, 422, "gross_commission_cents must be > 0")
    if cobroke is None or cobroke < 0 or cobroke >= gross:
        raise ApiError(ERR_COBROKE_EXCEEDS_GROSS, 422,
                       "cobroke_payout_cents must be >= 0 and < gross")
    if referral_pct is None or referral_pct < 0 or referral_pct > 1:
        raise ApiError(ERR_PCT_OUT_OF_RANGE, 422, "referral_pct must lie in [0,1]")


@bp.route("/brokerage/deals", methods=["POST"])
@guard(roles=["Agent", "TransactionCoordinator"])
def create_deal(user_id, role):
    data = body()
    terms = _parse_terms(data)

    # Ownership scoping for Agent-role callers
    if role == "Agent" and terms["agent_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_RESOURCE, 403,
                       "Agent-role callers may only create deals for themselves")

    agent = db.agents.get(terms["agent_id"])
    if agent is None:
        raise ApiError(ERR_NOT_FOUND, 404, "agent_id does not reference an existing Agent")

    if agent["status"] != "ACTIVE":
        raise ApiError(ERR_AGENT_INVALID_STATE, 409,
                       "only an ACTIVE agent may be credited with new deals")

    _validate_terms(terms, agent)

    deal = {
        "id": new_id(),
        "agent_id": terms["agent_id"],
        "address": terms["address"],
        "gross_commission_cents": terms["gross_commission_cents"],
        "closing_date": terms["closing_date"].isoformat(),
        "cobroke_payout_cents": terms["cobroke_payout_cents"] or 0,
        "cobroke_payee_name": terms["cobroke_payee_name"],
        "referral_pct": terms["referral_pct"] or 0,
        "referral_agent_id": terms["referral_agent_id"],
        "trust_received_cents": 0,
        "status": "DRAFT",
        "_closing_date": terms["closing_date"],
    }
    stamp_new(deal)
    db.deals[deal["id"]] = deal
    return success_obj(public(deal), status=201)


@bp.route("/brokerage/deals/<dealId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_deal(user_id, role, dealId):
    deal = _get_deal(dealId)
    forbid_unless_owner(role, user_id, deal["agent_id"])
    return success_obj(public(deal))


@bp.route("/brokerage/deals", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_deals(user_id, role):
    agent_id = parse_str_filter("agent_id")
    referral_agent_id = parse_str_filter("referral_agent_id")
    status = parse_enum_filter("status", DEAL_STATUSES)
    items = list(db.deals.values())
    if role == "Agent":
        items = [d for d in items if d["agent_id"] == user_id]
    if agent_id is not None:
        items = [d for d in items if d["agent_id"] == agent_id]
    if referral_agent_id is not None:
        items = [d for d in items if d.get("referral_agent_id") == referral_agent_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response(by_created(items))


@bp.route("/brokerage/deals/<dealId>", methods=["PUT"])
@guard(roles=["Agent", "TransactionCoordinator"])
def put_deal(user_id, role, dealId):
    # Step 5 (request schema) precedes step 6 (path existence) per PRD §2.9.
    terms = _parse_terms(body(), for_update=True)
    deal = _get_deal(dealId)
    if role == "Agent" and deal["agent_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_RESOURCE, 403, "not the owning agent")
    if deal["status"] != "DRAFT":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "only a DRAFT deal is editable")

    agent = db.agents[deal["agent_id"]]
    _validate_terms(terms, agent)

    deal["address"] = terms["address"]
    deal["gross_commission_cents"] = terms["gross_commission_cents"]
    deal["closing_date"] = terms["closing_date"].isoformat()
    deal["_closing_date"] = terms["closing_date"]
    deal["cobroke_payout_cents"] = terms["cobroke_payout_cents"] or 0
    deal["cobroke_payee_name"] = terms["cobroke_payee_name"]
    deal["referral_pct"] = terms["referral_pct"] or 0
    deal["referral_agent_id"] = terms["referral_agent_id"]
    touch(deal)
    return success_obj(public(deal))


@bp.route("/brokerage/deals/<dealId>/submit", methods=["POST"])
@guard(roles=["Agent", "TransactionCoordinator"])
def submit_deal(user_id, role, dealId):
    deal = _get_deal(dealId)
    if role == "Agent" and deal["agent_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_RESOURCE, 403, "not the owning agent")
    if deal["status"] != "DRAFT":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "deal is not DRAFT")
    deal["status"] = "PENDING_CLOSING"
    touch(deal)
    return success_obj(public(deal))


@bp.route("/brokerage/deals/<dealId>/withdraw", methods=["POST"])
@guard(roles=["Agent", "TransactionCoordinator"])
def withdraw_deal(user_id, role, dealId):
    deal = _get_deal(dealId)
    if role == "Agent" and deal["agent_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_RESOURCE, 403, "not the owning agent")
    if deal["status"] != "PENDING_CLOSING":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "deal is not PENDING_CLOSING")
    deal["status"] = "DRAFT"
    touch(deal)
    return success_obj(public(deal))


@bp.route("/brokerage/deals/<dealId>/fall-through", methods=["POST"])
@guard(roles=["TransactionCoordinator"])
def fall_through_deal(user_id, role, dealId):
    deal = _get_deal(dealId)
    if deal["status"] != "PENDING_CLOSING":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "deal is not PENDING_CLOSING")
    deal["status"] = "FELL_THROUGH"
    touch(deal)
    return success_obj(public(deal))


@bp.route("/brokerage/deals/<dealId>/close", methods=["POST"])
@guard(roles=["TransactionCoordinator"])
def close_deal(user_id, role, dealId):
    deal = _get_deal(dealId)
    if deal["status"] != "PENDING_CLOSING":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "deal is not PENDING_CLOSING")

    data = body()
    actual_gross = opt_int(data, "actual_gross_commission_cents")
    actual_closing = opt_date(data, "actual_closing_date")

    eff_gross = actual_gross if actual_gross is not None else deal["gross_commission_cents"]
    eff_closing = actual_closing if actual_closing is not None else deal["_closing_date"]

    agent = db.agents[deal["agent_id"]]

    # Temporal guards (steps 10-11) before fiscal range (step 17)
    if eff_closing < agent["_joined_date"]:
        raise ApiError(ERR_DEAL_BEFORE_JOIN, 422,
                       "the effective closing date precedes the agent's joined_at")
    if eff_closing > db.clock_date():
        raise ApiError(ERR_FUTURE_CLOSING, 422,
                       "the effective closing date lies after the clock date")
    if eff_gross <= 0:
        raise ApiError(ERR_NONPOSITIVE_GROSS, 422, "the effective gross must be > 0")

    if actual_gross is not None:
        deal["gross_commission_cents"] = actual_gross
    if actual_closing is not None:
        deal["closing_date"] = actual_closing.isoformat()
        deal["_closing_date"] = actual_closing

    deal["trust_received_cents"] = deal["gross_commission_cents"]
    post_trust(deal["id"], "RECEIPT", deal["gross_commission_cents"])
    deal["status"] = "CLOSED"
    touch(deal)
    return success_obj(public(deal))


@bp.route("/brokerage/deals/<dealId>/void", methods=["POST"])
@guard(roles=["TransactionCoordinator"])
def void_deal(user_id, role, dealId):
    deal = _get_deal(dealId)
    if deal["status"] != "CLOSED":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "only a CLOSED deal can be voided")
    post_trust(deal["id"], "RECEIPT_REVERSAL", -deal["trust_received_cents"])
    deal["trust_received_cents"] = 0
    deal["status"] = "VOIDED"
    touch(deal)
    return success_obj(public(deal))


@bp.route("/brokerage/deals/<dealId>/payout-estimate", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def payout_estimate(user_id, role, dealId):
    deal = _get_deal(dealId)
    forbid_unless_owner(role, user_id, deal["agent_id"])
    if deal["status"] in ("FELL_THROUGH", "VOIDED"):
        raise ApiError(ERR_DEAL_INVALID_STATE, 409,
                       "payout estimate is unavailable for FELL_THROUGH or VOIDED deals")

    agent = db.agents[deal["agent_id"]]
    closing = deal["_closing_date"]
    idx = window_index_for(agent["_joined_date"], closing)

    from services.anniversary import get_period
    window = get_period(agent["id"], idx)
    if window is None:
        # Read-only view of the would-be window (no materialization)
        from services.anniversary import window_bounds
        start, end = window_bounds(agent["_joined_date"], idx)
        window = {"window_index": idx, "window_start": start.isoformat(),
                  "window_end": end.isoformat(),
                  "company_dollar_accrued_cents": 0, "royalty_accrued_cents": 0,
                  "status": "OPEN"}

    from services.enrollment import covering_enrollment, plan_terms
    enrollment = covering_enrollment(agent["id"], closing)
    if enrollment is None:
        raise ApiError(ERR_NO_PLAN_ENROLLMENT, 409,
                       "no PlanEnrollment covers the deal's closing_date")
    if window["status"] == "CLOSED":
        raise ApiError(ERR_WINDOW_CLOSED, 409,
                       "the anniversary window containing closing_date is CLOSED")

    terms = plan_terms(enrollment["plan_id"], enrollment["plan_version"])
    breakdown = run_waterfall(deal, agent, terms, window)
    out = {"variant": "PROVISIONAL"}
    for k, v in breakdown.items():
        if k not in ("mentor_agent_id", "team_lead_agent_id"):
            out[k] = v
    return success_obj(out)


@bp.route("/brokerage/deals/<dealId>/settle", methods=["POST"])
@guard(roles=["TransactionCoordinator"])
def settle(user_id, role, dealId):
    deal = _get_deal(dealId)
    if deal["status"] == "SETTLED":
        raise ApiError(ERR_DEAL_HAS_SETTLEMENT, 409,
                       "a non-REVERSED settlement already exists for this deal")
    if deal["status"] != "CLOSED":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "only a CLOSED deal can be settled")
    if active_settlement_for_deal(dealId) is not None:
        raise ApiError(ERR_DEAL_HAS_SETTLEMENT, 409,
                       "a non-REVERSED settlement already exists for this deal")
    settlement = settle_deal(deal, user_id)
    return success_obj(public(settlement), status=201)


@bp.route("/brokerage/deals/<dealId>/unsettle", methods=["POST"])
@guard(roles=["TransactionCoordinator"])
def unsettle(user_id, role, dealId):
    deal = _get_deal(dealId)
    if deal["status"] != "SETTLED":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409, "only a SETTLED deal can be unsettled")
    unsettle_deal(deal)
    return success_obj(public(deal))
