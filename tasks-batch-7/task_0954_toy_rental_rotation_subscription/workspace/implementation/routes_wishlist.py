"""Wishlist entry hold routes: cancel and accept-hold."""
from flask import Blueprint

from domain import (
    age_gate_passes,
    base_fields,
    cancel_wishlist_entry,
    sanitization_valid,
    touch,
)
from envelope import ok_object
from errors import domain as derr, invalid_state, not_found
from serializers import serialize_wishlist_entry
from store import DB, clock
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    parse_fields,
    require_ownership,
)

bp = Blueprint("wishlist", __name__)


def _get_entry(eid):
    e = DB.wishlist_entries.get(eid)
    if e is None:
        raise not_found("ERR_WISHLIST_ENTRY_NOT_FOUND", "WishlistEntry id does not exist.")
    return e


@bp.post("/toy-rental/wishlist-entries/<eid>/cancel")
def cancel_entry(eid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = _get_entry(eid)
    require_ownership(role, uid, e["member_id"])
    if e["status"] not in ("WAITING", "HELD"):
        raise invalid_state("Wishlist entry is not WAITING or HELD.")
    data = body()
    shape = parse_fields(data, [])
    finalize_shape(shape)
    cancel_wishlist_entry(e, released=None)
    return ok_object(serialize_wishlist_entry(e))


@bp.post("/toy-rental/wishlist-entries/<eid>/accept-hold")
def accept_hold(eid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    e = _get_entry(eid)
    data = body()
    shape = parse_fields(data, [F("rotation_box_id", True, "str")])
    box_id = shape.values.get("rotation_box_id")
    box = DB.boxes.get(box_id) if isinstance(box_id, str) else None
    if isinstance(box_id, str) and box is None:
        raise not_found("ERR_BOX_NOT_FOUND", "RotationBox id does not exist.")
    require_ownership(role, uid, e["member_id"])
    m = DB.members.get(e["member_id"])
    if m is not None and m["status"] == "SUSPENDED":
        raise derr("ERR_MEMBER_SUSPENDED", 409, "Member is SUSPENDED.")
    if e["status"] != "HELD":
        raise invalid_state("Wishlist entry is not HELD.")
    copy = DB.copies.get(e["held_copy_id"]) if e["held_copy_id"] else None
    # Business-safety gates (priority 6): age gate, then sanitization.
    cat = DB.catalog_items.get(copy["catalog_item_id"]) if copy else None
    if cat is not None and not age_gate_passes(e["member_id"], cat):
        raise derr("ERR_AGE_INCOMPATIBLE", 422,
                   "No child of the member passes the age gate for this toy.")
    if copy is not None and not sanitization_valid(copy):
        raise derr("ERR_NEEDS_RESANITIZATION", 422,
                   "Copy sanitization is stale.")
    # Hold expiry (priority 7): strictly before hold_expires_at.
    if e["hold_expires_at"] is not None and clock() >= e["hold_expires_at"]:
        raise derr("ERR_HOLD_EXPIRED", 409, "The hold has expired.")
    # Slot gate (priority 8): PLANNED box of the member's ACTIVE subscription
    # with a free slot.
    slot_fail = False
    if box is None or box["status"] != "PLANNED":
        slot_fail = True
    else:
        sub = DB.subscriptions.get(box["subscription_id"])
        if (
            sub is None
            or sub["member_id"] != e["member_id"]
            or sub["status"] != "ACTIVE"
        ):
            slot_fail = True
    if not slot_fail:
        slotted = sum(
            1 for it in DB.box_items.values()
            if it["rotation_box_id"] == box["id"]
            and it["loan_status"] == "PENDING_RETURN"
        )
        if slotted >= box["plan_snapshot"]["toys_per_box"]:
            slot_fail = True
    if slot_fail:
        raise derr("ERR_SLOT_CAPACITY_EXCEEDED", 422,
                   "Target box is not a PLANNED box of the member's ACTIVE "
                   "subscription with a free slot.")
    if copy is None or copy["status"] != "RESERVED" or copy["reserved_member_id"] != e["member_id"]:
        raise derr("ERR_COPY_NOT_AVAILABLE", 409,
                   "Held copy is no longer RESERVED to this member.")
    finalize_shape(shape)
    it = base_fields()
    it.update({
        "rotation_box_id": box["id"],
        "toy_copy_id": copy["id"],
        "swapped_from_item_id": None,
        "loan_status": "PENDING_RETURN",
        "resolution_status": "NONE",
        "condition_returned": None,
        "damage_severity": None,
        "missing_piece_count": 0,
        "buyout_price_cents": None,
        "wallet_applied_cents": None,
        "net_charge_cents": None,
    })
    DB.box_items[it["id"]] = it
    e["status"] = "FULFILLED"
    e["held_copy_id"] = None
    touch(e)
    touch(box)
    return ok_object(serialize_wishlist_entry(e))
