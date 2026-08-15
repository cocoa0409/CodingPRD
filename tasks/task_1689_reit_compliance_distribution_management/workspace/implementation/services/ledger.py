"""Cross-entity ledger sync helpers."""

from db import db
from services.calculations import calc_ep_balance
from services.common import touch


def recompute_quarter_income_total(quarter_id):
    quarter = db.quarters.get(quarter_id)
    if quarter is None:
        return
    total = sum(
        i["amount_cents"] for i in db.income_items.values()
        if i["quarter_id"] == quarter_id
    )
    quarter["gross_income_total_cents"] = total
    quarter["updated_at"] = __import__("services.common", fromlist=["now_iso"]).now_iso()


def sync_requirement_amounts(requirement):
    """Recompute distributed_amount_cents and deficiency_cents on a requirement
    from sibling declarations in DECLARED/PAID."""
    distributed = sum(
        d["amount_cents"]
        for d in db.dividend_declarations.values()
        if d["reit_id"] == requirement["reit_id"]
        and d["taxable_year"] == requirement["taxable_year"]
        and d["status"] in ("DECLARED", "PAID")
    )
    requirement["distributed_amount_cents"] = distributed
    requirement["deficiency_cents"] = max(
        0, requirement["required_amount_cents"] - distributed
    )
    return requirement["deficiency_cents"]


def refresh_ep_balance(reit):
    """Re-run the chronological replay and persist current_ep_balance_cents."""
    reit["current_ep_balance_cents"] = calc_ep_balance(reit["id"])
