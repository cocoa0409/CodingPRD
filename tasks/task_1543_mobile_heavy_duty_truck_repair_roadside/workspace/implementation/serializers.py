"""Entity -> JSON serializers. Derived fields are recomputed at read time."""
from db import store
from util import fmt_dt, month_window

OOS_BLOCKING_STATES = {"OPEN", "REPAIR_SCHEDULED", "CORRECTED",
                       "VERIFICATION_FAILED", "ESCALATED"}


def fleet_mtd(fleet_id):
    """Month-to-date spend: ISSUED invoices + spend adjustments in the logical
    clock's current calendar month [month start inclusive, next month exclusive)."""
    start, end = month_window(store.clock)
    total = 0
    for inv in store.invoices.values():
        if (inv["fleet_account_id"] == fleet_id
                and inv["issue_status"] == "ISSUED"
                and inv["issued_at"] is not None
                and start <= inv["issued_at"] < end):
            total += inv["total_cents"]
    for adj in store.spend_adjustments.values():
        if (adj["fleet_account_id"] == fleet_id
                and start <= adj["posted_at"] < end):
            total += adj["amount_cents"]
    return total


def tier_for_mtd(mtd):
    if mtd >= 500000:
        return "PLATINUM"
    if mtd >= 200000:
        return "GOLD"
    return "STANDARD"


def vehicle_roadworthiness(vehicle_id):
    for d in store.inspection_defects.values():
        if (d["vehicle_id"] == vehicle_id and d["severity"] == "OOS"
                and d["status"] in OOS_BLOCKING_STATES):
            return "OUT_OF_SERVICE"
    return "ROADWORTHY"


def restock_pending(item_id):
    for r in store.restock_requests.values():
        if r["van_stock_item_id"] == item_id and r["status"] in ("PENDING", "APPROVED"):
            return True
    return False


_DT_FIELDS = {
    "received_at", "submitted_at", "issued_at", "due_at", "completed_at",
    "departed_at", "arrived_at", "posted_at", "verified_at", "decided_at",
    "hooked_at", "delivered_at", "effective_from", "effective_to",
    "discovered_at", "correction_deadline_at", "oem_warranty_expires_at",
    "window_start_at", "window_end_at", "pickup_window_start_at",
    "pickup_window_end_at",
}


def _base(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if k in _DT_FIELDS:
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    out["created_at"] = rec.get("_created")
    out["updated_at"] = rec.get("_updated")
    return out


def serialize_fleet(rec):
    out = _base(rec)
    mtd = fleet_mtd(rec["id"])
    out["month_to_date_spend_cents"] = mtd
    out["effective_discount_tier"] = tier_for_mtd(mtd)
    return out


def serialize_vehicle(rec):
    out = _base(rec)
    out["roadworthiness"] = vehicle_roadworthiness(rec["id"])
    return out


def serialize_van_item(rec):
    out = _base(rec)
    out["restock_pending"] = restock_pending(rec["id"])
    return out


def serialize_invoice(rec):
    out = _base(rec)
    due = rec.get("due_at")
    out["is_overdue"] = bool(
        due is not None and store.clock > due and rec["outstanding_cents"] > 0)
    return out


def serialize_call_event(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        out[k] = v
    out["created_at"] = rec.get("_created")
    return out


SERIALIZERS = {
    "fleet": serialize_fleet,
    "vehicle": serialize_vehicle,
    "van_item": serialize_van_item,
    "invoice": serialize_invoice,
    "call_event": serialize_call_event,
}


def serialize(kind, rec):
    fn = SERIALIZERS.get(kind)
    if fn:
        return fn(rec)
    return _base(rec)
