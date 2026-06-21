"""State-machine cascades and the payment waterfall (SCAFFOLD §1.2 / §1.3)."""
import db
from helpers import touch, stamp_create
from services import calc


# --------------------------------------------------------------------------
# GiftCardTxn ledger helper (immutable: id + created_at only)
# --------------------------------------------------------------------------
def _add_txn(gift_card, kind, amount_cents, booking_id=None):
    txn = {
        "gift_card_id": gift_card["id"],
        "booking_id": booking_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    stamp_create(txn, full_audit=False)
    db.gift_card_txns[txn["id"]] = txn
    return txn


# --------------------------------------------------------------------------
# Payment waterfall (calculations.payment_waterfall) — gift card -> wallet -> card
# Returns (gift_card_applied, wallet_applied, card_applied).
# --------------------------------------------------------------------------
def run_payment_waterfall(member, amount_due, booking_id):
    remaining = amount_due
    # bucket 1: member's ACTIVE gift cards, oldest created_at first
    cards = [
        gc for gc in db.gift_cards.values()
        if gc["owner_member_id"] == member["id"] and gc["status"] == "ACTIVE"
    ]
    cards.sort(key=lambda gc: gc["_seq"])
    for gc in cards:
        if remaining <= 0:
            break
        use = min(gc["balance_cents"], remaining)
        if use > 0:
            _add_txn(gc, "REDEEM", -use, booking_id)
            gc["balance_cents"] -= use
            remaining -= use
            touch(gc)
            if gc["balance_cents"] == 0:
                gc["status"] = "DEPLETED"
    gift_card_applied = amount_due - remaining
    # bucket 2: wallet credit
    wallet_use = min(member["wallet_credit_cents"], remaining)
    member["wallet_credit_cents"] -= wallet_use
    remaining -= wallet_use
    wallet_applied = wallet_use
    if wallet_use > 0:
        touch(member)
    # bucket 3: external card absorbs the rest
    card_applied = remaining
    return gift_card_applied, wallet_applied, card_applied


# --------------------------------------------------------------------------
# Reverse the gift-card portion of a payment via REVERSAL txns, remainder to
# wallet. Used on member cancellation refunds (PRD §3.7).
# Credits `refund_cents` total to wallet: gift-card-applied portion is returned
# via REVERSAL ledger entries (up to gift_card_applied_cents), remainder to wallet.
# --------------------------------------------------------------------------
def refund_gift_card_then_wallet(member, booking, refund_cents):
    remaining = refund_cents
    gc_portion = min(booking["gift_card_applied_cents"], remaining)
    if gc_portion > 0:
        # Return to the member's gift cards (oldest first) via REVERSAL txns.
        cards = [
            gc for gc in db.gift_cards.values()
            if gc["owner_member_id"] == member["id"]
        ]
        cards.sort(key=lambda gc: gc["_seq"])
        to_return = gc_portion
        for gc in cards:
            if to_return <= 0:
                break
            if gc["status"] == "VOIDED":
                continue
            # Return only what this card originally contributed is not tracked
            # per-card; reverse onto the redeemed cards up to their redeemed amount.
            redeemed = -sum(
                t["amount_cents"] for t in db.gift_card_txns.values()
                if t["gift_card_id"] == gc["id"] and t["kind"] == "REDEEM"
                and t["booking_id"] == booking["id"]
            )
            reversed_already = sum(
                t["amount_cents"] for t in db.gift_card_txns.values()
                if t["gift_card_id"] == gc["id"] and t["kind"] == "REVERSAL"
                and t["booking_id"] == booking["id"]
            )
            available = redeemed - reversed_already
            give = min(available, to_return)
            if give > 0:
                _add_txn(gc, "REVERSAL", give, booking["id"])
                gc["balance_cents"] += give
                to_return -= give
                if gc["status"] == "DEPLETED" and gc["balance_cents"] > 0:
                    gc["status"] = "ACTIVE"
                touch(gc)
        # any gift-card portion we could not place on a card falls to wallet
        gc_portion -= to_return
        remaining_wallet = refund_cents - gc_portion
    else:
        remaining_wallet = refund_cents
    if remaining_wallet > 0:
        member["wallet_credit_cents"] += remaining_wallet
        touch(member)


# --------------------------------------------------------------------------
# Waitlist promotion (calculations.waitlist_promotion) — at most one entry.
# Returns True if an entry was promoted.
# --------------------------------------------------------------------------
def promote_waitlist(session, freed_seats, cancelled_booking):
    candidates = [
        w for w in db.waitlist_entries.values()
        if w["session_id"] == session["id"] and w["queue_status"] == "WAITING"
        and w["seats_requested"] <= freed_seats
    ]
    if not candidates:
        return False
    candidates.sort(key=lambda w: w["_seq"])  # created_at ASC
    entry = candidates[0]
    member = db.members[entry["member_id"]]
    template = db.templates[session["template_id"]]
    charge = calc.booking_charge(session, template, entry["seats_requested"])
    new_booking = {
        "session_id": session["id"],
        "member_id": entry["member_id"],
        "seats_requested": entry["seats_requested"],
        "charge_cents": charge,
        "gift_card_applied_cents": 0,
        "wallet_applied_cents": 0,
        "card_applied_cents": 0,
        "refund_cents": 0,
        "refilled_from_waitlist": False,
        "lifecycle_status": "CONFIRMED",
        "payment_status": "PAID",
    }
    stamp_create(new_booking)
    db.bookings[new_booking["id"]] = new_booking
    gc_a, w_a, c_a = run_payment_waterfall(member, charge, new_booking["id"])
    new_booking["gift_card_applied_cents"] = gc_a
    new_booking["wallet_applied_cents"] = w_a
    new_booking["card_applied_cents"] = c_a
    entry["queue_status"] = "PROMOTED"
    entry["promoted_booking_id"] = new_booking["id"]
    touch(entry)
    cancelled_booking["refilled_from_waitlist"] = True
    session["confirmed_seats"] += entry["seats_requested"]
    return True


# --------------------------------------------------------------------------
# Revert an approved substitution (PRD §3.9). Compensating reversal in the
# opposite waterfall order: card first, then wallet, then gift card (REVERSAL).
# Each funding source returns to its pre-approval value; charge returns too.
# --------------------------------------------------------------------------
def revert_substitution_payment(member, booking, sub):
    surcharge = sub["surcharge_cents"]
    gc_delta = sub.get("_gc_delta", 0)
    wallet_delta = sub.get("_wallet_delta", 0)
    card_delta = sub.get("_card_delta", 0)
    # 1) card: simply drop the card-applied portion
    booking["card_applied_cents"] -= card_delta
    # 2) wallet: return the wallet-applied portion to wallet credit
    if wallet_delta > 0:
        member["wallet_credit_cents"] += wallet_delta
        touch(member)
    booking["wallet_applied_cents"] -= wallet_delta
    # 3) gift card: REVERSAL txns returning the redeemed surcharge portion
    if gc_delta > 0:
        cards = [gc for gc in db.gift_cards.values() if gc["owner_member_id"] == member["id"]]
        cards.sort(key=lambda gc: gc["_seq"])
        to_return = gc_delta
        for gc in cards:
            if to_return <= 0:
                break
            redeemed = -sum(
                t["amount_cents"] for t in db.gift_card_txns.values()
                if t["gift_card_id"] == gc["id"] and t["kind"] == "REDEEM"
                and t["booking_id"] == booking["id"]
            )
            reversed_already = sum(
                t["amount_cents"] for t in db.gift_card_txns.values()
                if t["gift_card_id"] == gc["id"] and t["kind"] == "REVERSAL"
                and t["booking_id"] == booking["id"]
            )
            available = redeemed - reversed_already
            give = min(available, to_return)
            if give > 0:
                _add_txn(gc, "REVERSAL", give, booking["id"])
                gc["balance_cents"] += give
                to_return -= give
                if gc["status"] == "DEPLETED" and gc["balance_cents"] > 0:
                    gc["status"] = "ACTIVE"
                touch(gc)
    booking["gift_card_applied_cents"] -= gc_delta
    booking["charge_cents"] -= surcharge
    touch(booking)


# --------------------------------------------------------------------------
# Member cancellation of a CONFIRMED booking (PRD §3.7).
# --------------------------------------------------------------------------
def cancel_confirmed_booking(booking, session):
    member = db.members[booking["member_id"]]
    refund = calc.cancellation_refund_provisional(booking, session)
    booking["refund_cents"] = refund
    # credit wallet via gift-card reversal first, remainder to wallet
    refund_gift_card_then_wallet(member, booking, refund)
    booking["lifecycle_status"] = "CANCELLED"
    if refund == booking["charge_cents"]:
        booking["payment_status"] = "REFUNDED"
    else:
        booking["payment_status"] = "PARTIALLY_REFUNDED"
    touch(booking)
    # seat accounting
    session["confirmed_seats"] -= booking["seats_requested"]
    calc.refresh_prep_cost(session)
    session["version"] = session.get("version", 1) + 1
    session["updated_at"] = db.iso_now()
    # late-cancel strike if within 24h
    if calc.is_within_late_window(session):
        _create_strike(member, booking, "LATE_CANCEL")
    # waitlist promotion (depth-3 cascade)
    promoted = promote_waitlist(session, booking["seats_requested"], booking)
    # FULL -> OPEN if no refill
    if not promoted and session["status"] == "FULL" and session["confirmed_seats"] < session["planned_seats"]:
        session["status"] = "OPEN"
    elif session["confirmed_seats"] == session["planned_seats"] and session["status"] == "OPEN":
        session["status"] = "FULL"
    touch(session)


def _create_strike(member, booking, kind):
    rec = {
        "member_id": member["id"],
        "booking_id": booking["id"],
        "kind": kind,
        "settlement_status": "PENDING",
    }
    stamp_create(rec, full_audit=False)
    db.no_show_records[rec["id"]] = rec
    return rec


# --------------------------------------------------------------------------
# Session COMPLETE cascade (PRD §3.10).
# --------------------------------------------------------------------------
def complete_session(session):
    affected_members = set()
    child_bookings = [b for b in db.bookings.values() if b["session_id"] == session["id"]]
    for b in child_bookings:
        if b["lifecycle_status"] == "CONFIRMED":
            b["lifecycle_status"] = "ATTENDED"
            touch(b)
        elif b["lifecycle_status"] == "PENDING":
            # cancel; never paid -> refund 0, payment_status unchanged (UNPAID)
            b["lifecycle_status"] = "CANCELLED"
            b["refund_cents"] = 0
            touch(b)
    # settle this session's pending strikes (strikes for child bookings)
    child_booking_ids = {b["id"] for b in child_bookings}
    for rec in db.no_show_records.values():
        if rec["booking_id"] in child_booking_ids and rec["settlement_status"] == "PENDING":
            rec["settlement_status"] = "SETTLED"
            affected_members.add(rec["member_id"])
    # FINAL refund reconciliation for cancelled bookings of this session
    for b in child_bookings:
        if b["lifecycle_status"] == "CANCELLED" and b["payment_status"] in ("REFUNDED", "PARTIALLY_REFUNDED"):
            final_refund = calc.cancellation_refund_final(b)
            delta = final_refund - b["refund_cents"]
            if delta != 0:
                member = db.members[b["member_id"]]
                member["wallet_credit_cents"] += delta
                if member["wallet_credit_cents"] < 0:
                    member["wallet_credit_cents"] = 0
                touch(member)
                b["refund_cents"] = final_refund
                if final_refund == b["charge_cents"]:
                    b["payment_status"] = "REFUNDED"
                else:
                    b["payment_status"] = "PARTIALLY_REFUNDED"
                touch(b)
                affected_members.add(b["member_id"])
    # recompute FINAL reliability for every affected member
    for mid in affected_members:
        calc.recompute_reliability(db.members[mid])
        touch(db.members[mid])
    session["status"] = "COMPLETED"
    touch(session)
    # series rollup
    if session.get("series_id"):
        ser = db.series.get(session["series_id"])
        if ser is not None:
            ser["active_session_count"] = max(0, ser["active_session_count"] - 1)
            touch(ser)


# --------------------------------------------------------------------------
# Studio-side session CANCEL cascade (PRD §3.10) — full refund, fee waived.
# --------------------------------------------------------------------------
def cancel_session(session):
    child_bookings = [b for b in db.bookings.values() if b["session_id"] == session["id"]]
    for b in child_bookings:
        if b["lifecycle_status"] in ("PENDING", "CONFIRMED"):
            was_paid = b["lifecycle_status"] == "CONFIRMED"
            member = db.members[b["member_id"]]
            if was_paid:
                full = b["charge_cents"]
                b["refund_cents"] = full
                refund_gift_card_then_wallet(member, b, full)
                b["payment_status"] = "REFUNDED"
            else:
                # pending booking: never paid
                b["refund_cents"] = 0
            b["lifecycle_status"] = "CANCELLED"
            touch(b)
    # expire WAITING waitlist entries
    for w in db.waitlist_entries.values():
        if w["session_id"] == session["id"] and w["queue_status"] == "WAITING":
            w["queue_status"] = "EXPIRED"
            touch(w)
    session["status"] = "CANCELLED"
    touch(session)
    if session.get("series_id"):
        ser = db.series.get(session["series_id"])
        if ser is not None:
            ser["active_session_count"] = max(0, ser["active_session_count"] - 1)
            touch(ser)
