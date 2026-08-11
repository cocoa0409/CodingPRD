"""BidPackage endpoints (§3.4): window gates, evaluation, the award cascade."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import clock
from db import store
from errors import ApiError
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from services.budget import recompute_site_budget, recompute_program_rollup
from services.forecast import recompute_commitment_for_site
from util import bump, iso_dt, new_entity, parse_datetime, serialize
from validate import (body_fk, get_or_404, json_body, req_datetime, req_enum,
                      req_int, req_str)

bp = Blueprint("bid_packages", __name__)

TERMINAL = ("AWARDED",)
EVAL_MODES = ("LOWEST_PRICE", "BEST_VALUE")
PRICE_WEIGHT = Decimal("0.7")
TECH_WEIGHT = Decimal("0.3")


def evaluation_score(min_amount, bid):
    """BEST_VALUE score, 2dp round_half_up (§3.4)."""
    score = (PRICE_WEIGHT * (Decimal(min_amount) / Decimal(bid["amount_cents"]))
             * Decimal(100) + TECH_WEIGHT * Decimal(bid["tech_score"]))
    return float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def responsive_candidates(package):
    return [
        b for b in store.bids.values()
        if b["bid_package_id"] == package["id"]
        and b["status"] == "SUBMITTED"
        and b["is_responsive"]
    ]


def live_score(package, bid):
    """Display-time score under BEST_VALUE while the package is unawarded."""
    if package["evaluation_mode"] != "BEST_VALUE":
        return None
    if bid["status"] != "SUBMITTED" or not bid["is_responsive"]:
        return None
    cands = responsive_candidates(package)
    if not cands:
        return None
    return evaluation_score(min(b["amount_cents"] for b in cands), bid)


def _rank_candidates(package, cands):
    if package["evaluation_mode"] == "LOWEST_PRICE":
        return sorted(cands, key=lambda b: (
            b["amount_cents"], b["duration_days"], b["submitted_at"], b["_seq"]))
    scored = [(evaluation_score(min(b["amount_cents"] for b in cands), b), b)
              for b in cands]
    scored.sort(key=lambda t: (
        -Decimal(str(t[0])), t[1]["amount_cents"], t[1]["submitted_at"], t[1]["_seq"]))
    return [b for _score, b in scored]


@bp.route("/rollout/bid-packages", methods=["POST"], strict_slashes=False)
@authed(["ProcurementLead"])
def create_package():
    body = json_body()
    market = body_fk(body, "market_id", store.markets)
    phase_wave = req_int(body, "phase_wave")
    scope = req_str(body, "scope_description")
    open_at = req_datetime(body, "bid_open_at")
    close_at = req_datetime(body, "bid_close_at")
    mode = req_enum(body, "evaluation_mode", EVAL_MODES)
    max_duration = req_int(body, "max_duration_days")
    if market is None:
        from errors import invalid_request
        invalid_request("field 'market_id' is required")
    package = new_entity(store)
    package.update({
        "market_id": market["id"],
        "phase_wave": phase_wave,
        "scope_description": scope,
        "bid_open_at": iso_dt(open_at),
        "bid_close_at": iso_dt(close_at),
        "evaluation_mode": mode,
        "max_duration_days": max_duration,
        "awarded_bid_id": None,
        "status": "DRAFT",
    })
    store.packages[package["id"]] = package
    return ok(serialize(package), status=201)


@bp.route("/rollout/bid-packages", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_packages():
    return list_response(store.packages, [
        ("market_id", "market_id", "str"),
        ("status", "status", "str"),
    ])


@bp.route("/rollout/bid-packages/<bidPackageId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_package(bidPackageId):
    return ok(serialize(get_or_404(store.packages, bidPackageId, "bid package")))


@bp.route("/rollout/bid-packages/<bidPackageId>/open", methods=["POST"], strict_slashes=False)
@authed(["ProcurementLead"])
def open_package(bidPackageId):
    package = get_or_404(store.packages, bidPackageId, "bid package")
    require_state(package, ("DRAFT",), TERMINAL)
    market = store.markets.get(package["market_id"])
    if market is None or market["status"] != "BIDDING":
        raise ApiError("ERR_MARKET_NOT_BIDDING", 409, "market is not BIDDING")
    if clock.now() < parse_datetime(package["bid_open_at"]):
        raise ApiError("ERR_BID_WINDOW_NOT_OPEN", 409,
                       "bid_open_at has not been reached")
    package["status"] = "OPEN"
    bump(package)
    return ok(serialize(package))


@bp.route("/rollout/bid-packages/<bidPackageId>/close", methods=["POST"], strict_slashes=False)
@authed(["ProcurementLead"])
def close_package(bidPackageId):
    package = get_or_404(store.packages, bidPackageId, "bid package")
    require_state(package, ("OPEN",), TERMINAL)
    if clock.now() < parse_datetime(package["bid_close_at"]):
        raise ApiError("ERR_BID_WINDOW_STILL_OPEN", 409,
                       "bid_close_at has not been reached")
    package["status"] = "CLOSED"
    bump(package)
    return ok(serialize(package))


@bp.route("/rollout/bid-packages/<bidPackageId>/award", methods=["POST"], strict_slashes=False)
@authed(["ProcurementLead"])
def award_package(bidPackageId):
    package = get_or_404(store.packages, bidPackageId, "bid package")
    require_state(package, ("CLOSED",), TERMINAL)
    cands = responsive_candidates(package)
    if not cands:
        raise ApiError("ERR_NO_RESPONSIVE_BIDS", 409,
                       "no responsive SUBMITTED bids on the package")
    ranked = _rank_candidates(package, cands)
    winner = ranked[0]

    # Freeze BEST_VALUE scores at award time (candidate set as of award).
    if package["evaluation_mode"] == "BEST_VALUE":
        min_amount = min(b["amount_cents"] for b in cands)
        for b in store.bids.values():
            if b["bid_package_id"] != package["id"]:
                continue
            b["evaluation_score"] = (
                evaluation_score(min_amount, b) if b in cands else None)

    winner["status"] = "AWARDED"
    bump(winner)
    for b in list(store.bids.values()):
        if (b["bid_package_id"] == package["id"] and b["status"] == "SUBMITTED"
                and b["id"] != winner["id"]):
            b["status"] = "REJECTED"
            bump(b)
    package["awarded_bid_id"] = winner["id"]
    package["status"] = "AWARDED"
    bump(package)

    market = store.markets.get(package["market_id"])
    if market is not None and market["status"] == "BIDDING":
        market["status"] = "AWARDED"
        bump(market)

    affected_programs = set()
    for site in store.sites.values():
        if (site["market_id"] == package["market_id"]
                and site["phase_wave"] == package["phase_wave"]
                and site["status"] not in ("OPEN", "REMOVED")):
            site["base_contract_cents"] = winner["amount_cents"]
            bump(site)
            recompute_site_budget(site)
            recompute_commitment_for_site(site)
            affected_programs.add(site["program_id"])
    for program_id in affected_programs:
        program = store.programs.get(program_id)
        if program is not None:
            recompute_program_rollup(program)
    return ok(serialize(package))
