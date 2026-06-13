"""Cross-cutting domain helpers: lazy grace transition, police-hold lookups."""
from db import store
from models import touch


def schedule_for_state(state_code):
    """Return the StateRateSchedule governing a state_code, or None."""
    for s in store.state_schedules.values():
        if s["state_code"] == state_code:
            return s
    return None


def rederive_grace(loan):
    """Lazy ACTIVE -> IN_GRACE drift (PRD §2.9).

    If the loan is ACTIVE and the clock has reached/passed term_end_at, move it
    to IN_GRACE. This counts as a mutation (refreshes updated_at, bumps version).
    Returns the loan.
    """
    if loan["status"] == "ACTIVE" and store.now() >= loan["term_end_at"]:
        loan["status"] = "IN_GRACE"
        touch(loan)
    return loan


def active_hold_on_pawn_item(pawn_item_id):
    """Return an ACTIVE PoliceHold naming this pawn item, or None."""
    for h in store.police_holds.values():
        if (
            h["status"] == "ACTIVE"
            and h["subject_kind"] == "PAWN_ITEM"
            and h["pawn_item_id"] == pawn_item_id
        ):
            return h
    return None


def active_hold_on_inventory_item(inventory_item_id):
    """Return an ACTIVE PoliceHold naming this inventory item, or None."""
    for h in store.police_holds.values():
        if (
            h["status"] == "ACTIVE"
            and h["subject_kind"] == "INVENTORY_ITEM"
            and h["inventory_item_id"] == inventory_item_id
        ):
            return h
    return None


def loan_for_pawn_item(pawn_item_id, statuses=None):
    """Return the (most recent) loan whose pawn_item_id matches, optionally filtered by status."""
    matches = [
        l for l in store.loans.values()
        if l["pawn_item_id"] == pawn_item_id
        and (statuses is None or l["status"] in statuses)
    ]
    if not matches:
        return None
    return max(matches, key=lambda l: l["_seq"])


def chargeable_tx_exists(loan_id):
    """True if any EXTENSION_FEE / RENEWAL_FEE / REDEMPTION_PAYOFF tx exists for the loan."""
    chargeable = {"EXTENSION_FEE", "RENEWAL_FEE", "REDEMPTION_PAYOFF"}
    for t in store.finance_transactions.values():
        if t["loan_id"] == loan_id and t["kind"] in chargeable:
            return True
    return False
