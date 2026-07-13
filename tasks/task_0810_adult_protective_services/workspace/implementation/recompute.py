"""Cross-entity derived-state recomputation."""
from store import store


def active_freezes_in_case(case_id):
    return [f for f in store.freezes.values()
            if f["case_id"] == case_id and f["status"] == "ACTIVE"]


def recompute_case_financials(case):
    """estimated / substantiated exposure + frozen_account_count (PRD 3.5).
    Does NOT touch version; caller decides whether the case was mutated."""
    active = active_freezes_in_case(case["id"])
    case["frozen_account_count"] = len(active)
    case["estimated_exposure_cents"] = sum(
        store.accounts[f["account_id"]]["total_balance_cents"] for f in active)
    case["substantiated_exposure_cents"] = sum(f["flagged_amount_cents"] for f in active)


def recompute_client_placement(client):
    """placement_status = PLACED while any owned ACTIVE placement, else NONE."""
    placed = any(p for p in store.placements.values()
                 if p["client_id"] == client["id"] and p["status"] == "ACTIVE")
    client["placement_status"] = "PLACED" if placed else "NONE"
