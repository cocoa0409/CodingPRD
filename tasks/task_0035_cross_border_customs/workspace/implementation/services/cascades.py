"""Cross-entity state cascades (PRD §2.7 and §3.7-3.8)."""

from clock import now, to_iso
from db import DB
from services.common import touch, emit_audit


def cascade_order_on_declaration_status(order: dict, declaration: dict, prior_status: str, new_status: str):
    """When a declaration's status changes, cascade the parent order's status."""
    advanced = False
    before = {"status": order["status"]}

    # PENDING_DECLARATION -> DECLARED when declaration enters APPROVED or CONDITIONALLY_RELEASED
    if new_status in ("APPROVED", "CONDITIONALLY_RELEASED") and order["status"] == "PENDING_DECLARATION":
        order["status"] = "DECLARED"
        touch(order)
        advanced = True
        emit_audit("DECLARATION", declaration["id"], "EXTERNAL_SYNC",
                   before_value={"order_status": before["status"]},
                   after_value={"order_status": "DECLARED",
                                "external_system": "ERP_ORDER_UPDATE"})

    # DECLARED -> RELEASED when declaration enters RELEASED
    if new_status == "RELEASED" and order["status"] == "DECLARED":
        order["status"] = "RELEASED"
        touch(order)
        advanced = True
        # pickup pin
        declaration["pickup_coordinated_at"] = to_iso(now())
        touch(declaration)
        emit_audit("DECLARATION", declaration["id"], "EXTERNAL_SYNC",
                   before_value={"order_status": "DECLARED"},
                   after_value={"order_status": "RELEASED",
                                "external_system": "LOGISTICS_PICKUP_ACK"})

    # Reverse cascades:
    # Declaration RELEASED -> APPROVED reverts order RELEASED -> DECLARED
    if prior_status == "RELEASED" and new_status == "APPROVED" and order["status"] == "RELEASED":
        order["status"] = "DECLARED"
        touch(order)
        advanced = True

    return advanced
