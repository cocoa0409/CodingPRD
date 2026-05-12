"""Cascade behaviors: delist, cancel, settlement reversal."""

from db import db, new_id
from clock import now_iso
from services.audit import append_audit
from services.calculations import compute_reversal_split


def _append_reversal_for_ticket(ticket, parent_posting):
    """Append a REVERSAL Settlement row for the given refunded/exchanged ticket
    whose original POSTING is in status POSTED.
    """
    showtime = db.showtimes.get(ticket["showtime_id"])
    distributor_id = showtime["distributor_id"] if showtime else None
    distributor = db.distributors.get(distributor_id) if distributor_id else None
    default_bps = distributor["default_split_ratio_bps"] if distributor else 0

    split = compute_reversal_split(ticket, default_bps)
    rev_id = new_id()
    rev_row = {
        "id": rev_id,
        "showtime_id": ticket["showtime_id"],
        "cycle_label": parent_posting["cycle_label"],
        "kind": "REVERSAL",
        "status": "POSTED",
        "gross_cents": split["gross_cents"],
        "platform_commission_cents": split["platform_commission_cents"],
        "tax_cents": split["tax_cents"],
        "distributor_amount_cents": split["distributor_amount_cents"],
        "cinema_amount_cents": split["cinema_amount_cents"],
        "parent_settlement_id": parent_posting["id"],
        "created_at": now_iso(),
    }
    db.settlements[rev_id] = rev_row
    # If sum across REVERSAL rows referencing this POSTING + posting.gross_cents == 0,
    # the POSTING becomes REVERSED.
    rev_sum = sum(
        s["gross_cents"] for s in db.settlements.values()
        if s["kind"] == "REVERSAL" and s.get("parent_settlement_id") == parent_posting["id"]
    )
    if rev_sum + parent_posting["gross_cents"] == 0:
        if parent_posting["status"] != "REVERSED":
            parent_posting["status"] = "REVERSED"
            # AuditLog action SETTLEMENT_REVERSE
            append_audit("system", "system", "SETTLEMENT_REVERSE", "Settlement", parent_posting["id"], {"status": "REVERSED"})
    return rev_row


def _refund_ticket_no_state_check(ticket):
    """Mark a VALID ticket REFUNDED with refunded_at = now, recompute showtime aggregates,
    and append a REVERSAL row if its POSTING is POSTED.
    """
    if ticket["status"] != "VALID":
        return None
    ticket["status"] = "REFUNDED"
    ticket["refunded_at"] = now_iso()
    ticket["updated_at"] = now_iso()
    ticket["version"] = ticket.get("version", 1) + 1

    # Find original POSTING Settlement for this ticket's showtime
    posting = None
    for s in db.settlements.values():
        if s["kind"] == "POSTING" and s["showtime_id"] == ticket["showtime_id"]:
            posting = s
            break
    if posting and posting["status"] == "POSTED":
        _append_reversal_for_ticket(ticket, posting)
    return ticket


def cascade_film_delist(film, actor_role, actor_id):
    """Cascade: SCHEDULED showtimes -> CANCELLED with cancel_reason=INCIDENT;
    VALID tickets -> REFUNDED; POSTED settlements -> REVERSAL rows; ScheduleAdjustment rows.
    """
    film_id = film["id"]
    showtimes_to_cancel = [
        s for s in db.showtimes.values()
        if s["film_id"] == film_id and s["lifecycle_status"] == "SCHEDULED"
    ]
    for s in showtimes_to_cancel:
        s["lifecycle_status"] = "CANCELLED"
        s["sale_status"] = "CLOSED"
        s["cancel_reason"] = "INCIDENT"
        s["updated_at"] = now_iso()
        s["version"] = s.get("version", 1) + 1

        # Refund VALID tickets
        affected_ticket_ids = []
        for t in list(db.tickets.values()):
            if t["showtime_id"] != s["id"]:
                continue
            if t["status"] == "VALID":
                _refund_ticket_no_state_check(t)
                affected_ticket_ids.append(t["id"])

        # Recompute aggregates after refunds
        from services.showtime_aggregates import recompute_showtime_aggregates
        recompute_showtime_aggregates(s)

        # ScheduleAdjustment
        adj_id = new_id()
        adj = {
            "id": adj_id,
            "showtime_id": s["id"],
            "adjustment_type": "CANCEL",
            "reason": "INCIDENT",
            "affected_ticket_ids": affected_ticket_ids,
            "notifications_dispatched": len(affected_ticket_ids),
            "archived_at": now_iso(),
            "created_at": now_iso(),
        }
        db.schedule_adjustments[adj_id] = adj


