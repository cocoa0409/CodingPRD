from ..store import store
from ..repository import touch


def cancel_placed_orders_for_restaurant(rid: str) -> None:
    for order in list(store.orders.values()):
        if order["restaurant_id"] == rid and order["status"] == "PLACED":
            order["status"] = "CANCELLED"
            if order["payment_status"] in ("UNPAID", "AUTHORIZED"):
                order["payment_status"] = "VOIDED"
            touch(order)
