"""Last-time-buy campaigns, the approval cycle and the dealer allocation waterfall."""
from flask import Blueprint

import auth
import calc
import domain
import envelope
import serializers
import store
from errors import ApiError
from routes.registry import fk

bp = Blueprint("campaigns", __name__)

LTB_METHODS = {"DEMAND_DECAY", "FLAT_RATE"}
CAMPAIGN_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED",
                     "ALLOCATING", "CLOSED", "CANCELLED"}
ALLOCATION_STATUSES = {"PENDING", "GRANTED", "PARTIALLY_GRANTED", "DENIED", "WITHDRAWN"}
LIVE_CAMPAIGN_STATES = ("SUBMITTED", "APPROVED", "ALLOCATING")


def _check_windows(part_id, start, end, exclude_id=None):
    """Priority 16 (half-open intersection) then priority 17 (30-day cooldown)."""
    others = []
    for camp in store.campaigns.values():
        if camp["part_id"] != part_id or camp["id"] == exclude_id:
            continue
        if camp["status"] not in LIVE_CAMPAIGN_STATES:
            continue
        others.append(camp)

    for other in others:
        if start < other["ltb_window_end"] and other["ltb_window_start"] < end:
            raise ApiError("ERR_LTB_WINDOW_OVERLAP")

    cooldown = store.days(calc.LTB_COOLDOWN_DAYS)
    for other in others:
        if not (start >= other["ltb_window_end"] + cooldown
                or end + cooldown <= other["ltb_window_start"]):
            raise ApiError("ERR_LTB_COOLDOWN_VIOLATION")


def _snapshot_demand(part):
    forecast = domain.current_forecast(part["id"], 12)
    if forecast is None:
        raise ApiError("ERR_FORECAST_INPUT_EMPTY")
    return forecast["forecast_units"]


# ------------------------------------------------------------ campaigns ----
@bp.post("/aftermarket/last-time-buy-campaigns")
def create_campaign():
    auth.require("AftermarketPlanner")
    data = auth.body()
    part = fk(data, "part_id", domain.get_part)
    part_id = auth.req_id(data, "part_id")
    if part is None:
        part = domain.get_part(part_id)

    method = auth.req_enum(data, "method", LTB_METHODS)
    coverage_years = auth.req_int(data, "coverage_years", minimum=1,
                                  maximum=calc.MAX_COVERAGE_YEARS)
    window_start = auth.req_datetime(data, "ltb_window_start")
    window_end = auth.req_datetime(data, "ltb_window_end")
    expected_part_version = auth.req_int(data, "expected_part_version")

    if expected_part_version != part["version"]:
        raise ApiError("ERR_STALE_PART_VERSION")
    if part["lifecycle_state"] == "SUPERSEDED":
        raise ApiError("ERR_PART_SUPERSEDED")

    _check_windows(part["id"], window_start, window_end)

    annual_demand_units = _snapshot_demand(part)
    cover = part["on_hand_units"] + part["in_transit_units"]
    proposed_qty = calc.ltb_quantity(method, annual_demand_units, coverage_years, cover)

    for camp in store.sort_created(list(store.campaigns.values())):
        if camp["part_id"] == part["id"] and camp["status"] == "DRAFT":
            camp["status"] = "CANCELLED"
            store.touch(camp)

    rec = store.new_record("LastTimeBuyCampaign", {
        "part_id": part["id"],
        "method": method,
        "coverage_years": coverage_years,
        "ltb_window_start": window_start,
        "ltb_window_end": window_end,
        "annual_demand_units": annual_demand_units,
        "proposed_qty": proposed_qty,
        "approved_qty": 0,
        "remaining_qty": 0,
        "status": "DRAFT",
        "revision_index": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "rejection_reason": None,
    })
    store.campaigns[rec["id"]] = rec
    store.touch(part)
    return envelope.created(serializers.campaign(rec))


@bp.get("/aftermarket/last-time-buy-campaigns/<campaign_id>")
def read_campaign(campaign_id):
    auth.require("AftermarketPlanner", "InventoryController", "DealerUser", "PlatformAdmin")
    return envelope.ok(serializers.campaign(domain.get_campaign(campaign_id)))


@bp.get("/aftermarket/last-time-buy-campaigns")
def list_campaigns():
    auth.require("AftermarketPlanner", "InventoryController", "DealerUser", "PlatformAdmin")
    limit, offset = auth.pagination()
    part_id = auth.query_str("part_id")
    status = auth.query_enum("status", CAMPAIGN_STATUSES)

    rows = list(store.campaigns.values())
    if part_id is not None:
        rows = [r for r in rows if r["part_id"] == part_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.campaign(r) for r in page], limit, offset, total)


