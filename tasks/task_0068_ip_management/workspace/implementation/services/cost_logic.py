"""Cost booking, allocation, FX conversion, and budget enforcement."""
from decimal import Decimal

import db
from errors import (APIError, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_ALLOCATION_BPS_INVALID,
                    ERR_ALLOCATION_BU_INACTIVE, ERR_BUDGET_EXCEEDED, ERR_BAD_REQUEST)
from services import audit
from services.common import make_unversioned
from utils import round_half_up_cents


BPS_TOTAL = 10000


def _convert_to_usd(amount_native_cents: int, fx_rate_to_usd) -> int:
    return round_half_up_cents(Decimal(amount_native_cents) * Decimal(str(fx_rate_to_usd)))


def _compute_allocations(total_usd_cents: int, allocation_rules) -> list:
    n = len(allocation_rules)
    out = []
    running = 0
    for i in range(n - 1):
        rule = allocation_rules[i]
        portion = round_half_up_cents(
            Decimal(total_usd_cents) * Decimal(rule["percent_bps"]) / Decimal(BPS_TOTAL)
        )
        running += portion
        out.append({
            "business_unit_id": rule["business_unit_id"],
            "percent_bps": rule["percent_bps"],
            "allocated_cents": portion,
        })
    last = allocation_rules[n - 1]
    last_portion = total_usd_cents - running
    out.append({
        "business_unit_id": last["business_unit_id"],
        "percent_bps": last["percent_bps"],
        "allocated_cents": last_portion,
    })
    return out


def _validate_allocation_rules(allocation_rules):
    if not isinstance(allocation_rules, list) or len(allocation_rules) == 0:
        raise APIError(ERR_ALLOCATION_BPS_INVALID, 422, "allocation_rules must be non-empty list")
    total_bps = 0
    norm = []
    for r in allocation_rules:
        if not isinstance(r, dict):
            raise APIError(ERR_ALLOCATION_BPS_INVALID, 422, "rule entry must be object")
        bu_id = r.get("business_unit_id")
        bps = r.get("percent_bps")
        if not bu_id or not isinstance(bps, int) or isinstance(bps, bool):
            raise APIError(ERR_ALLOCATION_BPS_INVALID, 422, "invalid rule shape")
        if bps < 0:
            raise APIError(ERR_ALLOCATION_BPS_INVALID, 422, "percent_bps must be non-negative")
        total_bps += bps
        norm.append({"business_unit_id": bu_id, "percent_bps": bps})
    if total_bps != BPS_TOTAL:
        raise APIError(ERR_ALLOCATION_BPS_INVALID, 422, "percent_bps must sum to 10000")
    # All targeted BUs must exist & be ACTIVE
    for r in norm:
        if r["business_unit_id"] not in db.business_units:
            raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422,
                           "allocation_rules business_unit_id does not resolve")
        bu = db.business_units[r["business_unit_id"]]
        if bu["status"] != "ACTIVE":
            raise APIError(ERR_ALLOCATION_BU_INACTIVE, 422,
                           "BusinessUnit is not ACTIVE")
    return norm


def _simulate_spend(allocations_to_add, cost_id_being_replaced=None):
    """Compute the resulting actual_spend per business unit if these allocations are
    applied, optionally replacing the existing allocations of cost_id_being_replaced.
    Raises ERR_BUDGET_EXCEEDED if any BU would exceed its annual_budget_cents."""
    # Compute the current spends per BU, but excluding the cost being replaced
    per_bu = {}
    for cost_id, cost in db.costs.items():
        if cost_id == cost_id_being_replaced:
            continue
        for a in cost.get("allocations", []):
            per_bu[a["business_unit_id"]] = per_bu.get(a["business_unit_id"], 0) + a["allocated_cents"]
    # Apply the new allocations
    for a in allocations_to_add:
        per_bu[a["business_unit_id"]] = per_bu.get(a["business_unit_id"], 0) + a["allocated_cents"]
    # Check against budget
    for bu_id, spend in per_bu.items():
        bu = db.business_units.get(bu_id)
        if not bu:
            continue
        if spend > bu["annual_budget_cents"]:
            raise APIError(ERR_BUDGET_EXCEEDED, 422,
                           f"BusinessUnit {bu_id} would exceed budget")


