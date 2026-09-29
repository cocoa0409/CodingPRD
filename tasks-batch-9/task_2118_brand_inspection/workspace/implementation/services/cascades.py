"""Multi-hop cascades. Each row a cascade touches is mutated in its own right,
fan-outs are processed created_at ascending, and aggregates are recomputed from
their source rows rather than nudged (PRD 2.9)."""

from db import by_created_at, db, now, touch
from services import aggregates, constants as C
from services.calculations import recompute_priority_ranks, conflict_group_key


# ------------------------------------------------------------ theft cascade ---
def freeze_pending_filings(registration):
    """Hop 4: pending filings against an encumbered record are held."""
    frozen = by_created_at(
        [
            app
            for app in db.applications.values()
            if app["prior_registration_id"] == registration["id"]
            and app["status"] in ("SUBMITTED", "UNDER_EXAMINATION")
        ]
    )
    for application in frozen:
        application["status"] = "CONFLICT_HOLD"
        touch(application)
    return frozen


def release_held_filings(registration):
    """A cleared encumbrance releases every held filing into UNDER_EXAMINATION."""
    held = by_created_at(
        [
            app
            for app in db.applications.values()
            if app["prior_registration_id"] == registration["id"] and app["status"] == "CONFLICT_HOLD"
        ]
    )
    for application in held:
        application["status"] = "UNDER_EXAMINATION"
        touch(application)
    return held


def encumber_registration(registration):
    """Hop 3 + hop 4 of the theft cascade."""
    aggregates.recompute_encumbrance(registration)
    if registration["status"] in C.REGISTRATION_GROUP_STATUSES:
        registration["status"] = "ENCUMBERED"
    touch(registration)
    freeze_pending_filings(registration)


def mark_lots_unverifiable(registration):
    """Every lot read against the record that still stands at PRESENTED."""
    affected = by_created_at(
        [
            lot
            for lot in db.lots.values()
            if lot["brand_registration_id"] == registration["id"] and lot["lot_status"] == "PRESENTED"
        ]
    )
    for lot in affected:
        lot["match_status"] = "UNVERIFIABLE"
        touch(lot)
    return affected


def unschedule_orders_for_lots(lots):
    """Hop 3 of the conflict cascade: field work on a revoked mark is aborted."""
    order_ids = []
    for lot in lots:
        if lot["inspection_order_id"] not in order_ids:
            order_ids.append(lot["inspection_order_id"])
    orders = by_created_at(
        [
            db.orders[order_id]
            for order_id in order_ids
            if order_id in db.orders
            and db.orders[order_id]["schedule_status"] in C.OCCUPYING_SCHEDULE_STATUSES
        ]
    )
    for order in orders:
        inspector = db.inspectors.get(order["inspector_id"])
        order["schedule_status"] = "REQUESTED"
        order["inspector_id"] = None
        order["scheduled_start_at"] = None
        order["scheduled_end_at"] = None
        touch(order)
        if inspector is not None:
            aggregates.recompute_inspector_assignments(inspector, bump=True)
    return orders


def revoke_registration_and_cascade(registration, unschedule=False):
    registration["status"] = "REVOKED"
    touch(registration)
    lots = mark_lots_unverifiable(registration)
    if unschedule:
        unschedule_orders_for_lots(lots)
    return lots


def recompute_order_hold(order):
    lot_ids = {lot["id"] for lot in db.lots.values() if lot["inspection_order_id"] == order["id"]}
    held = any(
        inv["animal_lot_id"] in lot_ids and inv["status"] in C.OPEN_INVESTIGATION_STATUSES
        for inv in db.investigations.values()
    )
    if order["hold_flag"] != held:
        order["hold_flag"] = held
        touch(order)
    return held


def set_order_hold(order, value):
    if order["hold_flag"] != value:
        order["hold_flag"] = value
        touch(order)


# ------------------------------------------------------- renewal supersession --
def reject_pending_filings(registration, reason, renewal_only, exclude_id=None):
    affected = by_created_at(
        [
            app
            for app in db.applications.values()
            if app["prior_registration_id"] == registration["id"]
            and app["status"] in C.PENDING_APPLICATION_STATUSES
            and app["id"] != exclude_id
            and (not renewal_only or app["application_type"] == "RENEWAL")
        ]
    )
    for application in affected:
        application["status"] = "REJECTED"
        application["rejection_reason"] = reason
        touch(application)
    return affected


# ----------------------------------------------------------- recording helper --
def rerank_conflict_group(registration, created_id=None):
    recompute_priority_ranks(conflict_group_key(registration), created_id=created_id)
