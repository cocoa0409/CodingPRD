"""The three named transitive cascades.

A. harvest report -> pro-rata reallocation -> line trim -> order reprice ->
   credit posture
B. contract default -> AR -> credit posture -> orders ON_HOLD -> shipments HELD
C. temperature reading -> EXCURSION_FLAGGED -> yeast FAILED + hop line
   QUARANTINED -> replacement propagation job
"""

from datetime import timedelta

from calc import (
    CONTRACT_TYPE_RANK,
    assess_order_fees,
    contracts_of_program,
    lines_of,
    orders_of,
    pitch_advisory,
    recompute_brewer,
    refresh_line_derived,
    rollup_order,
    shipments_of_order,
)
from db import db, new_entity, now, set_dt, sort_key, touch
from util import D, dec_floor


# ===========================================================================
# Cascade A
# ===========================================================================

def run_reallocation(program, yield_pct):
    """calculations.shortfall_prorata_reallocation plus links 2 through 5."""
    active = [
        c
        for c in contracts_of_program(program["id"])
        if c["status"] in ("ACTIVE", "SHORTFALL_ADJUSTED", "CARRY_FORWARD_PENDING")
    ]
    total_contracted = D(0)
    for contract in active:
        total_contracted += D(contract["contracted_lbs"])
    pool = dec_floor(total_contracted * D(yield_pct) / D(100), 0)
    program["allocatable_pool_lbs"] = pool

    ordered = sorted(
        active,
        key=lambda c: (CONTRACT_TYPE_RANK[c["contract_type"]],) + sort_key(c),
    )
    remaining_pool = pool
    affected_orders = set()
    for contract in ordered:
        contracted = D(contract["contracted_lbs"])
        allocated = contracted if remaining_pool >= contracted else remaining_pool
        if allocated < 0:
            allocated = D(0)
        remaining_pool -= allocated
        changed = D(contract["allocated_lbs"]) != allocated
        contract["allocated_lbs"] = allocated
        if allocated < contracted and contract["status"] == "ACTIVE":
            contract["status"] = "SHORTFALL_ADJUSTED"
            changed = True
        trimmed = trim_lines_for_contract(contract)
        affected_orders |= trimmed
        if changed or trimmed:
            touch(contract)
    program["unallocated_pool_lbs"] = remaining_pool

    affected_brewers = set()
    for order_id in affected_orders:
        order = db.orders.get(order_id)
        if order is None:
            continue
        rollup_order(order)
        assess_order_fees(order, "PROVISIONAL")
        touch(order)
        affected_brewers.add(order["brewer_id"])
    for brewer_id in affected_brewers:
        brewer = db.brewers.get(brewer_id)
        if brewer is not None:
            recompute_brewer(brewer)


def trim_lines_for_contract(contract):
    """Link 3: trim newest-first until committed_lbs no longer exceeds
    allocated_lbs.  Lines whose order has moved past CONFIRMED are immune."""
    affected = set()
    gap = D(contract["committed_lbs"]) - D(contract["allocated_lbs"])
    if gap <= 0:
        return affected
    candidates = []
    for line in db.lines.values():
        if line.get("hop_contract_id") != contract["id"]:
            continue
        if line["status"] not in ("OPEN", "TRIMMED"):
            continue
        order = db.orders.get(line["sales_order_id"])
        if order is None or order["fulfillment_status"] != "CONFIRMED":
            continue
        candidates.append(line)
    candidates.sort(key=sort_key, reverse=True)
    for line in candidates:
        if gap <= 0:
            break
        quantity = D(line["quantity"])
        if gap >= quantity:
            line["trimmed_lbs"] = D(line["trimmed_lbs"]) + quantity
            line["status"] = "CANCELLED_SHORTFALL"
            line["extended_cents"] = 0
            contract["committed_lbs"] = D(contract["committed_lbs"]) - quantity
            gap -= quantity
        else:
            line["quantity"] = quantity - gap
            line["trimmed_lbs"] = D(line["trimmed_lbs"]) + gap
            line["status"] = "TRIMMED"
            contract["committed_lbs"] = D(contract["committed_lbs"]) - gap
            gap = D(0)
            refresh_line_derived(line)
        touch(line)
        affected.add(line["sales_order_id"])
    return affected


