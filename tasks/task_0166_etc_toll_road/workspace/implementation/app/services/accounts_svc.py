"""Recompute Account.outstanding_fine_cents and cascade status transitions."""
from ..store import store
from .pricing import SUSPEND_THRESHOLD_CENTS


def _account_pending_fine_sum(account_id: str) -> int:
    total = 0
    for fine in store.fines.values():
        viol = store.violations.get(fine.get("violation_id"))
        if viol is None or viol.get("account_id") != account_id:
            continue
        if fine["settlement_status"] in ("PENDING", "OVERDUE"):
            total += int(fine["amount_cents"])
    return total


def recompute_outstanding_and_cascade(account_id: str) -> None:
    """Recompute outstanding fines and cascade ACTIVE<->SUSPENDED on the account.

    Cascades update version & timestamps on each affected vehicle/transponder.
    """
    account = store.accounts.get(account_id)
    if account is None:
        return
    total = _account_pending_fine_sum(account_id)
    account["outstanding_fine_cents"] = total

    current_status = account["status"]

    if current_status == "ACTIVE" and total >= SUSPEND_THRESHOLD_CENTS:
        _suspend_account(account)
    elif current_status == "SUSPENDED" and total < SUSPEND_THRESHOLD_CENTS:
        _reactivate_account(account)
    else:
        # Even if status didn't flip, the outstanding total changed; bump version/updated_at
        store.bump(account)


def _suspend_account(account: dict) -> None:
    account["status"] = "SUSPENDED"
    store.bump(account)
    for v in store.vehicles_of(account["id"]):
        if v["status"] != "BLOCKED":
            v["status"] = "BLOCKED"
            store.bump(v)
    for t in store.transponders_of(account["id"]):
        if t["status"] == "ACTIVE":
            t["status"] = "SUSPENDED"
            store.bump(t)


def _reactivate_account(account: dict) -> None:
    account["status"] = "ACTIVE"
    store.bump(account)
    for v in store.vehicles_of(account["id"]):
        # Restore only vehicles whose only blocker was the account suspension.
        # If the vehicle is also escalated by a fine ESCALATED violation, keep BLOCKED.
        if v["status"] == "BLOCKED" and not _vehicle_has_escalated_violation(v["id"]):
            v["status"] = "ACTIVE"
            store.bump(v)
    for t in store.transponders_of(account["id"]):
        if t["status"] == "SUSPENDED" and t.get("bound_vehicle_id"):
            bound_vehicle = store.vehicles.get(t["bound_vehicle_id"])
            if bound_vehicle and bound_vehicle["status"] == "ACTIVE":
                t["status"] = "ACTIVE"
                store.bump(t)


def _vehicle_has_escalated_violation(vehicle_id: str) -> bool:
    for viol in store.violations.values():
        if viol.get("vehicle_id") == vehicle_id and viol.get("status") == "ESCALATED":
            return True
    return False


def restore_vehicle_if_escalated(vehicle_id: str) -> None:
    """If a vehicle has an ESCALATED violation we just cleared/dismissed, and no
    other ESCALATED violations remain, restore it to ACTIVE (assuming account is ACTIVE)."""
    vehicle = store.vehicles.get(vehicle_id)
    if vehicle is None:
        return
    if vehicle["status"] != "BLOCKED":
        return
    if _vehicle_has_escalated_violation(vehicle_id):
        return
    account = store.accounts.get(vehicle["account_id"])
    if account is None or account["status"] != "ACTIVE":
        return
    vehicle["status"] = "ACTIVE"
    store.bump(vehicle)
    # Possibly restore a previously-suspended transponder bound to this vehicle
    for t in store.transponders.values():
        if t.get("bound_vehicle_id") == vehicle_id and t["status"] == "SUSPENDED":
            owner = store.accounts.get(t["account_id"])
            if owner and owner["status"] == "ACTIVE":
                t["status"] = "ACTIVE"
                store.bump(t)
