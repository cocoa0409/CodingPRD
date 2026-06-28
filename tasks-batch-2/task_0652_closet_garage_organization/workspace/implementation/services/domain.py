"""Cross-cutting domain helpers shared by routes.

- region derivation from zip code
- project balance reconciliation (with version bump)
- quote expiry sweep (read-triggered)
- ownership checks
"""
from datetime import timedelta

import db
from errors import err
from services import clock
from services import calc


def derive_region(zip_code: str) -> str:
    first = zip_code[0]
    if first in "012":
        return "NORTH"
    if first in "34":
        return "SOUTH"
    if first in "56":
        return "EAST"
    return "WEST"  # 7,8,9


def recompute_balance(project):
    """Recompute project.balance_due_cents and version-bump the project.

    accepted_total - sum(CAPTURED deposit amounts) - financed, floored at 0.
    financed = funded financing application's approved_amount_cents, else 0.
    This recomputation is itself a mutation (PRD 2.4).
    """
    accepted_total = 0
    aq_id = project.get("accepted_quote_id")
    if aq_id and aq_id in db.quotes:
        accepted_total = db.quotes[aq_id]["total_cents"]

    deposits_applied = 0
    for dep in db.deposits.values():
        if dep["project_id"] == project["id"] and dep["status"] == "CAPTURED":
            deposits_applied += dep["amount_cents"]

    financed = 0
    fa_id = project.get("financing_application_id")
    if fa_id and fa_id in db.financing_applications:
        fa = db.financing_applications[fa_id]
        if fa["status"] == "FUNDED":
            financed = fa["approved_amount_cents"]

    project["balance_due_cents"] = calc.balance_due_cents(
        accepted_total, deposits_applied, financed)
    db.touch(project)


def sweep_quote(quote):
    """Read-triggered expiry: ISSUED quote past expires_at -> EXPIRED.

    A quote sitting exactly at expires_at is NOT yet expired; only strictly
    past it triggers the sweep.
    """
    if quote["status"] != "ISSUED":
        return
    exp = quote.get("expires_at")
    if exp is None:
        return
    if clock.now() > exp:
        quote["status"] = "EXPIRED"
        db.touch(quote)


def sweep_project_quotes(project_id):
    for q in db.quotes.values():
        if q["project_id"] == project_id:
            sweep_quote(q)


def check_project_owner(project, user_id, role):
    """For Customer role, X-User-ID must equal project.customer_id."""
    if role == "Customer" and project.get("customer_id") != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER")
