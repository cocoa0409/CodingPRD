"""Existence lookups (validation #3) and fleet-ownership resolution (validation #4)."""
from db import db
from errors import err

# Enum vocabularies (SCAFFOLD §1.1)
ACCOUNT_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
VEHICLE_STATUSES = ("ACTIVE", "OUT_OF_SERVICE", "RETIRED")
DRIVER_STATUSES = ("ACTIVE", "INACTIVE")
CARD_STATUSES = ("ISSUED", "ACTIVE", "SUSPENDED", "CANCELLED")
ASSIGNMENT_STATUSES = ("ACTIVE", "SUPERSEDED", "ENDED")
PRODUCTS = ("UNLEADED", "PREMIUM", "DIESEL", "DEF")
POSTING_STATUSES = ("AUTHORIZED", "CAPTURED", "SETTLED", "VOIDED")
REVIEW_STATUSES = ("CLEAN", "FLAGGED", "CLEARED")
ALERT_STATUSES = ("OPEN", "INVESTIGATING", "CONFIRMED", "DISMISSED")
RULE_CODES = ("OVER_TANK_FILL", "OUTSIDE_HOURS", "PRODUCT_MISMATCH")
FAULT_STATUSES = ("OPEN", "MAINTENANCE_SCHEDULED", "MAINTENANCE_COMPLETE", "CLEARED")
SEVERITIES = ("INFO", "WARN", "CRITICAL")
REPORT_STATUSES = ("DRAFT", "FILED")

MAINTENANCE_BUFFER_HOURS = 2

DEFAULT_REBATE_TIERS = [
    {"min_month_gallons": 0, "cpg_rebate": 5},
    {"min_month_gallons": 1000, "cpg_rebate": 8},
    {"min_month_gallons": 5000, "cpg_rebate": 12},
]

TAX_RATE_CENTS = {"CA": 68, "AZ": 26, "NV": 33, "OR": 38, "TX": 20}


def _get(table, key, error_id):
    record = table.get(key)
    if record is None:
        raise err(error_id)
    return record


def get_account(account_id):
    return _get(db.fleet_accounts, account_id, "ERR_FLEET_ACCOUNT_NOT_FOUND")


def get_vehicle(vehicle_id):
    return _get(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")


def get_driver(driver_id):
    return _get(db.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")


def get_card(card_id):
    return _get(db.fuel_cards, card_id, "ERR_CARD_NOT_FOUND")


def get_assignment(assignment_id):
    return _get(db.card_assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_transaction(transaction_id):
    return _get(db.transactions, transaction_id, "ERR_TRANSACTION_NOT_FOUND")


def get_alert(alert_id):
    return _get(db.fraud_alerts, alert_id, "ERR_ALERT_NOT_FOUND")


def get_fault(fault_id):
    return _get(db.telematics_faults, fault_id, "ERR_FAULT_NOT_FOUND")


def get_report(report_id):
    return _get(db.ifta_reports, report_id, "ERR_REPORT_NOT_FOUND")


# ---------------------------------------------------------------------------
# Ownership resolution — PRD §2.1: a resource belongs to a fleet directly through
# its fleet_account_id, or transitively through the card / vehicle / driver it
# references.
# ---------------------------------------------------------------------------

def account_of_transaction(txn):
    return db.fuel_cards[txn["card_id"]]["fleet_account_id"]


def account_of_assignment(assignment):
    return db.fuel_cards[assignment["card_id"]]["fleet_account_id"]


def account_of_alert(alert):
    return db.fuel_cards[alert["card_id"]]["fleet_account_id"]


def account_of_fault(fault):
    return db.vehicles[fault["vehicle_id"]]["fleet_account_id"]


def account_transactions(account_id):
    return [t for t in db.transactions.values() if account_of_transaction(t) == account_id]


def card_transactions(card_id):
    return [t for t in db.transactions.values() if t["card_id"] == card_id]


def vehicle_transactions(vehicle_id):
    return [t for t in db.transactions.values() if t.get("vehicle_id") == vehicle_id]


def txn_order_key(txn):
    """purchased_at ascending, ties broken by created_at ascending (PRD §3.4/§3.8)."""
    return (txn["_purchased_at_dt"], txn["created_at"], txn["_seq"])
