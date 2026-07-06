"""Commercial Cleaning Janitorial API — Flask entry point."""
import os
from decimal import Decimal

from flask import Flask, request

import constants as C
import calculations as calc
from db import db
from errors import ApiError, err
from response import object_response, array_response, error_response
from helpers import (
    auth, body, pagination, paginate,
    require_str, require_int, require_number, require_enum, require_datetime,
    optional_enum, hours_between,
)
from lookups import get_account, get_child, get_fk, acct_rfp, acct_contract

app = Flask(__name__)

READ_ROLES_ALL = ["SalesRep", "OperationsManager", "AccountManager", "PlatformAdmin"]


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % e)


# --------------------------------------------------------------------------- #
# Health-axis helpers
# --------------------------------------------------------------------------- #
def adjust_health(account, delta):
    score = account.get("health_score", 100) + delta
    score = max(0, min(100, score))
    account["health_score"] = score
    db.touch(account)


def account_has_other_servicing(account_id, exclude_contract_id):
    for c in db.query("CleaningContract", account_id=account_id):
        if c["id"] == exclude_contract_id:
            continue
        if c["lifecycle_status"] == "SERVICING":
            return True
    return False


# =========================================================================== #
# Account
# =========================================================================== #
@app.route("/accounts", methods=["POST"])
def create_account():
    auth(["SalesRep"])
    data = body()
    legal_name = require_str(data, "legal_name")
    industry = require_enum(data, "industry", C.INDUSTRIES)
    rec = db.create("Account", {
        "legal_name": legal_name,
        "industry": industry,
        "owner_user_id": None,
        "lifecycle_stage": "PROSPECT",
        "health_score": 100,
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>", methods=["GET"])
def get_account_route(account_id):
    auth(READ_ROLES_ALL)
    return object_response(get_account(account_id))


@app.route("/accounts", methods=["GET"])
def list_accounts():
    auth(READ_ROLES_ALL)
    limit, offset = pagination()
    owner = request.args.get("owner_user_id")
    items = db.query("Account", owner_user_id=owner) if owner else db.query("Account")
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


# =========================================================================== #
# SiteContact
# =========================================================================== #
@app.route("/accounts/<account_id>/site-contacts", methods=["POST"])
def create_site_contact(account_id):
    auth(["SalesRep"])
    get_account(account_id)
    data = body()
    full_name = require_str(data, "full_name")
    avail_start = require_datetime(data, "avail_start_at")
    avail_end = require_datetime(data, "avail_end_at")
    if avail_end <= avail_start:
        raise err("ERR_INVALID_RANGE", "avail_end_at must be after avail_start_at")
    rec = db.create("SiteContact", {
        "account_id": account_id,
        "full_name": full_name,
        "avail_start_at": data["avail_start_at"],
        "avail_end_at": data["avail_end_at"],
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/site-contacts", methods=["GET"])
def list_site_contacts(account_id):
    auth(READ_ROLES_ALL)
    get_account(account_id)
    limit, offset = pagination()
    items = db.query("SiteContact", account_id=account_id)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


# =========================================================================== #
# RfpOpportunity
# =========================================================================== #
@app.route("/accounts/<account_id>/rfps", methods=["POST"])
def create_rfp(account_id):
    auth(["SalesRep"])
    get_account(account_id)
    data = body()
    title = require_str(data, "title")
    due_at = require_str(data, "due_at")
    require_datetime(data, "due_at")
    est = require_int(data, "estimated_total_sqft")
    if est <= 0:
        raise err("ERR_INVALID_RANGE", "estimated_total_sqft must be > 0")
    rec = db.create("RfpOpportunity", {
        "account_id": account_id,
        "title": title,
        "due_at": due_at,
        "estimated_total_sqft": est,
        "status": "OPEN",
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/rfps/<rfp_id>", methods=["GET"])
def get_rfp(account_id, rfp_id):
    auth(READ_ROLES_ALL)
    return object_response(acct_rfp(account_id, rfp_id))


@app.route("/accounts/<account_id>/rfps", methods=["GET"])
def list_rfps(account_id):
    auth(READ_ROLES_ALL)
    get_account(account_id)
    limit, offset = pagination()
    items = db.query("RfpOpportunity", account_id=account_id)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


# =========================================================================== #
# Walkthrough
# =========================================================================== #
@app.route("/accounts/<account_id>/rfps/<rfp_id>/walkthroughs", methods=["POST"])
def schedule_walkthrough(account_id, rfp_id):
    auth(["SalesRep"])
    rfp = acct_rfp(account_id, rfp_id)
    data = body()
    site_contact_id = require_str(data, "site_contact_id")
    sc = get_fk("SiteContact", site_contact_id, "SiteContact")
    start_at = require_datetime(data, "start_at")
    end_at = require_datetime(data, "end_at")
    if end_at <= start_at:
        raise err("ERR_INVALID_RANGE", "end_at must be after start_at")
    # state: RFP must be OPEN
    if rfp["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "RFP must be OPEN to schedule a walkthrough")
    # site contact must belong to same account
    if sc["account_id"] != account_id:
        raise err("ERR_SITE_CONTACT_MISMATCH", "site contact belongs to a different account")
    # window within availability (inclusive)
    from clock import parse_iso
    av_start = parse_iso(sc["avail_start_at"])
    av_end = parse_iso(sc["avail_end_at"])
    if start_at < av_start or end_at > av_end:
        raise err("ERR_OUTSIDE_AVAILABILITY", "walkthrough outside site contact availability")
    # closed-interval overlap on same site contact among SCHEDULED walkthroughs
    for wt in db.query("Walkthrough", site_contact_id=site_contact_id):
        if wt["status"] != "SCHEDULED":
            continue
        ex_start = parse_iso(wt["start_at"])
        ex_end = parse_iso(wt["end_at"])
        # closed intervals overlap if start <= other_end and other_start <= end
        if start_at <= ex_end and ex_start <= end_at:
            raise err("ERR_WALKTHROUGH_OVERLAP", "overlaps an existing scheduled walkthrough")
    rec = db.create("Walkthrough", {
        "rfp_id": rfp_id,
        "site_contact_id": site_contact_id,
        "start_at": data["start_at"],
        "end_at": data["end_at"],
        "status": "SCHEDULED",
    })
    rfp["status"] = "WALKTHROUGH_SCHEDULED"
    db.touch(rfp)
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/walkthroughs", methods=["GET"])
def list_walkthroughs(account_id, rfp_id):
    auth(READ_ROLES_ALL)
    acct_rfp(account_id, rfp_id)
    limit, offset = pagination()
    sc = request.args.get("site_contact_id")
    items = db.query("Walkthrough", rfp_id=rfp_id, site_contact_id=sc)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/walkthroughs/<wt_id>/complete", methods=["POST"])
def complete_walkthrough(account_id, rfp_id, wt_id):
    auth(["SalesRep"])
    rfp = acct_rfp(account_id, rfp_id)
    wt = get_child("Walkthrough", wt_id, "rfp_id", rfp_id, "Walkthrough")
    if wt["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Walkthrough must be SCHEDULED to complete")
    wt["status"] = "COMPLETED"
    db.touch(wt)
    if rfp["status"] == "WALKTHROUGH_SCHEDULED":
        rfp["status"] = "BIDDING"
        db.touch(rfp)
    return object_response(wt)


# =========================================================================== #
# ServiceArea
# =========================================================================== #
@app.route("/accounts/<account_id>/rfps/<rfp_id>/service-areas", methods=["POST"])
def create_service_area(account_id, rfp_id):
    auth(["SalesRep", "BidEstimator"])
    acct_rfp(account_id, rfp_id)
    data = body()
    label = require_str(data, "label")
    sqft = require_int(data, "sqft")
    soil = require_enum(data, "soil_level", C.SOIL_LEVELS)
    freq = require_int(data, "frequency_per_week")
    if sqft <= 0:
        raise err("ERR_INVALID_RANGE", "sqft must be > 0")
    if freq < 1 or freq > 7:
        raise err("ERR_INVALID_RANGE", "frequency_per_week must be 1..7")
    weekly = calc.area_weekly_hours_display({"sqft": sqft, "soil_level": soil,
                                             "frequency_per_week": freq}, "ESTIMATE")
    rec = db.create("ServiceArea", {
        "rfp_id": rfp_id,
        "label": label,
        "sqft": sqft,
        "soil_level": soil,
        "frequency_per_week": freq,
        "weekly_hours": weekly,
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/service-areas", methods=["GET"])
def list_service_areas(account_id, rfp_id):
    auth(["SalesRep", "BidEstimator", "OperationsManager", "AccountManager", "PlatformAdmin"])
    acct_rfp(account_id, rfp_id)
    limit, offset = pagination()
    items = db.query("ServiceArea", rfp_id=rfp_id)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


# =========================================================================== #
# BidEstimate
# =========================================================================== #
@app.route("/accounts/<account_id>/rfps/<rfp_id>/bid-estimates", methods=["POST"])
def create_bid_estimate(account_id, rfp_id):
    auth(["BidEstimator"])
    acct_rfp(account_id, rfp_id)
    data = body()
    base_wage = require_int(data, "base_wage_cents")
    margin = require_number(data, "target_margin_pct")
    loading = optional_enum(data, "loading_method", C.LOADING_METHODS, "ESTIMATE")
    if base_wage <= 0:
        raise err("ERR_INVALID_RANGE", "base_wage_cents must be > 0")
    if margin < 0 or margin > 0.90:
        raise err("ERR_INVALID_RANGE", "target_margin_pct must be 0.00..0.90")
    rec = db.create("BidEstimate", {
        "rfp_id": rfp_id,
        "base_wage_cents": base_wage,
        "target_margin_pct": margin,
        "loading_method": loading,
        "monthly_labor_hours": None,
        "labor_cost_cents": None,
        "supply_cost_cents": None,
        "total_cost_cents": None,
        "base_bid_cents": None,
        "status": "DRAFT",
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/bid-estimates/<bid_id>", methods=["GET"])
def get_bid_estimate(account_id, rfp_id, bid_id):
    auth(["BidEstimator", "SalesRep", "PlatformAdmin"])
    acct_rfp(account_id, rfp_id)
    return object_response(get_child("BidEstimate", bid_id, "rfp_id", rfp_id, "BidEstimate"))


@app.route("/accounts/<account_id>/rfps/<rfp_id>/bid-estimates", methods=["GET"])
def list_bid_estimates(account_id, rfp_id):
    auth(["BidEstimator", "SalesRep", "PlatformAdmin"])
    acct_rfp(account_id, rfp_id)
    limit, offset = pagination()
    items = db.query("BidEstimate", rfp_id=rfp_id)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/bid-estimates/<bid_id>/price", methods=["POST"])
def price_bid_estimate(account_id, rfp_id, bid_id):
    auth(["BidEstimator"])
    acct_rfp(account_id, rfp_id)
    bid = get_child("BidEstimate", bid_id, "rfp_id", rfp_id, "BidEstimate")
    areas = db.query("ServiceArea", rfp_id=rfp_id)
    if not areas:
        raise err("ERR_SERVICE_AREA_REQUIRED", "RFP has no service areas to price")
    result = calc.bid_buildup(areas, bid["base_wage_cents"], bid["target_margin_pct"],
                              bid["loading_method"])
    bid.update(result)
    bid["status"] = "PRICED"
    db.touch(bid)
    return object_response(bid)


# =========================================================================== #
# Proposal
# =========================================================================== #
@app.route("/accounts/<account_id>/rfps/<rfp_id>/proposals", methods=["POST"])
def create_proposal(account_id, rfp_id):
    auth(["SalesRep"])
    acct_rfp(account_id, rfp_id)
    data = body()
    bid_id = require_str(data, "bid_estimate_id")
    bid = get_fk("BidEstimate", bid_id, "BidEstimate")
    if bid["status"] != "PRICED":
        raise err("ERR_BID_NOT_PRICED", "referenced bid estimate is not PRICED")
    monthly_price, margin_pct = calc.proposal_pricing(bid["base_bid_cents"], bid["total_cost_cents"])
    rec = db.create("Proposal", {
        "rfp_id": rfp_id,
        "bid_estimate_id": bid_id,
        "monthly_price_cents": monthly_price,
        "achieved_margin_pct": margin_pct,
        "revision_round": 1,
        "status": "DRAFT",
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/proposals/<proposal_id>", methods=["GET"])
def get_proposal(account_id, rfp_id, proposal_id):
    auth(["SalesRep", "AccountManager", "PlatformAdmin"])
    acct_rfp(account_id, rfp_id)
    return object_response(get_child("Proposal", proposal_id, "rfp_id", rfp_id, "Proposal"))


@app.route("/accounts/<account_id>/rfps/<rfp_id>/proposals", methods=["GET"])
def list_proposals(account_id, rfp_id):
    auth(["SalesRep", "AccountManager", "PlatformAdmin"])
    acct_rfp(account_id, rfp_id)
    limit, offset = pagination()
    bid = request.args.get("bid_estimate_id")
    items = db.query("Proposal", rfp_id=rfp_id, bid_estimate_id=bid)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


def _proposal_and_rfp(account_id, rfp_id, proposal_id):
    rfp = acct_rfp(account_id, rfp_id)
    prop = get_child("Proposal", proposal_id, "rfp_id", rfp_id, "Proposal")
    return rfp, prop


@app.route("/accounts/<account_id>/rfps/<rfp_id>/proposals/<proposal_id>/send", methods=["POST"])
def send_proposal(account_id, rfp_id, proposal_id):
    auth(["SalesRep"])
    rfp, prop = _proposal_and_rfp(account_id, rfp_id, proposal_id)
    if prop["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Proposal must be DRAFT to send")
    if rfp["status"] != "BIDDING":
        raise err("ERR_INVALID_STATE", "RFP must be BIDDING to send proposal")
    if Decimal(str(prop["achieved_margin_pct"])) < C.MIN_MARGIN_PCT:
        raise err("ERR_MARGIN_BELOW_FLOOR", "achieved margin below floor")
    prop["status"] = "SENT"
    db.touch(prop)
    rfp["status"] = "PROPOSED"
    db.touch(rfp)
    return object_response(prop)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/proposals/<proposal_id>/revise", methods=["POST"])
def revise_proposal(account_id, rfp_id, proposal_id):
    auth(["SalesRep"])
    rfp, prop = _proposal_and_rfp(account_id, rfp_id, proposal_id)
    if prop["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Proposal must be SENT to revise")
    prop["status"] = "DRAFT"
    prop["revision_round"] = prop["revision_round"] + 1
    db.touch(prop)
    rfp["status"] = "BIDDING"
    db.touch(rfp)
    return object_response(prop)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/proposals/<proposal_id>/accept", methods=["POST"])
def accept_proposal(account_id, rfp_id, proposal_id):
    auth(["SalesRep"])
    rfp, prop = _proposal_and_rfp(account_id, rfp_id, proposal_id)
    if prop["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Proposal must be SENT to accept")
    prop["status"] = "ACCEPTED"
    db.touch(prop)
    rfp["status"] = "WON"
    db.touch(rfp)
    return object_response(prop)


@app.route("/accounts/<account_id>/rfps/<rfp_id>/proposals/<proposal_id>/decline", methods=["POST"])
def decline_proposal(account_id, rfp_id, proposal_id):
    auth(["SalesRep"])
    rfp, prop = _proposal_and_rfp(account_id, rfp_id, proposal_id)
    if prop["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Proposal must be SENT to decline")
    prop["status"] = "DECLINED"
    db.touch(prop)
    rfp["status"] = "LOST"
    db.touch(rfp)
    return object_response(prop)


# =========================================================================== #
# CleaningContract
# =========================================================================== #
@app.route("/accounts/<account_id>/contracts", methods=["POST"])
def create_contract(account_id):
    auth(["SalesRep"])
    get_account(account_id)
    data = body()
    proposal_id = require_str(data, "proposal_id")
    prop = get_fk("Proposal", proposal_id, "Proposal")
    term = require_int(data, "term_months")
    if term < 1:
        raise err("ERR_INVALID_RANGE", "term_months must be >= 1")
    rec = db.create("CleaningContract", {
        "account_id": account_id,
        "proposal_id": proposal_id,
        "monthly_value_cents": None,
        "term_months": term,
        "lifecycle_status": "DRAFT",
        "billing_status": "PENDING",
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/contracts/<contract_id>", methods=["GET"])
def get_contract(account_id, contract_id):
    auth(READ_ROLES_ALL)
    return object_response(acct_contract(account_id, contract_id))


@app.route("/accounts/<account_id>/contracts", methods=["GET"])
def list_contracts(account_id):
    auth(READ_ROLES_ALL)
    get_account(account_id)
    limit, offset = pagination()
    prop = request.args.get("proposal_id")
    items = db.query("CleaningContract", account_id=account_id, proposal_id=prop)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


@app.route("/accounts/<account_id>/contracts/<contract_id>/sign", methods=["POST"])
def sign_contract(account_id, contract_id):
    auth(["SalesRep"])
    contract = acct_contract(account_id, contract_id)
    if contract["lifecycle_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Contract must be DRAFT to sign")
    prop = db.get("Proposal", contract["proposal_id"])
    if prop is None or prop["status"] != "ACCEPTED":
        raise err("ERR_PROPOSAL_NOT_ACCEPTED", "linked proposal is not ACCEPTED")
    # snapshot monthly value
    contract["monthly_value_cents"] = prop["monthly_price_cents"]
    contract["lifecycle_status"] = "SIGNED"
    db.touch(contract)
    # create StartupPlan PLANNING with planned_monthly_hours snapshot via the bid
    bid = db.get("BidEstimate", prop["bid_estimate_id"])
    planned = bid["monthly_labor_hours"] if bid else 0.0
    db.create("StartupPlan", {
        "contract_id": contract_id,
        "planned_monthly_hours": planned,
        "allocated_hours": 0.0,
        "go_live_at": None,
        "status": "PLANNING",
    })
    return object_response(contract)


@app.route("/accounts/<account_id>/contracts/<contract_id>/end", methods=["POST"])
def end_contract(account_id, contract_id):
    auth(["AccountManager"])
    contract = acct_contract(account_id, contract_id)
    if contract["lifecycle_status"] != "SERVICING":
        raise err("ERR_INVALID_STATE", "Contract must be SERVICING to end")
    contract["lifecycle_status"] = "ENDED"
    contract["billing_status"] = "CLOSED"
    db.touch(contract)
    account = db.get("Account", account_id)
    if not account_has_other_servicing(account_id, contract_id):
        account["lifecycle_stage"] = "CHURNED"
        db.touch(account)
    return object_response(contract)


@app.route("/accounts/<account_id>/contracts/<contract_id>/billing/suspend", methods=["POST"])
def suspend_billing(account_id, contract_id):
    auth(["AccountManager"])
    contract = acct_contract(account_id, contract_id)
    if contract["billing_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "billing must be ACTIVE to suspend")
    if contract["lifecycle_status"] != "SERVICING":
        raise err("ERR_CONTRACT_NOT_SERVICING", "contract must be SERVICING")
    contract["billing_status"] = "SUSPENDED"
    db.touch(contract)
    adjust_health(db.get("Account", account_id), -C.HEALTH_SUSPEND_PENALTY)
    return object_response(contract)


@app.route("/accounts/<account_id>/contracts/<contract_id>/billing/resume", methods=["POST"])
def resume_billing(account_id, contract_id):
    auth(["AccountManager"])
    contract = acct_contract(account_id, contract_id)
    if contract["billing_status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "billing must be SUSPENDED to resume")
    contract["billing_status"] = "ACTIVE"
    db.touch(contract)
    adjust_health(db.get("Account", account_id), C.HEALTH_SUSPEND_PENALTY)
    return object_response(contract)


@app.route("/accounts/<account_id>/contracts/<contract_id>/upsell", methods=["POST"])
def upsell_contract(account_id, contract_id):
    auth(["AccountManager"])
    contract = acct_contract(account_id, contract_id)
    data = body()
    upsell_type = require_str(data, "upsell_type")
    addon = require_int(data, "monthly_addon_cents")
    expected = require_int(data, "expected_contract_version")
    if contract["lifecycle_status"] != "SERVICING" or addon <= 0:
        raise err("ERR_UPSELL_INVALID", "contract not SERVICING or addon <= 0")
    if expected != contract["version"]:
        raise err("ERR_STALE_VERSION", "expected_contract_version mismatch")
    contract["monthly_value_cents"] = (contract["monthly_value_cents"] or 0) + addon
    db.touch(contract)
    adjust_health(db.get("Account", account_id), C.HEALTH_UPSELL_BONUS)
    return object_response(contract)


# =========================================================================== #
# StartupPlan
# =========================================================================== #
def _acct_plan(account_id, plan_id):
    get_account(account_id)
    plan = db.get("StartupPlan", plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "StartupPlan not found")
    contract = db.get("CleaningContract", plan["contract_id"])
    if contract is None or contract["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "StartupPlan not found under account")
    return plan, contract


@app.route("/accounts/<account_id>/startup-plans/<plan_id>", methods=["GET"])
def get_startup_plan(account_id, plan_id):
    auth(["OperationsManager", "SalesRep", "PlatformAdmin"])
    plan, _ = _acct_plan(account_id, plan_id)
    return object_response(plan)


@app.route("/accounts/<account_id>/startup-plans", methods=["GET"])
def list_startup_plans(account_id):
    auth(["OperationsManager", "SalesRep", "PlatformAdmin"])
    get_account(account_id)
    limit, offset = pagination()
    contract_filter = request.args.get("contract_id")
    contract_ids = {c["id"] for c in db.query("CleaningContract", account_id=account_id)}
    items = [p for p in db.all("StartupPlan") if p["contract_id"] in contract_ids]
    if contract_filter:
        items = [p for p in items if p["contract_id"] == contract_filter]
    items.sort(key=lambda r: r["_seq"])
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


@app.route("/accounts/<account_id>/startup-plans/<plan_id>/crew", methods=["POST"])
def assign_crew_shift(account_id, plan_id):
    auth(["OperationsManager"])
    plan, contract = _acct_plan(account_id, plan_id)
    data = body()
    crew_id = require_str(data, "crew_id")
    crew = get_fk("Crew", crew_id, "Crew")
    start_at = require_datetime(data, "start_at")
    end_at = require_datetime(data, "end_at")
    if end_at <= start_at:
        raise err("ERR_INVALID_RANGE", "end_at must be after start_at")
    first_shift = plan["status"] == "PLANNING"
    if plan["status"] not in ("PLANNING", "CREWED"):
        raise err("ERR_INVALID_STATE", "plan must be PLANNING or CREWED to assign")
    if first_shift and contract["lifecycle_status"] != "SIGNED":
        raise err("ERR_CONTRACT_NOT_SIGNED", "contract must be SIGNED for first shift")
    if crew["status"] != "AVAILABLE":
        raise err("ERR_CREW_UNAVAILABLE", "crew is not AVAILABLE")
    # half-open + travel buffer overlap on same crew among ASSIGNED shifts
    from clock import parse_iso
    from datetime import timedelta
    buf = timedelta(minutes=C.CREW_TRAVEL_BUFFER_MIN)
    for s in db.query("CrewShift", crew_id=crew_id):
        if s["status"] != "ASSIGNED":
            continue
        ex_start = parse_iso(s["start_at"])
        ex_end = parse_iso(s["end_at"]) + buf
        # half-open [start, end+buf): overlap if start < ex_end and ex_start < (end+buf)
        if start_at < ex_end and ex_start < (end_at + buf):
            raise err("ERR_SHIFT_OVERLAP", "shift overlaps existing assigned shift on crew")
    sh = calc_hours(start_at, end_at)
    shift = db.create("CrewShift", {
        "startup_plan_id": plan_id,
        "crew_id": crew_id,
        "start_at": data["start_at"],
        "end_at": data["end_at"],
        "shift_hours": sh,
        "status": "ASSIGNED",
    })
    # recompute allocated_hours
    plan["allocated_hours"] = calc.allocated_hours(db.query("CrewShift", startup_plan_id=plan_id))
    if plan["status"] == "PLANNING":
        plan["status"] = "CREWED"
    db.touch(plan)
    if first_shift and contract["lifecycle_status"] == "SIGNED":
        contract["lifecycle_status"] = "STARTUP"
        db.touch(contract)
    return object_response(shift, 201)


def calc_hours(start_at, end_at):
    from helpers import rhu_2dp
    return rhu_2dp(hours_between(start_at, end_at))


@app.route("/accounts/<account_id>/startup-plans/<plan_id>/mark-ready", methods=["POST"])
def mark_ready(account_id, plan_id):
    auth(["OperationsManager"])
    plan, _ = _acct_plan(account_id, plan_id)
    if plan["status"] != "CREWED":
        raise err("ERR_INVALID_STATE", "plan must be CREWED to mark ready")
    if Decimal(str(plan["allocated_hours"])) < Decimal(str(plan["planned_monthly_hours"])):
        raise err("ERR_HOURS_UNDERALLOCATED", "allocated hours below planned")
    plan["status"] = "READY"
    db.touch(plan)
    return object_response(plan)


@app.route("/accounts/<account_id>/startup-plans/<plan_id>/go-live", methods=["POST"])
def go_live(account_id, plan_id):
    user_id, role = auth(["OperationsManager"])
    plan, contract = _acct_plan(account_id, plan_id)
    if plan["status"] != "READY":
        raise err("ERR_STARTUP_NOT_READY", "plan must be READY to go live")
    if contract["lifecycle_status"] != "STARTUP":
        raise err("ERR_INVALID_STATE", "contract must be STARTUP to go live")
    plan["status"] = "LIVE"
    db.touch(plan)
    contract["lifecycle_status"] = "SERVICING"
    contract["billing_status"] = "ACTIVE"
    db.touch(contract)
    account = db.get("Account", account_id)
    account["lifecycle_stage"] = "ACTIVE_CUSTOMER"
    if account.get("owner_user_id") is None:
        account["owner_user_id"] = user_id
    db.touch(account)
    return object_response(plan)


@app.route("/accounts/<account_id>/startup-plans/<plan_id>/abort", methods=["POST"])
def abort_plan(account_id, plan_id):
    auth(["OperationsManager"])
    plan, _ = _acct_plan(account_id, plan_id)
    if plan["status"] not in ("PLANNING", "CREWED", "READY"):
        raise err("ERR_INVALID_STATE", "plan cannot be aborted from its current state")
    for s in db.query("CrewShift", startup_plan_id=plan_id):
        if s["status"] == "ASSIGNED":
            s["status"] = "CANCELLED"
    plan["allocated_hours"] = calc.allocated_hours(db.query("CrewShift", startup_plan_id=plan_id))
    plan["status"] = "ABORTED"
    db.touch(plan)
    adjust_health(db.get("Account", account_id), -C.HEALTH_ABORT_PENALTY)
    return object_response(plan)


# =========================================================================== #
# Crew
# =========================================================================== #
@app.route("/crews", methods=["POST"])
def create_crew():
    auth(["OperationsManager"])
    data = body()
    name = require_str(data, "name")
    cap = require_number(data, "weekly_capacity_hours")
    if cap <= 0:
        raise err("ERR_INVALID_RANGE", "weekly_capacity_hours must be > 0")
    rec = db.create("Crew", {
        "name": name,
        "weekly_capacity_hours": cap,
        "status": "AVAILABLE",
    })
    return object_response(rec, 201)


@app.route("/crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    auth(["OperationsManager", "PlatformAdmin"])
    rec = db.get("Crew", crew_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Crew not found")
    return object_response(rec)


@app.route("/crews/<crew_id>/retire", methods=["POST"])
def retire_crew(crew_id):
    auth(["OperationsManager"])
    rec = db.get("Crew", crew_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Crew not found")
    if rec["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "crew must be AVAILABLE to retire")
    rec["status"] = "RETIRED"
    return object_response(rec)


# =========================================================================== #
# CrewShift
# =========================================================================== #
@app.route("/accounts/<account_id>/startup-plans/<plan_id>/crew-shifts", methods=["GET"])
def list_plan_crew_shifts(account_id, plan_id):
    auth(["OperationsManager", "SalesRep", "PlatformAdmin"])
    _acct_plan(account_id, plan_id)
    limit, offset = pagination()
    crew = request.args.get("crew_id")
    items = db.query("CrewShift", startup_plan_id=plan_id, crew_id=crew)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


@app.route("/accounts/<account_id>/crew-shifts", methods=["GET"])
def list_crew_shifts(account_id):
    auth(["OperationsManager", "PlatformAdmin"])
    get_account(account_id)
    limit, offset = pagination()
    crew = request.args.get("crew_id")
    plan = request.args.get("startup_plan_id")
    contract_ids = {c["id"] for c in db.query("CleaningContract", account_id=account_id)}
    plan_ids = {p["id"] for p in db.all("StartupPlan") if p["contract_id"] in contract_ids}
    items = [s for s in db.all("CrewShift") if s["startup_plan_id"] in plan_ids]
    if crew:
        items = [s for s in items if s["crew_id"] == crew]
    if plan:
        items = [s for s in items if s["startup_plan_id"] == plan]
    items.sort(key=lambda r: r["_seq"])
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


@app.route("/accounts/<account_id>/crew-shifts/<shift_id>/cancel", methods=["POST"])
def cancel_crew_shift(account_id, shift_id):
    auth(["OperationsManager"])
    get_account(account_id)
    shift = db.get("CrewShift", shift_id)
    if shift is None:
        raise err("ERR_NOT_FOUND", "CrewShift not found")
    plan = db.get("StartupPlan", shift["startup_plan_id"])
    contract = db.get("CleaningContract", plan["contract_id"]) if plan else None
    if contract is None or contract["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "CrewShift not found under account")
    if shift["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "shift must be ASSIGNED to cancel")
    if plan["status"] == "LIVE":
        raise err("ERR_INVALID_STATE", "cannot cancel a shift on a LIVE plan")
    shift["status"] = "CANCELLED"
    plan["allocated_hours"] = calc.allocated_hours(db.query("CrewShift", startup_plan_id=plan["id"]))
    db.touch(plan)
    return object_response(shift)


# =========================================================================== #
# SupplyBudget
# =========================================================================== #
@app.route("/accounts/<account_id>/contracts/<contract_id>/supply-budget", methods=["POST"])
def create_supply_budget(account_id, contract_id):
    auth(["OperationsManager"])
    acct_contract(account_id, contract_id)
    data = body()
    total = require_int(data, "total_cents")
    if total <= 0:
        raise err("ERR_INVALID_RANGE", "total_cents must be > 0")
    rec = db.create("SupplyBudget", {
        "contract_id": contract_id,
        "total_cents": total,
        "committed_cents": 0,
        "remaining_cents": total,
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/contracts/<contract_id>/supply-budget", methods=["GET"])
def list_contract_supply_budget(account_id, contract_id):
    auth(["OperationsManager", "AccountManager", "PlatformAdmin"])
    acct_contract(account_id, contract_id)
    limit, offset = pagination()
    items = db.query("SupplyBudget", contract_id=contract_id)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


def _acct_budget(account_id, budget_id):
    get_account(account_id)
    budget = db.get("SupplyBudget", budget_id)
    if budget is None:
        raise err("ERR_NOT_FOUND", "SupplyBudget not found")
    contract = db.get("CleaningContract", budget["contract_id"])
    if contract is None or contract["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "SupplyBudget not found under account")
    return budget


@app.route("/accounts/<account_id>/supply-budgets/<budget_id>", methods=["GET"])
def get_supply_budget(account_id, budget_id):
    auth(["OperationsManager", "AccountManager", "PlatformAdmin"])
    return object_response(_acct_budget(account_id, budget_id))


# =========================================================================== #
# SupplyRequisition
# =========================================================================== #
@app.route("/accounts/<account_id>/supply-budgets/<budget_id>/requisitions", methods=["POST"])
def create_requisition(account_id, budget_id):
    auth(["OperationsManager"])
    budget = _acct_budget(account_id, budget_id)
    data = body()
    item_label = require_str(data, "item_label")
    amount = require_int(data, "amount_cents")
    if amount <= 0:
        raise err("ERR_INVALID_RANGE", "amount_cents must be > 0")
    rec = db.create("SupplyRequisition", {
        "supply_budget_id": budget_id,
        "item_label": item_label,
        "amount_cents": amount,
        "status": "REQUESTED",
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/supply-budgets/<budget_id>/requisitions", methods=["GET"])
def list_budget_requisitions(account_id, budget_id):
    auth(["OperationsManager", "AccountManager", "PlatformAdmin"])
    _acct_budget(account_id, budget_id)
    limit, offset = pagination()
    items = db.query("SupplyRequisition", supply_budget_id=budget_id)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


def _acct_req(account_id, req_id):
    get_account(account_id)
    req = db.get("SupplyRequisition", req_id)
    if req is None:
        raise err("ERR_NOT_FOUND", "SupplyRequisition not found")
    budget = db.get("SupplyBudget", req["supply_budget_id"])
    contract = db.get("CleaningContract", budget["contract_id"]) if budget else None
    if contract is None or contract["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "SupplyRequisition not found under account")
    return req, budget


@app.route("/accounts/<account_id>/supply-requisitions/<req_id>", methods=["GET"])
def get_requisition(account_id, req_id):
    auth(["OperationsManager", "AccountManager", "PlatformAdmin"])
    req, _ = _acct_req(account_id, req_id)
    return object_response(req)


@app.route("/accounts/<account_id>/supply-requisitions/<req_id>/approve", methods=["POST"])
def approve_requisition(account_id, req_id):
    auth(["OperationsManager"])
    req, budget = _acct_req(account_id, req_id)
    data = body()
    expected = require_int(data, "expected_supply_budget_version")
    if req["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "requisition must be REQUESTED to approve")
    if req["amount_cents"] > budget["remaining_cents"]:
        raise err("ERR_BUDGET_EXCEEDED", "amount exceeds remaining budget")
    if expected != budget["version"]:
        raise err("ERR_STALE_VERSION", "expected_supply_budget_version mismatch")
    req["status"] = "APPROVED"
    db.touch(req)
    budget["committed_cents"] += req["amount_cents"]
    budget["remaining_cents"] = budget["total_cents"] - budget["committed_cents"]
    db.touch(budget)
    return object_response(req)


@app.route("/accounts/<account_id>/supply-requisitions/<req_id>/cancel", methods=["POST"])
def cancel_requisition(account_id, req_id):
    auth(["OperationsManager"])
    req, budget = _acct_req(account_id, req_id)
    if req["status"] not in ("REQUESTED", "APPROVED"):
        raise err("ERR_INVALID_STATE", "requisition cannot be cancelled from its state")
    was_approved = req["status"] == "APPROVED"
    req["status"] = "CANCELLED"
    db.touch(req)
    if was_approved:
        budget["committed_cents"] -= req["amount_cents"]
        budget["remaining_cents"] = budget["total_cents"] - budget["committed_cents"]
        db.touch(budget)
    return object_response(req)


# =========================================================================== #
# RenewalCycle
# =========================================================================== #
@app.route("/accounts/<account_id>/contracts/<contract_id>/renewal-cycles", methods=["POST"])
def create_renewal_cycle(account_id, contract_id):
    auth(["AccountManager"])
    contract = acct_contract(account_id, contract_id)
    data = body()
    method = require_enum(data, "escalation_method", C.ESCALATION_METHODS)
    if contract["lifecycle_status"] != "SERVICING":
        raise err("ERR_CONTRACT_NOT_SERVICING", "contract must be SERVICING for renewal")
    proposed = calc.renewal_escalation(contract["monthly_value_cents"], method)
    rec = db.create("RenewalCycle", {
        "contract_id": contract_id,
        "escalation_method": method,
        "proposed_monthly_cents": proposed,
        "status": "DRAFT",
    })
    return object_response(rec, 201)


@app.route("/accounts/<account_id>/contracts/<contract_id>/renewal-cycles", methods=["GET"])
def list_contract_renewals(account_id, contract_id):
    auth(["AccountManager", "PlatformAdmin"])
    acct_contract(account_id, contract_id)
    limit, offset = pagination()
    items = db.query("RenewalCycle", contract_id=contract_id)
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


def _acct_cycle(account_id, cycle_id):
    get_account(account_id)
    cycle = db.get("RenewalCycle", cycle_id)
    if cycle is None:
        raise err("ERR_NOT_FOUND", "RenewalCycle not found")
    contract = db.get("CleaningContract", cycle["contract_id"])
    if contract is None or contract["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "RenewalCycle not found under account")
    return cycle, contract


@app.route("/accounts/<account_id>/renewal-cycles/<cycle_id>", methods=["GET"])
def get_renewal_cycle(account_id, cycle_id):
    auth(["AccountManager", "PlatformAdmin"])
    cycle, _ = _acct_cycle(account_id, cycle_id)
    return object_response(cycle)


@app.route("/accounts/<account_id>/renewal-cycles/<cycle_id>/offer", methods=["POST"])
def offer_renewal(account_id, cycle_id):
    auth(["AccountManager"])
    cycle, contract = _acct_cycle(account_id, cycle_id)
    if cycle["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "cycle must be DRAFT to offer")
    if contract["lifecycle_status"] != "SERVICING":
        raise err("ERR_CONTRACT_NOT_SERVICING", "contract must be SERVICING")
    cycle["status"] = "OFFERED"
    db.touch(cycle)
    return object_response(cycle)


@app.route("/accounts/<account_id>/renewal-cycles/<cycle_id>/accept", methods=["POST"])
def accept_renewal(account_id, cycle_id):
    auth(["AccountManager"])
    cycle, contract = _acct_cycle(account_id, cycle_id)
    data = body()
    expected = require_int(data, "expected_contract_version")
    if cycle["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "cycle must be OFFERED to accept")
    if expected != contract["version"]:
        raise err("ERR_STALE_VERSION", "expected_contract_version mismatch")
    cycle["status"] = "RENEWED"
    db.touch(cycle)
    contract["monthly_value_cents"] = cycle["proposed_monthly_cents"]
    db.touch(contract)
    adjust_health(db.get("Account", account_id), C.HEALTH_RENEW_BONUS)
    return object_response(cycle)


@app.route("/accounts/<account_id>/renewal-cycles/<cycle_id>/lapse", methods=["POST"])
def lapse_renewal(account_id, cycle_id):
    auth(["AccountManager"])
    cycle, contract = _acct_cycle(account_id, cycle_id)
    if cycle["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "cycle must be OFFERED to lapse")
    cycle["status"] = "LAPSED"
    db.touch(cycle)
    contract["lifecycle_status"] = "ENDED"
    contract["billing_status"] = "CLOSED"
    db.touch(contract)
    account = db.get("Account", account_id)
    if not account_has_other_servicing(account_id, contract["id"]):
        account["lifecycle_stage"] = "CHURNED"
        db.touch(account)
    adjust_health(account, -C.HEALTH_LAPSE_PENALTY)
    return object_response(cycle)


# =========================================================================== #
# Flat read surface (segment-derivation single GET + filtered list GET)
# =========================================================================== #
def _flat_get(kind, rid, roles, label):
    auth(roles)
    rec = db.get(kind, rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    return object_response(rec)


def _flat_list(kind, roles, filters):
    auth(roles)
    limit, offset = pagination()
    args = {f: request.args.get(f) for f in filters}
    items = db.query(kind, **{k: v for k, v in args.items() if v is not None})
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)


_ALL5 = ["SalesRep", "OperationsManager", "AccountManager", "BidEstimator", "PlatformAdmin"]


@app.route("/accounts/rfp-records/<rfp_id>", methods=["GET"])
def flat_get_rfp(rfp_id):
    return _flat_get("RfpOpportunity", rfp_id, _ALL5, "RFP")


@app.route("/accounts/rfp-records", methods=["GET"])
def flat_list_rfp():
    return _flat_list("RfpOpportunity", _ALL5, ["account_id"])


@app.route("/accounts/site-contacts/<contact_id>", methods=["GET"])
def flat_get_site_contact(contact_id):
    return _flat_get("SiteContact", contact_id, READ_ROLES_ALL, "SiteContact")


@app.route("/accounts/site-contacts", methods=["GET"])
def flat_list_site_contact():
    return _flat_list("SiteContact", READ_ROLES_ALL, ["account_id"])


@app.route("/accounts/walkthrough-records/<wt_id>", methods=["GET"])
def flat_get_walkthrough(wt_id):
    return _flat_get("Walkthrough", wt_id, READ_ROLES_ALL, "Walkthrough")


@app.route("/accounts/walkthrough-records", methods=["GET"])
def flat_list_walkthrough():
    return _flat_list("Walkthrough", READ_ROLES_ALL, ["rfp_id", "site_contact_id"])


@app.route("/accounts/service-area-records/<area_id>", methods=["GET"])
def flat_get_service_area(area_id):
    return _flat_get("ServiceArea", area_id, ["SalesRep", "BidEstimator", "PlatformAdmin"], "ServiceArea")


@app.route("/accounts/service-area-records", methods=["GET"])
def flat_list_service_area():
    return _flat_list("ServiceArea",
                      ["SalesRep", "BidEstimator", "OperationsManager", "AccountManager", "PlatformAdmin"],
                      ["rfp_id"])


@app.route("/accounts/bid-estimate-records/<bid_id>", methods=["GET"])
def flat_get_bid_estimate(bid_id):
    return _flat_get("BidEstimate", bid_id, ["BidEstimator", "SalesRep", "PlatformAdmin"], "BidEstimate")


@app.route("/accounts/bid-estimate-records", methods=["GET"])
def flat_list_bid_estimate():
    return _flat_list("BidEstimate", ["BidEstimator", "SalesRep", "PlatformAdmin"], ["rfp_id"])


@app.route("/accounts/proposal-records/<proposal_id>", methods=["GET"])
def flat_get_proposal(proposal_id):
    return _flat_get("Proposal", proposal_id, ["SalesRep", "AccountManager", "PlatformAdmin"], "Proposal")


@app.route("/accounts/proposal-records", methods=["GET"])
def flat_list_proposal():
    return _flat_list("Proposal", ["SalesRep", "AccountManager", "PlatformAdmin"],
                      ["rfp_id", "bid_estimate_id"])


@app.route("/accounts/contract-records/<contract_id>", methods=["GET"])
def flat_get_contract(contract_id):
    return _flat_get("CleaningContract", contract_id, READ_ROLES_ALL, "Contract")


@app.route("/accounts/contract-records", methods=["GET"])
def flat_list_contract():
    return _flat_list("CleaningContract", READ_ROLES_ALL, ["account_id", "proposal_id"])


@app.route("/accounts/startup-plan-records/<plan_id>", methods=["GET"])
def flat_get_startup_plan(plan_id):
    return _flat_get("StartupPlan", plan_id, ["OperationsManager", "SalesRep", "PlatformAdmin"], "StartupPlan")


@app.route("/accounts/startup-plan-records", methods=["GET"])
def flat_list_startup_plan():
    return _flat_list("StartupPlan", ["OperationsManager", "SalesRep", "PlatformAdmin"], ["contract_id"])


@app.route("/accounts/crew-shift-records/<shift_id>", methods=["GET"])
def flat_get_crew_shift(shift_id):
    return _flat_get("CrewShift", shift_id, ["OperationsManager", "SalesRep", "PlatformAdmin"], "CrewShift")


@app.route("/accounts/crew-shift-records", methods=["GET"])
def flat_list_crew_shift():
    return _flat_list("CrewShift", ["OperationsManager", "SalesRep", "PlatformAdmin"],
                      ["startup_plan_id", "crew_id"])


@app.route("/accounts/supply-budget-records/<budget_id>", methods=["GET"])
def flat_get_supply_budget(budget_id):
    return _flat_get("SupplyBudget", budget_id, ["OperationsManager", "AccountManager", "PlatformAdmin"], "SupplyBudget")


@app.route("/accounts/supply-budget-records", methods=["GET"])
def flat_list_supply_budget():
    return _flat_list("SupplyBudget", ["OperationsManager", "AccountManager", "PlatformAdmin"], ["contract_id"])


@app.route("/accounts/supply-requisition-records/<req_id>", methods=["GET"])
def flat_get_supply_requisition(req_id):
    return _flat_get("SupplyRequisition", req_id, ["OperationsManager", "AccountManager", "PlatformAdmin"], "SupplyRequisition")


@app.route("/accounts/supply-requisition-records", methods=["GET"])
def flat_list_supply_requisition():
    return _flat_list("SupplyRequisition", ["OperationsManager", "AccountManager", "PlatformAdmin"], ["supply_budget_id"])


@app.route("/accounts/renewal-cycle-records/<cycle_id>", methods=["GET"])
def flat_get_renewal_cycle(cycle_id):
    return _flat_get("RenewalCycle", cycle_id, ["AccountManager", "PlatformAdmin"], "RenewalCycle")


@app.route("/accounts/renewal-cycle-records", methods=["GET"])
def flat_list_renewal_cycle():
    return _flat_list("RenewalCycle", ["AccountManager", "PlatformAdmin"], ["contract_id"])


@app.route("/accounts/crew-records/<crew_id>", methods=["GET"])
def flat_get_crew(crew_id):
    return _flat_get("Crew", crew_id, ["OperationsManager", "PlatformAdmin"], "Crew")


# =========================================================================== #
# Logical clock
# =========================================================================== #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlatformAdmin"])
    data = body()
    iso = require_str(data, "to_iso8601")
    try:
        from clock import parse_iso
        parse_iso(iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601")
    db.clock.set(iso)
    return object_response({"now": iso})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