def book_cost(body, actor_role, actor_id):
    from utils import get_str, get_int, get_enum
    category = get_enum(body, "category", ("APPLICATION", "ANNUAL_FEE", "LITIGATION", "AGENT_FEE"))
    currency = get_str(body, "currency")
    amount_native = get_int(body, "amount_native_cents", required=True, min_value=0)
    fx_raw = body.get("fx_rate_to_usd")
    if fx_raw is None or isinstance(fx_raw, bool):
        raise APIError(ERR_BAD_REQUEST, 422, "fx_rate_to_usd is required")
    if not isinstance(fx_raw, (int, float)) or fx_raw <= 0:
        raise APIError(ERR_BAD_REQUEST, 422, "fx_rate_to_usd must be > 0")
    booked_at = get_str(body, "booked_at")
    allocation_rules_raw = body.get("allocation_rules")
    norm_rules = _validate_allocation_rules(allocation_rules_raw)

    ip_right_id = body.get("ip_right_id")
    protection_case_id = body.get("protection_case_id")
    agent_id = body.get("agent_id")

    if ip_right_id is not None and ip_right_id not in db.ip_rights:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "ip_right_id does not resolve")
    if protection_case_id is not None and protection_case_id not in db.protection_cases:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "protection_case_id does not resolve")
    if agent_id is not None and agent_id not in db.agents:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "agent_id does not resolve")

    amount_usd = _convert_to_usd(amount_native, fx_raw)
    allocations = _compute_allocations(amount_usd, norm_rules)
    _simulate_spend(allocations)

    cost = make_unversioned({
        "category": category,
        "ip_right_id": ip_right_id,
        "protection_case_id": protection_case_id,
        "agent_id": agent_id,
        "currency": currency,
        "amount_native_cents": amount_native,
        "fx_rate_to_usd": fx_raw,
        "amount_usd_cents": amount_usd,
        "allocations": allocations,
        "allocation_rules": norm_rules,
        "booked_at": booked_at,
    })
    db.costs[cost["id"]] = cost
    return cost


def reallocate(cost, body, actor_role, actor_id):
    allocation_rules_raw = body.get("allocation_rules")
    norm_rules = _validate_allocation_rules(allocation_rules_raw)
    allocations = _compute_allocations(cost["amount_usd_cents"], norm_rules)
    _simulate_spend(allocations, cost_id_being_replaced=cost["id"])
    cost["allocation_rules"] = norm_rules
    cost["allocations"] = allocations
    return cost


def book_cost_for_event(category, amount_usd_cents, ip_right_id, protection_case_id,
                        agent_id, business_unit_id, actor_role, actor_id, currency="USD"):
    """Internal helper used by side-effect cost bookings (annual fees, litigation)."""
    # Single-BU allocation: 10000 bps to the supplied BU
    allocations = [{
        "business_unit_id": business_unit_id,
        "percent_bps": BPS_TOTAL,
        "allocated_cents": amount_usd_cents,
    }]
    # Side-effect cost bookings bypass budget enforcement (a payment race could otherwise
    # leave the system in an inconsistent state).  The PRD calls out budget enforcement
    # explicitly on POST /costs and PATCH /costs/{id}/allocation; internal bookings are
    # not in scope for that check.
    cost = make_unversioned({
        "category": category,
        "ip_right_id": ip_right_id,
        "protection_case_id": protection_case_id,
        "agent_id": agent_id,
        "currency": currency,
        "amount_native_cents": amount_usd_cents,
        "fx_rate_to_usd": 1.0,
        "amount_usd_cents": amount_usd_cents,
        "allocations": allocations,
        "allocation_rules": [{"business_unit_id": business_unit_id, "percent_bps": BPS_TOTAL}],
        "booked_at": db.now_iso(),
    })
    db.costs[cost["id"]] = cost
    return cost