@bp.post("/aftermarket/last-time-buy-campaigns/<campaign_id>/submit")
def submit_campaign(campaign_id):
    user_id, _ = auth.require("AftermarketPlanner", "InventoryController")
    camp = domain.get_campaign(campaign_id)
    part = store.parts.get(camp["part_id"])

    if camp["status"] != "DRAFT":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")
    if part is None or part["lifecycle_state"] != "PHASE_OUT":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")

    _check_windows(camp["part_id"], camp["ltb_window_start"], camp["ltb_window_end"],
                   exclude_id=camp["id"])

    camp["status"] = "SUBMITTED"
    camp["submitted_by_user_id"] = user_id
    store.touch(camp)
    return envelope.ok(serializers.campaign(camp))


@bp.post("/aftermarket/last-time-buy-campaigns/<campaign_id>/approve")
def approve_campaign(campaign_id):
    user_id, _ = auth.require("InventoryController")
    camp = domain.get_campaign(campaign_id)

    if camp["submitted_by_user_id"] is not None and user_id == camp["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    data = auth.body()
    approved_qty = auth.req_int(data, "approved_qty", minimum=1)

    if camp["status"] != "SUBMITTED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")

    camp["status"] = "APPROVED"
    camp["approved_qty"] = approved_qty
    camp["remaining_qty"] = approved_qty
    camp["approved_by_user_id"] = user_id
    store.touch(camp)

    part = store.parts.get(camp["part_id"])
    if part is not None and part["lifecycle_state"] == "PHASE_OUT":
        domain.set_lifecycle_state(part, "LTB_OPEN")
        store.touch(part)

    return envelope.ok(serializers.campaign(camp))


@bp.post("/aftermarket/last-time-buy-campaigns/<campaign_id>/reject")
def reject_campaign(campaign_id):
    user_id, _ = auth.require("InventoryController")
    camp = domain.get_campaign(campaign_id)

    if camp["submitted_by_user_id"] is not None and user_id == camp["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    data = auth.body()
    rejection_reason = auth.req_str(data, "rejection_reason")

    if camp["status"] != "SUBMITTED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")

    camp["status"] = "REJECTED"
    camp["rejection_reason"] = rejection_reason
    store.touch(camp)
    return envelope.ok(serializers.campaign(camp))


@bp.post("/aftermarket/last-time-buy-campaigns/<campaign_id>/revise")
def revise_campaign(campaign_id):
    auth.require("AftermarketPlanner")
    camp = domain.get_campaign(campaign_id)
    data = auth.body()
    method = auth.opt_enum(data, "method", LTB_METHODS)
    coverage_years = auth.opt_int(data, "coverage_years", default=None, minimum=1,
                                  maximum=calc.MAX_COVERAGE_YEARS)

    if camp["status"] != "REJECTED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")

    part = store.parts.get(camp["part_id"])
    annual_demand_units = _snapshot_demand(part)

    if method is not None:
        camp["method"] = method
    if coverage_years is not None:
        camp["coverage_years"] = coverage_years

    cover = part["on_hand_units"] + part["in_transit_units"]
    camp["annual_demand_units"] = annual_demand_units
    camp["proposed_qty"] = calc.ltb_quantity(camp["method"], annual_demand_units,
                                             camp["coverage_years"], cover)
    camp["status"] = "DRAFT"
    camp["revision_index"] += 1
    camp["submitted_by_user_id"] = None
    camp["rejection_reason"] = None
    store.touch(camp)
    return envelope.ok(serializers.campaign(camp))


@bp.post("/aftermarket/last-time-buy-campaigns/<campaign_id>/allocate")
def allocate_campaign(campaign_id):
    auth.require("InventoryController")
    camp = domain.get_campaign(campaign_id)

    if camp["status"] != "APPROVED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")

    requests = store.sort_created([r for r in store.allocation_requests.values()
                                   if r["campaign_id"] == camp["id"]])
    pending = [r for r in requests if r["status"] == "PENDING"]

    candidates = []
    suspended = []
    for req in pending:
        dealer = store.dealers.get(req["dealer_id"])
        if dealer is not None and dealer["status"] == "ACTIVE":
            candidates.append((req, dealer))
        else:
            suspended.append(req)

    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_ALLOCATION_REQUESTS")

    for req in suspended:
        req["status"] = "DENIED"
        req["granted_units"] = 0
        store.touch(req)

    part_id = camp["part_id"]
    granted = {}
    for req, dealer in candidates:
        installed = len(domain.covered_units(part_id, dealer_id=dealer["id"]))
        req["dealer_installed_units"] = installed
        req["priority_score"] = calc.priority_score(dealer["tier"], installed,
                                                    dealer["credit_hold"])
        granted[req["id"]] = 0

    fair_share = calc.floor_int(
        calc.dec(camp["approved_qty"]) * calc.FAIR_SHARE_PCT / calc.dec(len(candidates)))
    for req, _ in candidates:
        granted[req["id"]] = min(req["requested_units"], fair_share)

    remaining = camp["approved_qty"] - sum(granted.values())

    ordered = sorted(candidates,
                     key=lambda pair: (-pair[0]["priority_score"],
                                       -pair[0]["requested_units"],
                                       pair[0]["created_at"],
                                       pair[0]["_seq"]))
    for req, _ in ordered:
        if remaining <= 0:
            break
        take = min(req["requested_units"] - granted[req["id"]], remaining)
        if take > 0:
            granted[req["id"]] += take
            remaining -= take

    for req, _ in candidates:
        amount = granted[req["id"]]
        req["granted_units"] = amount
        if amount == req["requested_units"]:
            req["status"] = "GRANTED"
        elif amount > 0:
            req["status"] = "PARTIALLY_GRANTED"
        else:
            req["status"] = "DENIED"
        store.touch(req)

    camp["status"] = "ALLOCATING"
    camp["remaining_qty"] = remaining
    store.touch(camp)
    return envelope.ok(serializers.campaign(camp))


