"""Loan-level cascade helpers shared by payment/repossession flows (PRD 3.7, 3.9)."""
import db
import lookups
from errors import err


def release_lien_cascade(loan):
    """TitleLien FILED -> RELEASED, which sets Vehicle.lien_state = CLEAR (depth-2).

    Only a lien currently in FILED is released; a PENDING lien is left as-is.
    The vehicle is mutated when the lien releases.
    """
    lien = lookups.title_lien_for_loan(loan["id"])
    if lien is not None and lien["status"] == "FILED":
        lien["status"] = "RELEASED"
        db.touch(lien)
        vehicle = db.vehicles.get(loan["vehicle_id"])
        if vehicle is not None:
            vehicle["lien_state"] = "CLEAR"
            db.touch(vehicle)


def cancel_active_repo_cascade(loan):
    """Active RepossessionOrder (ORDERED/ASSIGNED/RECOVERED) -> CANCELLED."""
    order = lookups.active_repo_for_loan(loan["id"])
    if order is not None:
        order["status"] = "CANCELLED"
        db.touch(order)
        return order
    return None


def maybe_payoff(loan):
    """OUTSTANDING -> PAID_OFF when all three balances reach zero (PRD 3.7).

    Cascades: lien FILED -> RELEASED -> vehicle CLEAR; remaining SCHEDULED
    installments -> WAIVED. Bumps the loan version. Returns True if paid off.
    Caller is responsible for bumping the loan version on the primary payment
    transition separately; this routine bumps the loan version for the payoff
    transition itself.
    """
    if loan["payoff_status"] != "OUTSTANDING":
        return False
    if not (loan["principal_balance_cents"] == 0
            and loan["accrued_interest_cents"] == 0
            and loan["fees_balance_cents"] == 0):
        return False
    loan["payoff_status"] = "PAID_OFF"
    release_lien_cascade(loan)
    for inst in lookups.installments_for_loan(loan["id"]):
        if inst["status"] == "SCHEDULED":
            inst["status"] = "WAIVED"
            db.touch(inst)
    db.touch(loan)
    return True
