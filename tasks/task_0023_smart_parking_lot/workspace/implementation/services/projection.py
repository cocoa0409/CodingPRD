"""Public projections of internal entities (strip private fields, add computed)."""
import db
from services.billing import compute_session_fee
from services.revenue import compute_card_balances


def lot_view(lot: dict) -> dict:
    return {k: v for k, v in lot.items() if not k.startswith("_")}


def zone_view(zone: dict) -> dict:
    return {k: v for k, v in zone.items() if not k.startswith("_")}


def space_view(space: dict) -> dict:
    return {k: v for k, v in space.items() if not k.startswith("_")}


def vehicle_view(vehicle: dict) -> dict:
    return {k: v for k, v in vehicle.items() if not k.startswith("_")}


def card_view(card: dict) -> dict:
    """Return card with provisional balance_cents and finalized_balance_cents recomputed."""
    out = {k: v for k, v in card.items() if not k.startswith("_")}
    prov, fin = compute_card_balances(card["id"])
    out["balance_cents"] = prov
    out["finalized_balance_cents"] = fin
    return out


def reservation_view(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def session_view(s: dict) -> dict:
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    if s.get("occupancy_status") == "ACTIVE":
        fee, _kind = compute_session_fee(s, variant="provisional")
        out["estimated_fee_cents"] = fee
    else:
        # EXITED — show pinned final and also reflect estimate equals final
        out["estimated_fee_cents"] = s.get("final_fee_cents")
    return out


def violation_view(v: dict) -> dict:
    out = {k: v_val for k, v_val in v.items() if not k.startswith("_")}
    fine = None
    for f in db.fines.values():
        if f.get("violation_id") == v["id"]:
            fine = f
            break
    if fine:
        out["fine"] = {k: vv for k, vv in fine.items() if not k.startswith("_")}
    return out


def fine_view(f: dict) -> dict:
    return {k: v for k, v in f.items() if not k.startswith("_")}


def payment_view(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def revenue_entry_view(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def audit_log_view(a: dict) -> dict:
    return {k: v for k, v in a.items() if not k.startswith("_")}


def invoice_view(i: dict) -> dict:
    return {k: v for k, v in i.items() if not k.startswith("_")}
