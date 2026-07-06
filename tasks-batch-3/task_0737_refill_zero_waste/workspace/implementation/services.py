"""Shared business-logic helpers: wallet ledger appends, bin depletion/return
cascades, and line queries. Kept separate so container/order/delivery routes all
drive the same invariant-preserving primitives."""
import store
from helpers import stamp_new, touch


# ---------------------------------------------------------------------------
# WalletLedger (append-only). Member balances are projections over these rows,
# so appending an entry also bumps the member's version/updated_at (PRD 2.4).
# ---------------------------------------------------------------------------
def append_ledger(member_id, entry_type, wallet_delta=0, liability_delta=0,
                  points_delta=0, source_kind="ORDER", source_id=None, memo=None):
    rec = {
        "member_id": member_id,
        "entry_type": entry_type,
        "wallet_delta_cents": wallet_delta,
        "liability_delta_cents": liability_delta,
        "points_delta": points_delta,
        "source_kind": source_kind,
        "source_id": source_id,
        "memo": memo,
    }
    stamp_new(rec, versioned=False)
    store.DB["wallet_ledger"][rec["id"]] = rec
    member = store.DB["members"].get(member_id)
    if member is not None:
        touch(member)
    return rec


# ---------------------------------------------------------------------------
# Bin grams cascades
# ---------------------------------------------------------------------------
def deplete_bin(bin_rec, net_g):
    """FINAL fill: decrement on_hand; flip OPEN->LOW and mint a RestockTask on
    the threshold crossing (cascade hops 2->3->4)."""
    bin_rec["on_hand_g"] -= net_g
    touch(bin_rec)
    created_task = None
    if bin_rec["status"] == "OPEN" and bin_rec["on_hand_g"] <= bin_rec["reorder_threshold_g"]:
        bin_rec["status"] = "LOW"
        created_task = _create_restock_task(bin_rec)
    return created_task


def return_grams(bin_rec, net_g):
    """Compensating action (void / cancel): return grams; clear LOW->OPEN if the
    threshold is cleared again."""
    bin_rec["on_hand_g"] += net_g
    if bin_rec["status"] == "LOW" and bin_rec["on_hand_g"] > bin_rec["reorder_threshold_g"]:
        bin_rec["status"] = "OPEN"
    touch(bin_rec)


def _create_restock_task(bin_rec):
    rec = {
        "bin_id": bin_rec["id"],
        "requested_fill_g": bin_rec["capacity_g"] - bin_rec["on_hand_g"],
        "restocked_g": None,
        "status": "OPEN",
        "_completed_at": None,
    }
    stamp_new(rec)
    store.DB["restock_tasks"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Line queries
# ---------------------------------------------------------------------------
def order_lines(order_id):
    return [l for l in store.DB["lines"].values() if l["order_id"] == order_id]


def nonvoided_lines(order_id):
    return [l for l in order_lines(order_id) if l["pricing_stage"] != "VOIDED"]


def final_lines(order_id):
    return [l for l in order_lines(order_id) if l["pricing_stage"] == "FINAL"]


def resolve_bin(product_id, station_id):
    """The unique non-RETIRED bin for a product at a station (BulkBin has no
    RETIRED state in this domain, so this is simply the bin for the pair)."""
    for b in store.DB["bins"].values():
        if b["product_id"] == product_id and b["station_id"] == station_id:
            return b
    return None
