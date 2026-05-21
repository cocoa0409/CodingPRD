"""WorkOrder lifecycle and helpers."""

import state


_LEGAL_CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM", "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
}

_LEGAL_OPENER_ROLES = {"CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE"}


def new_work_order(opened_by_role, opened_by_id, category,
                   related_order_id=None, related_return_id=None,
                   assigned_cs_user_id=None, status="OPEN"):
    now = state.now()
    wid = state.gen_id()
    rec = {
        "id": wid,
        "opened_by_role": opened_by_role,
        "opened_by_id": opened_by_id,
        "category": category,
        "related_order_id": related_order_id,
        "related_return_id": related_return_id,
        "assigned_cs_user_id": assigned_cs_user_id,
        "status": status,
        "resolution_notes": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    state.STORE.work_orders[wid] = rec
    return rec


def bump(rec):
    rec["updated_at"] = state.now()
    rec["version"] = rec["version"] + 1
