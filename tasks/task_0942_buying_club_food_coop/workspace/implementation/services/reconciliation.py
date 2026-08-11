"""drop_reconciliation_balance (PRD §3.9).

FRICTION 1 — `supplier_cost_cents` is weighted by `subtotal_cents` "over
RECEIVED drop runs", but a draft is only ever taken after delivery, when those
same drop runs have already moved RECEIVED -> SETTLED.  Read literally the
cohort would be empty and the division undefined, which would make drafting —
and therefore posting, payout, cycle reconcile and cycle close — unreachable.
The cohort is therefore read as "the drop runs that reached RECEIVED", i.e.
those now in RECEIVED or SETTLED: exactly the cohort freight level 1 used.
"""

from core.constants import RECON_VARIANCE_TOLERANCE_CENTS
from core.money import largest_remainder
from core.store import DB, ordered, touch
from services import commission, recompute

SUPPLIER_COST_COHORT = ("RECEIVED", "SETTLED")


def reconciliations_of(drop_run):
    return ordered([r for r in DB.drop_reconciliations.values()
                    if r["drop_run_id"] == drop_run["id"]])


def active_reconciliation(drop_run):
    for recon in reconciliations_of(drop_run):
        if recon["status"] in ("DRAFT", "BALANCED", "VARIANCE_HELD"):
            return recon
    return None


def member_charges(drop_run):
    total = 0
    for order in recompute.orders_of_drop_run(drop_run):
        if order["payment_status"] in ("CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED"):
            total += order["captured_cents"] - order["refunded_cents"]
    return total


def supplier_cost(drop_run):
    route_run = DB.get("RouteRun", drop_run["route_run_id"])
    if route_run is None:
        return 0
    cohort = [d for d in recompute.drop_runs_of_route_run(route_run)
              if d["status"] in SUPPLIER_COST_COHORT]
    if not cohort:
        return 0
    weights = [d["subtotal_cents"] for d in cohort]
    shares, _ = largest_remainder(route_run["supplier_invoice_cents"], weights)
    for index, candidate in enumerate(cohort):
        if candidate["id"] == drop_run["id"]:
            return shares[index]
    return 0


def commission_net(drop_run):
    accruals = commission.accruals_of(drop_run)
    if not accruals:
        return 0
    return accruals[0]["net_cents"]


def draft(drop_run, prepared_by_user_id):
    charges = member_charges(drop_run)
    supplier = supplier_cost(drop_run)
    freight = drop_run["freight_alloc_cents"]
    reefer = drop_run["reefer_alloc_cents"]
    comm = commission_net(drop_run)
    club_margin = charges - supplier - freight - reefer - comm
    variance = charges - (supplier + freight + reefer + comm + club_margin)
    row = DB.insert("DropReconciliation", {
        "drop_run_id": drop_run["id"],
        "member_charges_cents": charges,
        "supplier_cost_cents": supplier,
        "freight_alloc_cents": freight,
        "reefer_alloc_cents": reefer,
        "commission_cents": comm,
        "club_margin_cents": club_margin,
        "variance_cents": variance,
        "prepared_by_user_id": prepared_by_user_id,
        "posted_by_user_id": None,
        "posted_at": None,
        "status": "DRAFT",
    })
    # The draft never rests in DRAFT: it auto-branches inside this request.
    row["status"] = ("BALANCED" if abs(variance) <= RECON_VARIANCE_TOLERANCE_CENTS
                     else "VARIANCE_HELD")
    touch(row)
    return row


def recompute_downstream(drop_run):
    """Refund / volunteer cascade hop 4: recompute the non-POSTED ledger.

    `club_margin_cents` is the residual frozen at draft time; it is NOT
    recomputed here, which is exactly how a downstream change opens a variance.
    """
    recon = active_reconciliation(drop_run)
    if recon is None:
        return None
    recon["member_charges_cents"] = member_charges(drop_run)
    recon["commission_cents"] = commission_net(drop_run)
    recon["variance_cents"] = recon["member_charges_cents"] - (
        recon["supplier_cost_cents"] + recon["freight_alloc_cents"]
        + recon["reefer_alloc_cents"] + recon["commission_cents"]
        + recon["club_margin_cents"])
    if recon["status"] == "BALANCED" and abs(recon["variance_cents"]) > RECON_VARIANCE_TOLERANCE_CENTS:
        recon["status"] = "VARIANCE_HELD"
    touch(recon)
    return recon
