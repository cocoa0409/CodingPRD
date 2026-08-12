"""Custodian statement ingestion + synchronous reconciliation (PRD 3.9)."""

import db
import util
from helpers import stamp_new
from domain import open_lots


def _add_break(statement, account_id, security_id, break_type,
               expected_qty=0.0, reported_qty=0.0,
               event_id=None, expected_cash=None, reported_cash=None,
               auto_claim_id=None):
    brk = {
        "statement_id": statement["id"],
        "event_id": event_id,
        "account_id": account_id,
        "security_id": security_id,
        "break_type": break_type,
        "expected_quantity": float(util.round4_half_up(expected_qty)),
        "reported_quantity": float(util.round4_half_up(reported_qty)),
        "expected_cash_cents": expected_cash,
        "reported_cash_cents": reported_cash,
        "auto_claim_id": auto_claim_id,
        "resolution": None,
        "resolution_note": None,
        "status": "OPEN",
    }
    stamp_new(brk)
    db.insert("recon_breaks", brk)
    return brk


def _auto_file_claim(statement, brk, event, entitlement, diff_shares):
    """Auto-file a claim for a MISSED_ENTITLEMENT break when the entitlement is
    MISSED or SETTLED and no FILED claim exists for it. claimed_amount_cents is
    the absolute share difference valued under the EVENT_TERMS basis."""
    if entitlement is None or entitlement["status"] not in ("MISSED", "SETTLED"):
        return None
    for claim in db.all_rows("claims"):
        if claim["entitlement_id"] == entitlement["id"] and claim["review_status"] == "FILED":
            return None
    price = event["terms"].get("price_per_share_cents", 0) if event else 0
    claimed = util.round_half_up_cents(util.D(diff_shares) * util.D(price))
    claim = {
        "event_id": brk["event_id"],
        "entitlement_id": entitlement["id"],
        "account_id": brk["account_id"],
        "reason": "MISSED_ENTITLEMENT",
        "claimed_amount_cents": claimed,
        "market_price_cents": None,
        "compensation_cents": None,
        "filed_by_user_id": "system",
        "reviewed_by_user_id": None,
        "review_status": "FILED",
        "payment_status": "UNPAID",
    }
    stamp_new(claim)
    db.insert("claims", claim)
    return claim


def reconcile_statement(statement):
    """Run reconciliation synchronously over the statement lines, top-to-bottom
    in the submitted array order. Zero tolerance: exact equality only."""
    for line in statement["lines"]:
        account_id = line["account_id"]
        security_id = line["security_id"]
        event_id = line.get("event_id")
        cash_cents = line.get("cash_cents")
        reported_qty = util.dec_of(line["quantity"])

        if event_id is not None and cash_cents is not None:
            # CASH reconciliation for that event
            expected_cash = 0
            for bl in db.all_rows("booking_lines"):
                booking = db.get("bookings", bl["booking_id"])
                if booking is None or booking["status"] != "POSTED":
                    continue
                if booking["event_id"] != event_id:
                    continue
                ent = db.get("entitlements", bl["entitlement_id"])
                if ent is not None and ent["account_id"] == account_id:
                    expected_cash += bl["cash_delta_cents"]
            if expected_cash != cash_cents:
                _add_break(statement, account_id, security_id, "CASH_MISMATCH",
                           expected_qty=0.0, reported_qty=reported_qty,
                           event_id=event_id,
                           expected_cash=expected_cash, reported_cash=cash_cents)
        elif event_id is not None:
            # ENTITLEMENT reconciliation
            event = db.get("events", event_id)
            ent = None
            for e in db.all_rows("entitlements"):
                if (e["event_id"] == event_id and e["account_id"] == account_id
                        and e["status"] != "SUPERSEDED"):
                    ent = e  # latest non-SUPERSEDED
            expected = util.D(ent["entitled_shares"]) if ent is not None else util.D(0)
            if expected != util.round4_half_up(reported_qty):
                brk = _add_break(statement, account_id, security_id,
                                 "MISSED_ENTITLEMENT",
                                 expected_qty=expected, reported_qty=reported_qty,
                                 event_id=event_id)
                diff = abs(expected - util.round4_half_up(reported_qty))
                claim = _auto_file_claim(statement, brk, event, ent, diff)
                if claim is not None:
                    brk["auto_claim_id"] = claim["id"]
        else:
            # POSITION reconciliation
            expected = sum((util.dec_of(l["quantity"]) for l in
                            open_lots(account_id, security_id)), util.D(0))
            if util.round4_half_up(expected) != util.round4_half_up(reported_qty):
                _add_break(statement, account_id, security_id, "POSITION_MISMATCH",
                           expected_qty=expected, reported_qty=reported_qty)
