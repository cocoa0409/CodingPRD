from ..store import store
from ..repository import base_versioned, touch, now_iso


def open_workorder_for_return(ret, opened_by_id):
    wo = base_versioned()
    wo.update({
        "opened_by_role": "CUSTOMER_SERVICE",
        "opened_by_id": opened_by_id,
        "category": "OTHER",
        "related_order_id": ret["order_id"],
        "related_return_id": ret["id"],
        "status": "OPEN",
        "assigned_cs_user_id": None,
        "resolution_notes": None,
    })
    store.work_orders[wo["id"]] = wo
    return wo


def close_workorder_for_return_if_any(return_id):
    for wo in store.work_orders.values():
        if wo.get("related_return_id") == return_id and wo["status"] != "CLOSED":
            wo["status"] = "CLOSED"
            touch(wo)
