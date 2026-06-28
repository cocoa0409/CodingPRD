"""Public serialization of entities.

Strips internal-only keys (those prefixed with '_') and surfaces computed
fields that are reconciled on every relevant mutation.
"""
from db import db


def _public(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def plain(obj):
    return _public(obj)


# --- Computed-field reconciliation (PRD §2.5) ---

def property_view(prop):
    out = _public(prop)
    zones = [z for z in db.treatment_zones.values() if z["property_id"] == prop["id"]]
    out["zone_count"] = len(zones)
    out["total_treatable_sqft"] = sum(
        z["area_sqft"] for z in zones if z["status"] == "ACTIVE"
    )
    return out


def subscription_view(sub):
    out = _public(sub)
    visits = [v for v in db.visits.values() if v["subscription_id"] == sub["id"]]
    out["visits_completed_count"] = sum(1 for v in visits if v["status"] == "COMPLETED")
    out["season_balance_cents"] = _season_balance(sub)
    return out


def _season_balance(sub):
    """PRD §3.6 'Season balance'.

    PER_VISIT: sum of amount_cents across invoices whose status is ISSUED or PAID.
    SEASONAL: the single seasonal invoice's amount_cents once issued, else 0.
    """
    invs = [i for i in db.invoices.values() if i["subscription_id"] == sub["id"]]
    if sub["billing_mode"] == "PER_VISIT":
        return sum(i["amount_cents"] for i in invs if i["status"] in ("ISSUED", "PAID"))
    # SEASONAL
    for i in invs:
        if i["invoice_type"] == "SEASONAL" and i["status"] in ("ISSUED", "PAID"):
            return i["amount_cents"]
    return 0


def crew_route_view(route, include_load_factor=False):
    out = _public(route)
    assigned = _assigned_visit_count(route)
    crew = db.crews.get(route["crew_id"])
    capacity = crew["daily_capacity"] if crew else 0
    out["assigned_visit_count"] = assigned
    out["remaining_capacity"] = capacity - assigned
    if include_load_factor:
        out["route_load_factor"] = _load_factor(assigned, capacity)
    return out


def _assigned_visit_count(route):
    return sum(
        1 for v in db.visits.values()
        if v["crew_route_id"] == route["id"] and v["status"] in ("DISPATCHED", "COMPLETED")
    )


def _load_factor(assigned, capacity):
    from decimal import Decimal, ROUND_HALF_UP
    if capacity == 0:
        return 0.0
    q = (Decimal(assigned) / Decimal(capacity)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(q)
