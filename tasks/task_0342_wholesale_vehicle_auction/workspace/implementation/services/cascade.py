"""Cross-aggregate cascades and derived-field recomputation (PRD §2.10, §2.11,
§3.6, §3.8, §3.9, §3.10)."""
import db
from services.common import touch
from services import calc


# ---- buyer credit ledger (PRD §2.10) ---------------------------------------
def recompute_buyer_credit(buyer):
    """committed_cents = sum of total_due_cents over the buyer's settlements
    with payment_status in {UNPAID, PAID}."""
    committed = 0
    for s in db.settlements.values():
        if s.get("buyer_id") == buyer["id"] and s.get("payment_status") in ("UNPAID", "PAID"):
            committed += int(s.get("total_due_cents") or 0)
    buyer["committed_cents"] = committed
    buyer["available_credit_cents"] = int(buyer["credit_limit_cents"]) - committed
    touch(buyer)


# ---- lane slot occupancy (PRD §3.4) ----------------------------------------
def recompute_lane_slot_count(lane):
    count = 0
    for lot in db.lots.values():
        if lot.get("lane_id") == lane["id"] and lot.get("status") not in ("WITHDRAWN", "PASSED"):
            count += 1
    lane["scheduled_slot_count"] = count
    touch(lane)


# ---- sale lane_count (PRD §3.1) --------------------------------------------
def recompute_sale_lane_count(sale):
    count = 0
    for lane in db.lanes.values():
        if lane.get("sale_id") == sale["id"] and lane.get("status") != "ARCHIVED":
            count += 1
    sale["lane_count"] = count
    touch(sale)


# ---- condition report lookup -----------------------------------------------
def condition_report_for(consignment_id):
    for cr in db.condition_reports.values():
        if cr.get("consignment_id") == consignment_id:
            return cr
    return None


def settlement_for_lot(lot_id):
    for s in db.settlements.values():
        if s.get("lot_id") == lot_id:
            return s
    return None


def derived_settlement_status(settlement):
    ps = settlement["payment_status"]
    ts = settlement["title_status"]
    if ps == "REVERSED":
        return "VOID"
    if ps == "WRITTEN_OFF":
        return "DEFAULTED"
    if ps == "PAID" and ts == "TITLE_RECEIVED":
        return "CLEARED"
    return "OPEN"


# ---- settlement clearing cascade (PRD §3.9) --------------------------------
def maybe_clear_settlement(settlement):
    """If payment PAID and title RECEIVED, run the 4-deep clearing cascade."""
    if settlement["payment_status"] != "PAID" or settlement["title_status"] != "TITLE_RECEIVED":
        settlement["status"] = derived_settlement_status(settlement)
        return
    if settlement["status"] == "CLEARED":
        return

    lot = db.lots.get(settlement["lot_id"])
    consignment = db.consignments.get(lot["consignment_id"]) if lot else None
    seller = db.sellers.get(settlement["seller_id"])
    cr = condition_report_for(consignment["id"]) if consignment else None
    as_is = bool(cr["as_is"]) if cr else False

    settlement["status"] = "CLEARED"
    # Recompute final seller proceeds on (possibly reduced) sale price.
    final_proceeds = calc.seller_net_proceeds(
        settlement["sale_price_cents"],
        seller["seller_fee_pct"] if seller else 0,
        as_is,
    )
    settlement["seller_proceeds_cents"] = final_proceeds
    touch(settlement)

    # Mirror onto consignment
    if consignment is not None:
        consignment["expected_proceeds_cents"] = final_proceeds
        # Consignment SOLD -> SETTLED
        if consignment["status"] == "SOLD":
            consignment["status"] = "SETTLED"
        touch(consignment)

    # Lot HAMMERED -> FINALIZED
    if lot is not None and lot["status"] == "HAMMERED":
        lot["status"] = "FINALIZED"
        touch(lot)

    # Auto-issue GatePass
    issue_gate_pass(settlement)


def issue_gate_pass(settlement):
    from services.common import base_record
    gp = base_record(common_fields=True)
    gp.update({
        "settlement_id": settlement["id"],
        "buyer_id": settlement["buyer_id"],
        "status": "ISSUED",
    })
    db.gate_passes[gp["id"]] = gp
    return gp


# ---- arbitration full-approval unwind (PRD §3.10) --------------------------
def unwind_settlement(settlement):
    """APPROVED_FULL -> settlement VOID; cascade lot/consignment/gatepass and
    re-credit buyer."""
    settlement["payment_status"] = "REVERSED"
    settlement["status"] = "VOID"
    touch(settlement)

    # Re-credit buyer by total_due_cents (recompute committed_cents)
    buyer = db.buyers.get(settlement["buyer_id"])
    if buyer is not None:
        recompute_buyer_credit(buyer)

    # Lot HAMMERED -> ARB_REVERSED
    lot = db.lots.get(settlement["lot_id"])
    if lot is not None and lot["status"] == "HAMMERED":
        lot["status"] = "ARB_REVERSED"
        touch(lot)

    # Consignment SOLD -> ARB_UNWOUND, expected_proceeds -> 0
    consignment = db.consignments.get(lot["consignment_id"]) if lot else None
    if consignment is not None and consignment["status"] == "SOLD":
        consignment["status"] = "ARB_UNWOUND"
        consignment["expected_proceeds_cents"] = 0
        touch(consignment)

    # Void any ISSUED gate pass for this settlement
    for gp in db.gate_passes.values():
        if gp.get("settlement_id") == settlement["id"] and gp.get("status") == "ISSUED":
            gp["status"] = "VOID"
            touch(gp)