# ===========================================================================
# Cascade B
# ===========================================================================

def hold_staged_shipments(order):
    for shipment in shipments_of_order(order["id"]):
        if shipment["status"] == "STAGED":
            shipment["status"] = "HELD"
            touch(shipment)


def propagate_credit_hold(brewer):
    """Links 3 and 4: a HOLD posture pushes orders ON_HOLD and loads HELD."""
    if brewer.get("credit_status") != "HOLD":
        return
    for order in orders_of(brewer["id"]):
        if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
            continue
        if order["credit_status"] != "APPROVED":
            continue
        order["credit_status"] = "ON_HOLD"
        touch(order)
        hold_staged_shipments(order)


def post_receivable(brewer, delta_cents, propagate=False):
    """calculations.brewer_ar_ledger: apply a signed AR movement.

    ``propagate`` drives cascade B links 3 and 4, which the specification
    attaches to a declared contract default only.
    """
    brewer["ar_balance_cents"] = int(brewer["ar_balance_cents"]) + int(delta_cents)
    recompute_brewer(brewer, bump=False)
    touch(brewer)
    if propagate:
        propagate_credit_hold(brewer)


# ===========================================================================
# order commitment release (cancellation)
# ===========================================================================

def release_commitments(order):
    """Return contract and spot poundage held by an order's live lines."""
    for line in lines_of(order["id"]):
        if line["status"] not in ("OPEN", "TRIMMED"):
            continue
        quantity = D(line["quantity"])
        if line["item_type"] != "HOP":
            continue
        if line["allocation_source"] == "CONTRACT" and line.get("hop_contract_id"):
            contract = db.contracts.get(line["hop_contract_id"])
            if contract is not None:
                contract["committed_lbs"] = D(contract["committed_lbs"]) - quantity
                touch(contract)
        else:
            variety = db.varieties.get(line.get("hop_variety_id"))
            if variety is not None:
                variety["available_spot_lbs"] = D(variety["available_spot_lbs"]) + quantity
                touch(variety)


def supersede_shipments(order):
    for shipment in shipments_of_order(order["id"]):
        if shipment["status"] in ("STAGED", "HELD"):
            shipment["status"] = "SUPERSEDED"
            touch(shipment)


# ===========================================================================
# Cascade C
# ===========================================================================

def run_excursion_cascade(shipment):
    """A flagged reefer load fails its yeast and quarantines its cold hops."""
    order = db.orders.get(shipment["sales_order_id"])
    if order is None:
        return
    for line in lines_of(order["id"]):
        if line["item_type"] == "YEAST":
            job = db.jobs.get(line.get("yeast_propagation_job_id"))
            if job is None or job["status"] != "READY":
                continue
            job["status"] = "FAILED"
            job["failure_reason"] = "COLD_CHAIN_EXCURSION"
            touch(job)
            mint_replacement_job(job)
        elif (
            line["item_type"] == "HOP"
            and line["cold_chain_required"]
            and line["status"] == "OPEN"
        ):
            line["status"] = "QUARANTINED"
            touch(line)


def mint_replacement_job(failed_job):
    strain = db.strains[failed_job["yeast_strain_id"]]
    recipe = db.recipes[failed_job["recipe_id"]]
    pitch_date = failed_job["pitch_date"] + timedelta(
        days=int(strain["propagation_lead_time_days"])
    )
    job = new_entity()
    job.update(
        {
            "brewer_id": failed_job["brewer_id"],
            "recipe_id": failed_job["recipe_id"],
            "yeast_strain_id": failed_job["yeast_strain_id"],
            "replaces_job_id": failed_job["id"],
            "ready_at": None,
            "failure_reason": None,
            "status": "REQUESTED",
        }
    )
    set_dt(job, "pitch_date", pitch_date)
    job.update(pitch_advisory(recipe, strain, pitch_date))
    db.jobs[job["id"]] = job
    return job
