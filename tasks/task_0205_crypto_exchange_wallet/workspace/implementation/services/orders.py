"""Order cancellation / reserve release helpers."""
from db import db
from numeric import D
from services.common import touch, credit_available, debit_reserved


def release_reserve(order):
    """Release the order's reserved_remaining back to available on its reserve asset."""
    remaining = D(order["reserved_remaining"])
    if remaining <= 0:
        order["reserved_remaining"] = D(0)
        return
    reserve_asset = order["base_asset"] if order["side"] == "SELL" else order["quote_asset"]
    bal = db.get_or_create_balance(order["account_id"], reserve_asset)
    debit_reserved(bal, remaining)
    credit_available(bal, remaining)
    order["reserved_remaining"] = D(0)


def cancel_order_internal(order):
    """Cancel an OPEN/PARTIALLY_FILLED order, releasing its reserve. Used by
    explicit cancel, IOC remainder auto-cancel, and the freeze cascade."""
    release_reserve(order)
    order["lifecycle_status"] = "CANCELLED"
    touch(order)
