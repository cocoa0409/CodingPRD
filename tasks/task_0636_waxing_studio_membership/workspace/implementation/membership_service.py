"""Membership lifecycle: activate, freeze, unfreeze, renew, cancel.

State machine and calculations per PRD 3.3 and 3.4.
"""
from db import db
from errors import err
from clock import clock
from mutate import touch
from util import add_days
from credits import membership_credit_balance, write_ledger_entry

CREDIT_PAR_CENTS = 100  # PRD 3.3 par-value forfeit


def activate(mb):
    # PRD 3.3: permitted only while PENDING.
    if mb["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "membership not PENDING")
    mb["status"] = "ACTIVE"
    mb["cycle_anchor_utc"] = clock.get()  # cycle_index stays 0
    grant = 0 if mb["tier"] == "UNLIMITED" else mb["monthly_credit_grant"]
    write_ledger_entry(mb, "GRANT", grant, "MEMBERSHIP", mb["id"])
    touch(mb)
    return mb


def freeze(mb, freeze_days):
    # PRD 3.3: permitted only while ACTIVE; freeze_days integer 1..90.
    if mb["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "membership not ACTIVE")
    balance = membership_credit_balance(mb["id"])
    mb["status"] = "FROZEN"
    mb["freeze_until_utc"] = add_days(clock.get(), freeze_days)
    mb["frozen_cycle_credits"] = balance
    write_ledger_entry(mb, "FREEZE_PARK", -balance, "MEMBERSHIP", mb["id"])
    touch(mb)
    return mb


def unfreeze(mb):
    # PRD 3.3: returns a FROZEN membership to ACTIVE.
    if mb["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "membership not FROZEN")
    _do_unfreeze(mb)
    touch(mb)
    return mb


def _do_unfreeze(mb):
    """Unfreeze body shared by the endpoint and the freeze-expiry sweep."""
    parked = mb["frozen_cycle_credits"]
    mb["status"] = "ACTIVE"
    mb["freeze_until_utc"] = None
    write_ledger_entry(mb, "UNFREEZE_RESTORE", parked, "MEMBERSHIP", mb["id"])
    mb["frozen_cycle_credits"] = 0


def _cycle_rollover_settlement(mb):
    """calc cycle_rollover_settlement — pinned evaluation order (PRD 3.3)."""
    pre_renew_balance = membership_credit_balance(mb["id"])
    capped_carryover = min(pre_renew_balance, mb["max_rollover_credits"])
    forfeit = pre_renew_balance - capped_carryover
    if forfeit > 0:
        write_ledger_entry(mb, "ROLLOVER_FORFEIT", -forfeit, "MEMBERSHIP", mb["id"])
    grant = 0 if mb["tier"] == "UNLIMITED" else mb["monthly_credit_grant"]
    write_ledger_entry(mb, "GRANT", grant, "MEMBERSHIP", mb["id"])


def renew(mb, payment_outcome):
    # PRD 3.3 renewal. ACTIVE+FAILED -> PAST_DUE; SUCCEEDED on ACTIVE or PAST_DUE
    # runs the settlement-then-grant cascade and advances the cycle.
    if payment_outcome == "FAILED":
        if mb["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "FAILED renewal only on ACTIVE membership")
        # No GRANT, credit_balance unchanged, only version advances.
        mb["status"] = "PAST_DUE"
        touch(mb)
        return mb
    # SUCCEEDED
    if mb["status"] not in ("ACTIVE", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "SUCCEEDED renewal only on ACTIVE/PAST_DUE")
    # cycle_index advances BEFORE writing ledger entries so that the new entries
    # carry the new cycle_index. The rollover settlement reads the pre-renewal
    # balance, which is independent of cycle_index.
    mb["cycle_anchor_utc"] = add_days(mb["cycle_anchor_utc"], 30)
    mb["cycle_index"] = mb["cycle_index"] + 1
    _cycle_rollover_settlement(mb)
    mb["status"] = "ACTIVE"
    touch(mb)
    return mb


def cancel(mb):
    # PRD 3.3: permitted whenever not already CANCELLED.
    if mb["status"] == "CANCELLED":
        raise err("ERR_INVALID_STATE", "membership already CANCELLED")
    # Cascade: cancel every BOOKED/CHECKED_IN CREDIT reservation on this
    # membership, releasing held credits through a REFUND ledger entry.
    # Imported lazily to avoid a circular import with reservation_service.
    from reservation_service import release_credits_for_membership_cancel
    for res in list(db.reservations.values()):
        if res["membership_id"] != mb["id"]:
            continue
        if res["payment_method"] != "CREDIT":
            continue
        if res["booking_status"] in ("BOOKED", "CHECKED_IN"):
            release_credits_for_membership_cancel(res, mb)
    # After refunds land, the entire remaining credit_balance is forfeited to the
    # member's wallet at par (100 cents/credit), then recomputed to 0.
    remaining = membership_credit_balance(mb["id"])
    if remaining != 0:
        write_ledger_entry(mb, "ROLLOVER_FORFEIT", -remaining, "MEMBERSHIP", mb["id"])
    if remaining > 0:
        member = db.members[mb["member_id"]]
        member["wallet_credit_cents"] += remaining * CREDIT_PAR_CENTS
        touch(member)
    mb["status"] = "CANCELLED"
    touch(mb)
    return mb
