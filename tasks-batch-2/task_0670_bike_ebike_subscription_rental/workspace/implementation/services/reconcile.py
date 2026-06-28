"""Derived-count reconciliation (PRD §2.5). Counts are fully recomputed,
never blindly incremented."""
from db import db


def recompute_model_counts(model_id):
    model = db.bike_models.get(model_id)
    if model is None:
        return
    bikes = [b for b in db.bikes.values() if b["model_id"] == model_id]
    model["total_bikes"] = len(bikes)
    model["available_count"] = sum(1 for b in bikes if b["bike_status"] == "AVAILABLE")


def recompute_active_rental_count(account_id):
    account = db.accounts.get(account_id)
    if account is None:
        return
    active = {"RESERVED", "DELIVERED", "ACTIVE", "IN_SERVICE"}
    account["active_rental_count"] = sum(
        1 for r in db.rentals.values()
        if r["account_id"] == account_id and r["lifecycle_status"] in active
    )


def outstanding_balance(account_id):
    """Sum of amount_due_cents across ISSUED invoices for this account, plus
    settlement overflow billed but unpaid (tracked on the account)."""
    account = db.accounts.get(account_id)
    if account is None:
        return 0
    issued = sum(
        inv["amount_due_cents"] for inv in db.fleet_invoices.values()
        if inv["account_id"] == account_id and inv["status"] == "ISSUED"
    )
    return issued + account.get("_overflow_billed_unpaid_cents", 0)
