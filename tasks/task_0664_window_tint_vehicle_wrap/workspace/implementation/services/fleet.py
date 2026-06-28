"""Fleet credit recomputation (calc fleet_available_credit, scaffold §1.3)."""
import db

PROVISIONAL_INSTALL_STATES = {"SCHEDULED", "IN_PROGRESS", "CURING", "COMPLETED"}


def held_credit_cents(fleet_account_id):
    """PROVISIONAL held credit: sum of total_due_cents over WorkOrders linked to
    this account whose install_status is in {SCHEDULED, IN_PROGRESS, CURING,
    COMPLETED}.
    """
    total = 0
    for wo in db.work_orders.values():
        if wo.get("fleet_account_id") == fleet_account_id and wo["install_status"] in PROVISIONAL_INSTALL_STATES:
            total += wo["total_due_cents"]
    return total


def recompute_held_credit(fleet_account):
    """Recompute held_credit_cents on read (calc fleet_available_credit)."""
    fleet_account["held_credit_cents"] = held_credit_cents(fleet_account["id"])
    return fleet_account
