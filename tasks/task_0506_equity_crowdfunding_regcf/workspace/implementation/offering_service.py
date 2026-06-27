"""Offering sweep / close / refund cascades (PRD 3.5, 3.6).

Centralizes the transitive close cascade (close -> issuance -> cap-table mint ->
escrow debit -> offering totals) shared by rolling-close and final close, plus
the auto-refund cascade for failed raises and cancellations.
"""
from clock import clock
from calculations import equity_issuance, round_half_up_fee
from db import db, new_id, now_iso
from derive import (
    touch,
    credit_wallet,
    recompute_offering_committed,
    recompute_offering_swept,
    recompute_escrow_held,
    recompute_issuer_trailing,
    get_escrow_for_offering,
)


def close_batch(offering):
    """The close batch: investments in COMMITTED with reconfirm_required==false,
    plus those in RECONFIRMED. Sorted by insertion sequence for determinism."""
    batch = [
        i for i in db.investments.values()
        if i["offering_id"] == offering["id"]
        and (
            (i["status"] == "COMMITTED" and not i["reconfirm_required"])
            or i["status"] == "RECONFIRMED"
        )
    ]
    batch.sort(key=lambda i: i["_seq"])
    return batch


def sweep_batch(offering, batch):
    """Sweep the close batch: mint cap-table positions, compute issuance and
    sub-share refunds, debit escrow, advance offering totals. Pinned disbursement
    arithmetic computed on the batch as a whole (PRD 3.6)."""
    security_type = offering["security_type"]
    price = offering.get("price_per_security_cents")

    batch_gross = sum(i["amount_cents"] for i in batch)
    platform_fee = round_half_up_fee(batch_gross)

    sum_remainders = 0
    for inv in batch:
        securities, consideration, remainder, instrument, quantity, principal = equity_issuance(
            inv["amount_cents"], security_type, price
        )
        sum_remainders += remainder

        inv["status"] = "ISSUED"
        inv["securities_issued"] = securities
        inv["refund_amount_cents"] = remainder
        touch(inv)
        if remainder > 0:
            credit_wallet(inv["investor_id"], remainder)

        # Mint immutable CapTableEntry (no updated_at / version per PRD 2.4).
        ts = now_iso()
        cid = new_id()
        entry = {
            "id": cid,
            "offering_id": offering["id"],
            "investor_id": inv["investor_id"],
            "investment_id": inv["id"],
            "instrument": instrument,
            "quantity": quantity,
            "principal_cents": principal,
            "created_at": ts,
            "_seq": db.next_seq(),
        }
        db.cap_table_entries[cid] = entry

    net_disbursed = batch_gross - platform_fee - sum_remainders

    escrow = get_escrow_for_offering(offering["id"])
    if escrow is not None:
        escrow["disbursed_amount_cents"] += net_disbursed
        escrow["refunded_amount_cents"] += sum_remainders + platform_fee
        recompute_escrow_held(escrow)
        touch(escrow)

    recompute_offering_swept(offering)
    recompute_offering_committed(offering)


def refund_all_unswept(offering, terminal_status):
    """Auto-refund every un-swept commitment, moving each to terminal_status
    (REFUNDED on failed raise, CANCELLED on cancel). Drives escrow held to zero
    and advances refunded_amount_cents (PRD 3.5)."""
    total_refunded = 0
    affected = [
        i for i in db.investments.values()
        if i["offering_id"] == offering["id"] and i["status"] in ("COMMITTED", "RECONFIRMED")
    ]
    for inv in affected:
        inv["status"] = terminal_status
        inv["refund_amount_cents"] = inv["amount_cents"]
        credit_wallet(inv["investor_id"], inv["amount_cents"])
        total_refunded += inv["amount_cents"]
        touch(inv)

    escrow = get_escrow_for_offering(offering["id"])
    if escrow is not None:
        escrow["refunded_amount_cents"] += total_refunded
        recompute_escrow_held(escrow)  # -> 0 since no COMMITTED/RECONFIRMED remain
        touch(escrow)

    recompute_offering_committed(offering)
