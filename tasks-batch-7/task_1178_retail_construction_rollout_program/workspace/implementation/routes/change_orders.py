"""ChangeOrder endpoints (§3.6): tiers, segregation of duties, OCC, opening
lock, budget headroom — the most heavily gated operation in the API."""
from flask import Blueprint, g

from db import store
from errors import (ApiError, already_terminal, forbidden_identity,
                    invalid_request, invalid_state)
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from services.budget import recompute_program_rollup, recompute_site_budget
from services.forecast import commitment_of_site, recompute_commitment_for_site
from util import bump, new_entity, serialize
from validate import (body_fk, get_or_404, is_int, json_body, opt_str,
                      req_enum, req_int, req_str)

bp = Blueprint("change_orders", __name__)

TERMINAL = ("REJECTED", "CANCELLED", "RESCINDED")
COST_CATEGORIES = ("SCOPE", "SCHEDULE", "CODE_COMPLIANCE", "OWNER_REQUEST")


def _tier(amount_cents, base_contract_cents):
    """change_order_tier: exact rational comparison, NO rounding (§2.6)."""
    if base_contract_cents <= 0:
        return "STANDARD" if amount_cents == 0 else "CRITICAL"
    lhs = abs(amount_cents) * 10000
    if lhs <= 200 * base_contract_cents:
        return "STANDARD"
    if lhs <= 500 * base_contract_cents:
        return "ELEVATED"
    return "CRITICAL"