@bp.post("/aftermarket/last-time-buy-campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    auth.require("InventoryController")
    camp = domain.get_campaign(campaign_id)

    if camp["status"] != "ALLOCATING":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")

    for req in store.sort_created(list(store.allocation_requests.values())):
        if req["campaign_id"] == camp["id"] and req["status"] == "PENDING":
            req["status"] = "DENIED"
            store.touch(req)

    camp["status"] = "CLOSED"
    store.touch(camp)

    part = store.parts.get(camp["part_id"])
    if part is not None and part["lifecycle_state"] == "LTB_OPEN":
        domain.set_lifecycle_state(part, "LTB_CLOSED")
        store.touch(part)

    return envelope.ok(serializers.campaign(camp))


# --------------------------------------------------- allocation requests ---
@bp.post("/aftermarket/allocation-requests")
def create_allocation_request():
    user_id, role = auth.require("DealerUser")
    data = auth.body()

    body_dealer_id = data.get("dealer_id")
    if isinstance(body_dealer_id, str):
        auth.dealer_scope(role, user_id, body_dealer_id)

    camp = fk(data, "campaign_id", domain.get_campaign)
    dealer = fk(data, "dealer_id", domain.get_dealer)

    campaign_id = auth.req_id(data, "campaign_id")
    dealer_id = auth.req_id(data, "dealer_id")
    if camp is None:
        camp = domain.get_campaign(campaign_id)
    if dealer is None:
        dealer = domain.get_dealer(dealer_id)
    requested_units = auth.req_int(data, "requested_units", minimum=1)
    expected_campaign_version = auth.req_int(data, "expected_campaign_version")

    if expected_campaign_version != camp["version"]:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION")
    if camp["status"] != "APPROVED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")
    if requested_units > camp["remaining_qty"]:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_REMAINING")
    if dealer["credit_hold"]:
        raise ApiError("ERR_DEALER_CREDIT_HOLD")

    for prior in store.sort_created(list(store.allocation_requests.values())):
        if (prior["campaign_id"] == camp["id"]
                and prior["dealer_id"] == dealer["id"]
                and prior["status"] == "PENDING"):
            prior["status"] = "WITHDRAWN"
            store.touch(prior)

    rec = store.new_record("AllocationRequest", {
        "campaign_id": camp["id"],
        "dealer_id": dealer["id"],
        "requested_units": requested_units,
        "granted_units": 0,
        "priority_score": 0,
        "dealer_installed_units": 0,
        "status": "PENDING",
    })
    store.allocation_requests[rec["id"]] = rec
    store.touch(camp)
    return envelope.created(serializers.allocation_request(rec))


@bp.get("/aftermarket/allocation-requests/<request_id>")
def read_allocation_request(request_id):
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController", "PlatformAdmin")
    return envelope.ok(serializers.allocation_request(domain.get_allocation_request(request_id)))


@bp.get("/aftermarket/allocation-requests")
def list_allocation_requests():
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController", "PlatformAdmin")
    limit, offset = auth.pagination()
    campaign_id = auth.query_str("campaign_id")
    dealer_id = auth.query_str("dealer_id")
    status = auth.query_enum("status", ALLOCATION_STATUSES)

    rows = list(store.allocation_requests.values())
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.allocation_request(r) for r in page],
                            limit, offset, total)


@bp.post("/aftermarket/allocation-requests/<request_id>/withdraw")
def withdraw_allocation_request(request_id):
    user_id, role = auth.require("DealerUser", "AftermarketPlanner")
    req = domain.get_allocation_request(request_id)
    auth.dealer_scope(role, user_id, req["dealer_id"])

    camp = store.campaigns.get(req["campaign_id"])
    if req["status"] == "PENDING":
        req["status"] = "WITHDRAWN"
        store.touch(req)
    elif req["status"] in ("GRANTED", "PARTIALLY_GRANTED"):
        if camp is None or camp["status"] != "ALLOCATING":
            raise ApiError("ERR_ALLOCATION_STATE_INVALID")
        camp["remaining_qty"] += req["granted_units"]
        req["granted_units"] = 0
        req["status"] = "WITHDRAWN"
        store.touch(req)
        store.touch(camp)
    else:
        raise ApiError("ERR_ALLOCATION_STATE_INVALID")

    return envelope.ok(serializers.allocation_request(req))
