"""PoundageReport computation (calc distributed_poundage_ledger / PRD §3.9)."""
from db import db, now_iso
from services.calc import round2
from services import models


def compute_poundage_report(cycle_id):
    """Return a fresh PoundageReport snapshot dict for the cycle (recomputed on
    read; never stored). PRD §3.9.

    total_planned_lbs: sum of planned_lbs over PACKED+FINALIZED events whose
        order draws from this cycle (forward-looking).
    total_distributed_lbs: sum of actual_distributed_lbs over FINALIZED events,
        accumulated in ascending (finalized_at, created_at) order.
    total_tefap_lbs: sum of tefap_lbs over FINALIZED events.
    shrinkage_lbs: total_planned_lbs - total_distributed_lbs.
    VOIDED events excluded from every total.
    """
    # Map order_id -> order to test cycle membership.
    cycle_order_ids = {
        o["id"] for o in db.agency_orders.values() if o["allocation_cycle_id"] == cycle_id
    }
    events = [
        e
        for e in db.distribution_events.values()
        if e["agency_order_id"] in cycle_order_ids
    ]

    planned_total = 0.0
    for e in events:
        if e["status"] in ("PACKED", "FINALIZED"):
            planned_total += e["planned_lbs"]

    finalized = [e for e in events if e["status"] == "FINALIZED"]
    finalized.sort(key=lambda e: (e.get("finalized_at_seq", 0), e["_seq"]))

    distributed_total = 0.0
    tefap_total = 0.0
    for e in finalized:
        distributed_total += e["actual_distributed_lbs"]
        tefap_total += e["tefap_lbs"]

    total_planned = round2(planned_total)
    total_distributed = round2(distributed_total)
    total_tefap = round2(tefap_total)
    shrinkage = round2(total_planned - total_distributed)

    return {
        "id": db.new_id(),
        "allocation_cycle_id": cycle_id,
        "total_planned_lbs": total_planned,
        "total_distributed_lbs": total_distributed,
        "total_tefap_lbs": total_tefap,
        "shrinkage_lbs": shrinkage,
        "created_at": now_iso(),
    }
