"""Multi-row cascades shared by the enforcement, exception and sweep workflows."""

from calc import latest_non_rescinded_notice
from store import now_iso, sort_rows, store, touch

OPEN_VIOLATION_STATUSES = ("DETECTED", "NOTICED", "DISPUTED")


def reinstate_from_suspension(reseller, ended_at):
    """PRD §3.7 — a served or rescinded suspension returns the reseller to supply."""
    reseller["authorization_status"] = "AUTHORIZED"
    reseller["supply_status"] = "OPEN"
    reseller["hold_reason"] = "NONE"
    reseller["last_suspension_ended_at"] = ended_at
    reseller["suspension_ends_at"] = None
    touch(reseller)


def strip_assessed_points(violation, clear_floor=True):
    """Remove a violation's assessed points from its reseller's ledger."""
    reseller = store.resellers.get(violation.get("reseller_id"))
    points = violation.get("assessed_points")
    if reseller is not None and points:
        reseller["violation_points_total"] = reseller["violation_points_total"] - points
        touch(reseller)
    violation["assessed_points"] = None
    if clear_floor:
        violation["assessed_floor_cents"] = None
        violation["cure_deadline_at"] = None
    return reseller


def rescind_notice(notice, closed_reason):
    """Move a notice to RESCINDED, reinstating a suspended reseller where due."""
    was_suspension = notice.get("rung") == "SUSPENSION"
    notice["status"] = "RESCINDED"
    notice["closed_reason"] = closed_reason
    touch(notice)
    reseller = store.resellers.get(notice.get("reseller_id"))
    if was_suspension and reseller is not None and reseller["authorization_status"] == "SUSPENDED":
        reinstate_from_suspension(reseller, now_iso())
    return notice


def rescind_latest_notice(violation, closed_reason):
    notice = latest_non_rescinded_notice(violation["id"])
    if notice is None or notice["status"] not in ("ISSUED", "ACKNOWLEDGED"):
        return None
    return rescind_notice(notice, closed_reason)


def recall_units_of_reseller(reseller_id):
    count = 0
    for unit in sort_rows(list(store.serial_units.values())):
        if unit.get("downstream_reseller_id") != reseller_id:
            continue
        if unit["status"] != "SHIPPED_TO_RESELLER":
            continue
        unit["status"] = "RECALLED"
        touch(unit)
        count += 1
    return count


def terminate_agreements_of_reseller(reseller_id):
    """PRD §3.4 — an ACTIVE agreement terminates and recalls shipped stock."""
    terminated = 0
    for agreement in sort_rows(list(store.agreements.values())):
        if agreement["reseller_id"] != reseller_id or agreement["status"] != "ACTIVE":
            continue
        agreement["status"] = "TERMINATED"
        agreement["closed_reason"] = "SUPPLY_TERMINATED"
        touch(agreement)
        terminated += 1
        recall_units_of_reseller(reseller_id)
    return terminated


def terminate_reseller(reseller):
    """PRD §3.7 — drive both axes to their terminal condition and cascade twice over."""
    reseller["authorization_status"] = "TERMINATED"
    reseller["supply_status"] = "CUT_OFF"
    reseller["hold_reason"] = "TERMINATION"
    reseller["terminated_at"] = now_iso()
    reseller["suspension_ends_at"] = None
    touch(reseller)

    for violation in sort_rows(list(store.violations.values())):
        if violation["reseller_id"] != reseller["id"]:
            continue
        if violation["status"] not in OPEN_VIOLATION_STATUSES:
            continue
        violation["status"] = "CLOSED_MOOT"
        violation["resolution_reason"] = "RESELLER_TERMINATED"
        touch(violation)

    terminate_agreements_of_reseller(reseller["id"])


def expire_agreement(agreement):
    """PRD §3.4 / §3.9 phase 1 — term lapse pushes only the supply axis."""
    agreement["status"] = "EXPIRED"
    agreement["closed_reason"] = "TERM_EXPIRED"
    touch(agreement)
    reseller = store.resellers.get(agreement["reseller_id"])
    if reseller is not None:
        reseller["supply_status"] = "HOLD"
        reseller["hold_reason"] = "AGREEMENT_EXPIRED"
        touch(reseller)


def expire_exception(exception):
    """PRD §3.6 / §3.9 phase 2 — window end releases the product's exception count."""
    exception["status"] = "EXPIRED"
    touch(exception)
    product = store.products.get(exception["product_id"])
    if product is not None:
        product["open_exception_count"] = max(0, product["open_exception_count"] - 1)
        touch(product)
