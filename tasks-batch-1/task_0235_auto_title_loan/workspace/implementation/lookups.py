"""Existence resolution and cross-entity lookups (PRD 2.5).

Path/body identifiers are resolved left-to-right; the first that does not
resolve raises ERR_NOT_FOUND.
"""
import db
from errors import err


def get_or_404(store, entity_id):
    ent = store.get(entity_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "resource %s not found" % entity_id)
    return ent


def regulatory_profile_for_state(state_code):
    """Find the RegulatoryProfile governing a state, or None if not configured."""
    for prof in db.regulatory_profiles.values():
        if prof["state_code"] == state_code:
            return prof
    return None


def borrower_regulatory_profile(borrower):
    """Resolve the regulatory profile for a borrower's state."""
    return regulatory_profile_for_state(borrower["state_code"])


def device_for_vehicle(vehicle_id):
    """Find the device installed on a vehicle (vehicle_id is unique across devices)."""
    for dev in db.devices.values():
        if dev["vehicle_id"] == vehicle_id:
            return dev
    return None


def active_loan_for_vehicle(vehicle_id):
    """The single loan where loan.vehicle_id == vehicle_id AND payoff_status==OUTSTANDING."""
    for loan in db.loans.values():
        if loan["vehicle_id"] == vehicle_id and loan["payoff_status"] == "OUTSTANDING":
            return loan
    return None


def installments_for_loan(loan_id):
    rows = [i for i in db.installments.values() if i["loan_id"] == loan_id]
    rows.sort(key=lambda r: r["sequence_no"])
    return rows


def title_lien_for_loan(loan_id):
    for lien in db.title_liens.values():
        if lien["loan_id"] == loan_id:
            return lien
    return None


ACTIVE_REPO_STATES = {"ORDERED", "ASSIGNED", "RECOVERED"}


def active_repo_for_loan(loan_id):
    """Return a non-terminal repossession order for the loan, if any."""
    for order in db.repossession_orders.values():
        if order["loan_id"] == loan_id and order["status"] in ACTIVE_REPO_STATES:
            return order
    return None


def assignments_for_order(order_id):
    return [a for a in db.assignments.values() if a["repossession_order_id"] == order_id]
