"""Budget computations on a project.

provisional_committed_cents:
  sum over Contracts on this project where contract_status IN {SIGNED, ACCEPTED}
    AND (no Settlement exists for Contract OR Settlement.status != FINALIZED)
  of pinned_amount_cents + sum(approved ChangeOrder.delta_amount_cents)

finalized_settled_cents:
  sum of Settlement.final_amount_cents for FINALIZED settlements on this project

budget_balance_cents = total_budget_cents - provisional_committed_cents - finalized_settled_cents
"""

import db


def settlement_for_contract(contract_id):
    for s in db.settlements.values():
        if s["contract_id"] == contract_id:
            return s
    return None


def approved_deltas_sum(contract_id) -> int:
    return sum(
        co["delta_amount_cents"]
        for co in db.change_orders.values()
        if co["contract_id"] == contract_id and co["status"] == "APPROVED"
    )


def recompute_project_ledger(project: dict) -> None:
    project_id = project["id"]
    provisional = 0
    finalized = 0
    for c in db.contracts.values():
        if c["project_id"] != project_id:
            continue
        if c["contract_status"] not in ("SIGNED", "ACCEPTED"):
            continue
        s = settlement_for_contract(c["id"])
        if s is not None and s["status"] == "FINALIZED":
            continue
        provisional += int(c["pinned_amount_cents"]) + approved_deltas_sum(c["id"])
    for s in db.settlements.values():
        if s["status"] != "FINALIZED":
            continue
        c = db.contracts.get(s["contract_id"])
        if not c:
            continue
        if c["project_id"] != project_id:
            continue
        finalized += int(s["final_amount_cents"])
    project["provisional_committed_cents"] = provisional
    project["finalized_settled_cents"] = finalized
    project["budget_balance_cents"] = (
        int(project["total_budget_cents"]) - provisional - finalized
    )
    db.bump(project)


def soft_warning_threshold(project: dict) -> int:
    """Soft warning threshold for OVERSPEND_WARNING_RAISED — 90% of total."""
    return int(project["total_budget_cents"]) * 90 // 100