def cascade_showtime_cancel(showtime, cancel_reason, exchange_to_showtime_id, actor_role, actor_id):
    """Cascade after showtime cancel. Returns list of affected_ticket_ids."""
    affected_ticket_ids = []
    for t in list(db.tickets.values()):
        if t["showtime_id"] != showtime["id"]:
            continue
        if t["status"] != "VALID":
            continue

        if exchange_to_showtime_id:
            # Exchange path
            t["status"] = "EXCHANGED"
            t["exchanged_to_showtime_id"] = exchange_to_showtime_id
            t["refunded_at"] = now_iso()
            t["updated_at"] = now_iso()
            t["version"] = t.get("version", 1) + 1
            # Create a new child Ticket on destination
            new_ticket_id = new_id()
            child = {
                "id": new_ticket_id,
                "showtime_id": exchange_to_showtime_id,
                "buyer_external_id": t["buyer_external_id"],
                "paid_amount_cents": t["paid_amount_cents"],
                "promo_code": t.get("promo_code"),
                "status": "VALID",
                "exchanged_to_showtime_id": None,
                "purchased_at": now_iso(),
                "refunded_at": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "version": 1,
            }
            db.tickets[new_ticket_id] = child
            # Recompute destination showtime aggregates
            dest = db.showtimes.get(exchange_to_showtime_id)
            if dest:
                from services.showtime_aggregates import recompute_showtime_aggregates
                recompute_showtime_aggregates(dest)
        else:
            # Refund path
            t["status"] = "REFUNDED"
            t["refunded_at"] = now_iso()
            t["updated_at"] = now_iso()
            t["version"] = t.get("version", 1) + 1

        # REVERSAL settlement if POSTING POSTED
        posting = None
        for s in db.settlements.values():
            if s["kind"] == "POSTING" and s["showtime_id"] == t["showtime_id"]:
                posting = s
                break
        if posting and posting["status"] == "POSTED":
            _append_reversal_for_ticket(t, posting)

        affected_ticket_ids.append(t["id"])

    # Recompute source showtime aggregates
    from services.showtime_aggregates import recompute_showtime_aggregates
    recompute_showtime_aggregates(showtime)

    # ScheduleAdjustment
    adj_id = new_id()
    adj = {
        "id": adj_id,
        "showtime_id": showtime["id"],
        "adjustment_type": "CANCEL",
        "reason": cancel_reason,
        "affected_ticket_ids": affected_ticket_ids,
        "notifications_dispatched": len(affected_ticket_ids),
        "archived_at": now_iso(),
        "created_at": now_iso(),
    }
    db.schedule_adjustments[adj_id] = adj

    # EXCHANGE_TARGET adjustment row if exchange path
    if exchange_to_showtime_id and affected_ticket_ids:
        ex_adj_id = new_id()
        ex_adj = {
            "id": ex_adj_id,
            "showtime_id": exchange_to_showtime_id,
            "adjustment_type": "EXCHANGE_TARGET",
            "reason": cancel_reason,
            "affected_ticket_ids": list(affected_ticket_ids),
            "notifications_dispatched": 0,
            "archived_at": now_iso(),
            "created_at": now_iso(),
        }
        db.schedule_adjustments[ex_adj_id] = ex_adj

    return affected_ticket_ids


def append_reversal_for_individual_ticket(ticket):
    """For refund/exchange action endpoints — append a REVERSAL row if POSTING is POSTED."""
    posting = None
    for s in db.settlements.values():
        if s["kind"] == "POSTING" and s["showtime_id"] == ticket["showtime_id"]:
            posting = s
            break
    if posting and posting["status"] == "POSTED":
        _append_reversal_for_ticket(ticket, posting)