@bp.route("/rollout/change-orders", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def create_change_order():
    body = json_body()
    site = body_fk(body, "site_id", store.sites)
    # Step 5 — the site's market must be AWARDED.
    if site is not None:
        market = store.markets.get(site["market_id"])
        if market is None or market["status"] != "AWARDED":
            raise ApiError("ERR_MARKET_NOT_AWARDED", 409,
                           "site's market is not AWARDED")
    # Step 12 — request shape.
    if site is None:
        invalid_request("field 'site_id' is required")
    description = req_str(body, "description")
    amount = req_int(body, "amount_cents")
    category = req_enum(body, "cost_category", COST_CATEGORIES)

    co = new_entity(store)
    co.update({
        "site_id": site["id"],
        "description": description,
        "amount_cents": amount,
        "cost_category": category,
        "tier": _tier(amount, site["base_contract_cents"]),
        "proposed_by_user_id": g.user_id,
        "status": "PROPOSED",
    })
    store.change_orders[co["id"]] = co
    bump(site)  # proposed bucket grows (listed side effect)
    recompute_site_budget(site)
    return ok(serialize(co), status=201)


@bp.route("/rollout/change-orders", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_change_orders():
    return list_response(store.change_orders, [
        ("site_id", "site_id", "str"),
        ("status", "status", "str"),
        ("tier", "tier", "str"),
    ])


@bp.route("/rollout/change-orders/<changeOrderId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_change_order(changeOrderId):
    return ok(serialize(get_or_404(store.change_orders, changeOrderId, "change order")))


@bp.route("/rollout/change-orders/<changeOrderId>/approve", methods=["POST"], strict_slashes=False)
@authed(["FinanceController", "ProgramDirector"])
def approve_change_order(changeOrderId):
    body = json_body()
    co = get_or_404(store.change_orders, changeOrderId, "change order")

    # Step 5 — from-state on the order, then the site gate (terminal site).
    require_state(co, ("PROPOSED",), TERMINAL)
    site = store.sites.get(co["site_id"])
    if site is not None and site["status"] in ("OPEN", "REMOVED"):
        already_terminal("site is in terminal state %s" % site["status"])

    # Step 6 — optimistic concurrency on the site's version.
    esv = body.get("expected_site_version")
    if is_int(esv) and site is not None and esv != site["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_site_version does not match current Site.version")

    # Step 7 — tier authority first, then segregation of duties (§3.6 order).
    if co["tier"] in ("STANDARD", "ELEVATED"):
        if g.role != "FinanceController":
            raise ApiError("ERR_CO_TIER_ROLE_REQUIRED", 403,
                           "STANDARD/ELEVATED orders require FinanceController")
    else:  # CRITICAL
        if g.role != "ProgramDirector":
            raise ApiError("ERR_CO_TIER_ROLE_REQUIRED", 403,
                           "CRITICAL orders require ProgramDirector")
    if g.user_id == co["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "approver must differ from proposer")

    # Step 9 — opening lock: SCHEDULE orders blocked while the stored
    # protection posture (from the previous forecast evaluation) is AT_RISK or
    # BREACHED.
    if co["cost_category"] == "SCHEDULE" and site is not None:
        commitment = commitment_of_site(site)
        if commitment is not None and commitment["protection_posture"] in (
                "AT_RISK", "BREACHED"):
            raise ApiError("ERR_OPENING_LOCK_ENGAGED", 409,
                           "opening lock engaged for SCHEDULE change orders")

    # Step 11 — fiscal headroom: credits always pass.
    if site is not None and co["amount_cents"] > 0:
        if site["committed_cents"] + co["amount_cents"] > site["budget_allocation_cents"]:
            raise ApiError("ERR_BUDGET_HEADROOM_EXCEEDED", 422,
                           "committed cost would exceed the site's budget envelope")

    # Step 12 — request shape.
    if not is_int(esv):
        invalid_request("field 'expected_site_version' is required and must be an integer")
    opt_str(body, "approval_note")

    co["status"] = "APPROVED"
    bump(co)
    bump(site)  # listed side effect: increments Site.version by 1
    recompute_site_budget(site)
    program = store.programs.get(site["program_id"])
    if program is not None:
        recompute_program_rollup(program)
    recompute_commitment_for_site(site)  # CO approval triggers the forecast
    return ok(serialize(co))


@bp.route("/rollout/change-orders/<changeOrderId>/reject", methods=["POST"], strict_slashes=False)
@authed(["FinanceController", "ProgramDirector"])
def reject_change_order(changeOrderId):
    body = json_body()
    co = get_or_404(store.change_orders, changeOrderId, "change order")
    require_state(co, ("PROPOSED",), TERMINAL)
    req_str(body, "rejection_reason")
    co["status"] = "REJECTED"
    bump(co)
    site = store.sites.get(co["site_id"])
    if site is not None:
        bump(site)
        recompute_site_budget(site)  # provisional ratio re-derives
    return ok(serialize(co))


@bp.route("/rollout/change-orders/<changeOrderId>/rescind", methods=["POST"], strict_slashes=False)
@authed(["FinanceController"])
def rescind_change_order(changeOrderId):
    body = json_body()
    co = get_or_404(store.change_orders, changeOrderId, "change order")
    require_state(co, ("APPROVED",), TERMINAL)
    site = store.sites.get(co["site_id"])
    if site is not None and site["status"] in ("OPEN", "REMOVED"):
        invalid_state("site is %s" % site["status"])
    req_str(body, "rescind_reason")
    co["status"] = "RESCINDED"
    bump(co)
    if site is not None:
        bump(site)
        recompute_site_budget(site)
        program = store.programs.get(site["program_id"])
        if program is not None:
            recompute_program_rollup(program)
        recompute_commitment_for_site(site)  # CO rescission triggers the forecast
    return ok(serialize(co))


@bp.route("/rollout/change-orders/<changeOrderId>/cancel", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def cancel_change_order(changeOrderId):
    co = get_or_404(store.change_orders, changeOrderId, "change order")
    # Step 3 — only the recorded proposer may cancel.
    if co["proposed_by_user_id"] != g.user_id:
        forbidden_identity("only the proposing superintendent may cancel")
    require_state(co, ("PROPOSED",), TERMINAL)
    co["status"] = "CANCELLED"
    bump(co)
    site = store.sites.get(co["site_id"])
    if site is not None:
        bump(site)
        recompute_site_budget(site)
    return ok(serialize(co))
