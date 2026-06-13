"""Remittance + Allocation routes, including the multi-order allocation waterfall."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import lookup
from common import (
    stamp_create, touch, get_body, as_int, fk, round_half_up_cents,
    pagination, paginate, sort_by_created,
)
from db import store
from middleware import require_roles
from response import object_response, array_response
from services import serialize, ledger, calc

bp = Blueprint("remittances", __name__)


@bp.route("/remittances", methods=["POST"])
@require_roles("Employer", "FinanceOfficer")
def create_remittance(auth):
    body = get_body()
    # Existence (priority 3), left-to-right.
    employer = lookup.employer(fk(body, "employer_id"))
    ncp = lookup.noncustodial_party(fk(body, "noncustodial_party_id"))
    # Employer may only record remittances under its own employer record.
    if auth.role == "Employer" and employer["id"] != auth.user_id:
        raise errors.forbidden()
    # Structural validity (priority 5).
    disposable = as_int(body, "disposable_earnings_cents")
    gross = as_int(body, "gross_remitted_cents")
    # CCPA cap at creation (ccpa_withholding_cap).
    ccpa_cap_cents, distributable_cents = calc.compute_ccpa(ncp, disposable, gross)
    rec = stamp_create({
        "employer_id": employer["id"],
        "noncustodial_party_id": ncp["id"],
        "disposable_earnings_cents": disposable,
        "gross_remitted_cents": gross,
        "ccpa_cap_cents": ccpa_cap_cents,
        "distributable_cents": distributable_cents,
        "status": "RECEIVED",
    })
    store.remittances[rec["id"]] = rec
    return object_response(serialize.remittance(rec), 201)


@bp.route("/remittances/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "Employer")
def get_remittance(auth, rid):
    rec = lookup.remittance(rid)
    lookup.require(lookup.owns_remittance(auth, rec))
    return object_response(serialize.remittance(rec), 200)


@bp.route("/remittances", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "Employer")
def list_remittances(auth):
    emp_id = request.args.get("employer_id")
    ncp_id = request.args.get("noncustodial_party_id")
    items = list(store.remittances.values())
    if emp_id is not None:
        items = [r for r in items if r["employer_id"] == emp_id]
    if ncp_id is not None:
        items = [r for r in items if r["noncustodial_party_id"] == ncp_id]
    if auth.role == "Employer":
        items = [r for r in items if r["employer_id"] == auth.user_id]
    items = sort_by_created(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.remittance(r) for r in page],
                          limit, offset, total, 200)


@bp.route("/remittances/<rid>/allocate", methods=["POST"])
@require_roles("FinanceOfficer")
def allocate_remittance(auth, rid):
    rem = lookup.remittance(rid)
    # State (priority 7).
    if rem["status"] != "RECEIVED":
        raise errors.invalid_state()
    # Eligible candidate set: obligor's ACTIVE/MODIFIED orders, created_at ASC.
    eligible = [o for o in store.support_orders.values()
                if o["noncustodial_party_id"] == rem["noncustodial_party_id"]
                and o["obligation_status"] in ("ACTIVE", "MODIFIED")]
    eligible = sort_by_created(eligible)
    # ERR_NO_ALLOCABLE_ORDER (priority 11).
    if not eligible:
        raise errors.no_allocable_order()
    # ERR_NOTHING_TO_ALLOCATE (priority 12).
    distributable = rem["distributable_cents"]
    if distributable <= 0:
        raise errors.nothing_to_allocate()

    _run_allocation(rem, eligible, distributable)
    rem["status"] = "ALLOCATED"
    touch(rem)
    return object_response(serialize.remittance(rem), 200)


def _run_allocation(rem, eligible, distributable):
    """multi_order_allocation: two-stage waterfall (SCAFFOLD 1.3 / PRD 3.5)."""
    total_cs = sum(o["current_support_cents"] for o in eligible)

    cs_alloc = {o["id"]: 0 for o in eligible}
    int_alloc = {o["id"]: 0 for o in eligible}
    prin_alloc = {o["id"]: 0 for o in eligible}

    if distributable <= total_cs:
        # STAGE 1 only — pure current-support proration; nothing reaches arrears.
        for o in eligible:
            raw = Decimal(distributable) * Decimal(o["current_support_cents"]) / Decimal(total_cs)
            cs_alloc[o["id"]] = round_half_up_cents(raw)
        remainder = distributable - sum(cs_alloc.values())
        target = _greatest_cs_order(eligible)
        cs_alloc[target["id"]] += remainder
    else:
        # Current support satisfied first on every order; surplus to arrears.
        for o in eligible:
            cap = min(ledger.current_support_due_cents(o["id"]), o["current_support_cents"])
            cs_alloc[o["id"]] = cap
        surplus = distributable - sum(cs_alloc.values())
        # STAGE 2 — within each order (created_at ASC), apply running surplus.
        # The current-support portion is already taken; apply remaining surplus
        # to interest then principal per the within-order waterfall.
        for o in eligible:
            if surplus <= 0:
                break
            int_bal = ledger.interest_balance_cents(o["id"])
            prin_bal = ledger.arrears_principal_cents(o["id"])
            applied_interest = min(surplus, int_bal)
            surplus -= applied_interest
            applied_principal = min(surplus, prin_bal)
            surplus -= applied_principal
            int_alloc[o["id"]] = applied_interest
            prin_alloc[o["id"]] = applied_principal
            # Anything still in surplus is overpayment credit (not posted).

    # Materialize allocations + post PAYMENT ledger rows per bucket per order.
    for o in eligible:
        cs = cs_alloc[o["id"]]
        it = int_alloc[o["id"]]
        pr = prin_alloc[o["id"]]
        alloc = stamp_create({
            "remittance_id": rem["id"],
            "support_order_id": o["id"],
            "current_support_applied_cents": cs,
            "interest_applied_cents": it,
            "principal_applied_cents": pr,
            "total_applied_cents": cs + it + pr,
        })
        store.allocations[alloc["id"]] = alloc
        if cs > 0:
            ledger.post_entry(o["id"], "PAYMENT", "CURRENT_SUPPORT", cs, alloc["id"])
        if it > 0:
            ledger.post_entry(o["id"], "PAYMENT", "INTEREST", it, alloc["id"])
        if pr > 0:
            ledger.post_entry(o["id"], "PAYMENT", "PRINCIPAL", pr, alloc["id"])
        # Each target order is itself a mutation (balances change).
        touch(o)
        # Auto-satisfy enforcement if arrears principal + interest now both zero.
        _maybe_satisfy_enforcement(o)


def _greatest_cs_order(eligible):
    """Order with greatest current_support_cents; tie-break created_at ASC.

    `eligible` is already sorted created_at ASC, so a stable max on
    current_support_cents alone yields the earliest among ties.
    """
    best = eligible[0]
    for o in eligible[1:]:
        if o["current_support_cents"] > best["current_support_cents"]:
            best = o
    return best


def _maybe_satisfy_enforcement(order):
    """If arrears principal & interest are both 0 and an enforcement intercept
    is CERTIFIED/active, satisfy it and lift the order's enforcement_status."""
    if order["enforcement_status"] != "INTERCEPT_ACTIVE":
        return
    if ledger.arrears_principal_cents(order["id"]) != 0:
        return
    if ledger.interest_balance_cents(order["id"]) != 0:
        return
    for action in store.enforcement_actions.values():
        if action["support_order_id"] == order["id"] and action["status"] == "CERTIFIED":
            action["status"] = "SATISFIED"
            touch(action)
    order["enforcement_status"] = "LIFTED"
    touch(order)


# --- Allocation reads --------------------------------------------------------
@bp.route("/allocations", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def list_allocations(auth):
    rem_id = request.args.get("remittance_id")
    so_id = request.args.get("support_order_id")
    items = list(store.allocations.values())
    if rem_id is not None:
        items = [a for a in items if a["remittance_id"] == rem_id]
    if so_id is not None:
        items = [a for a in items if a["support_order_id"] == so_id]
    items = sort_by_created(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.allocation(a) for a in page],
                          limit, offset, total, 200)


@bp.route("/allocations/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def get_allocation(auth, rid):
    rec = lookup.allocation(rid)
    return object_response(serialize.allocation(rec), 200)


@bp.route("/remittances/<rid>/return", methods=["POST"])
@require_roles("FinanceOfficer")
def return_remittance(auth, rid):
    rem = lookup.remittance(rid)
    if rem["status"] != "RECEIVED":
        raise errors.invalid_state()
    rem["status"] = "RETURNED"
    touch(rem)
    return object_response(serialize.remittance(rem), 200)
