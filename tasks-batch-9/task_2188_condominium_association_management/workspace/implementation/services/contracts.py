"""Vendor contract / work order encumbrance bookkeeping -- Invariant E (PRD 3.6)."""
import clock
import db

CONTRACT_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "ACTIVE", "SUSPENDED",
                     "TERMINATED", "EXPIRED")
SUSPENSION_REASONS = ("NONE", "INSURANCE_LAPSED", "PERFORMANCE", "ELEMENT_SPEC_CHANGED")
ORDER_STATUSES = ("SCHEDULED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "INVOICED",
                  "CANCELLED")
HOLD_REASONS = ("NONE", "CONTRACT_SUSPENDED", "ELEMENT_UNAVAILABLE", "FUNDING")

# Invariant E summation set: CANCELLED and INVOICED orders contribute 0.
COMMITTED_STATUSES = ("SCHEDULED", "IN_PROGRESS", "ON_HOLD", "COMPLETED")


def orders_of(contract_id):
    return db.sorted_rows("work_orders", lambda w: w["contract_id"] == contract_id)


def recompute_committed(contract):
    """Invariant E: committed_cents is the sum of encumbered_cents over the orders
    still inside the summation set; invoiced_cents the sum of final_cost_cents over
    INVOICED orders."""
    committed = 0
    invoiced = 0
    for w in db.store["work_orders"].values():
        if w["contract_id"] != contract["id"]:
            continue
        if w["status"] in COMMITTED_STATUSES:
            committed += w["encumbered_cents"]
        elif w["status"] == "INVOICED":
            invoiced += w["final_cost_cents"] or 0
    contract["committed_cents"] = committed
    contract["invoiced_cents"] = invoiced
    return contract


def hold_open_orders(contract, reason="CONTRACT_SUSPENDED"):
    """SCHEDULED / IN_PROGRESS orders go ON_HOLD, encumbrances retained."""
    held = []
    for w in orders_of(contract["id"]):
        if w["status"] in ("SCHEDULED", "IN_PROGRESS"):
            w["status"] = "ON_HOLD"
            w["hold_reason"] = reason
            db.touch(w)
            held.append(w)
    return held


def cancel_open_orders(contract, statuses=("SCHEDULED", "ON_HOLD")):
    """Open orders are CANCELLED with encumbered_cents released to 0."""
    cancelled = []
    for w in orders_of(contract["id"]):
        if w["status"] in statuses:
            w["status"] = "CANCELLED"
            w["encumbered_cents"] = 0
            db.touch(w)
            cancelled.append(w)
    recompute_committed(contract)
    return cancelled


def sweep_insurance_lapse(contract):
    """ACTIVE + insurance_cert_expires_at at or before the clock -> SUSPENDED."""
    now = clock.now()
    if contract["status"] != "ACTIVE":
        return False
    expires = contract.get("insurance_cert_expires_at")
    if expires is None or expires > now:
        return False
    contract["status"] = "SUSPENDED"
    contract["suspension_reason"] = "INSURANCE_LAPSED"
    hold_open_orders(contract, "CONTRACT_SUSPENDED")
    recompute_committed(contract)
    db.touch(contract)
    return True


def sweep_term_expiry(contract):
    """ACTIVE / SUSPENDED + effective_to reached or passed -> EXPIRED."""
    now = clock.now()
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        return False
    effective_to = contract.get("effective_to")
    if effective_to is None or now < effective_to:
        return False
    contract["status"] = "EXPIRED"
    cancel_open_orders(contract, ("SCHEDULED", "ON_HOLD"))
    recompute_committed(contract)
    db.touch(contract)
    return True


def insurance_lapsed(contract):
    expires = contract.get("insurance_cert_expires_at")
    return expires is None or expires <= clock.now()
