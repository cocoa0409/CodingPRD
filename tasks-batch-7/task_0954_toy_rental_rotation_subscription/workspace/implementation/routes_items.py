"""Box item routes: read, fee list, swap chain, swap, buyout, report-lost."""
from flask import Blueprint

from domain import (
    MIN_NET_CHARGE_CENTS,
    age_gate_passes,
    base_fields,
    buyout_price_cents,
    by_seq,
    create_fee,
    ledger_append,
    member_of_box,
    release_reserved_copy,
    sanitization_valid,
    touch,
    wallet_of,
)
from envelope import ok_list, ok_object
from errors import domain as derr, invalid_state, not_found
from serializers import serialize_box_item, serialize_fee
from store import DB
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    paginate,
    parse_fields,
    require_ownership,
)

bp = Blueprint("box_items", __name__)


def _get_item(iid):
    it = DB.box_items.get(iid)
    if it is None:
        raise not_found("ERR_BOX_ITEM_NOT_FOUND", "BoxItem id does not exist.")
    return it


def _owner_of(item):
    box = DB.boxes.get(item["rotation_box_id"])
    return member_of_box(box) if box else None


def _check_member_active(owner):
    m = DB.members.get(owner)
    if m is not None and m["status"] == "SUSPENDED":
        raise derr("ERR_MEMBER_SUSPENDED", 409, "Member is SUSPENDED.")


@bp.get("/toy-rental/box-items/<iid>")
def get_box_item(iid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager"})
    it = _get_item(iid)
    require_ownership(role, uid, _owner_of(it))
    return ok_object(serialize_box_item(it))


@bp.get("/toy-rental/box-items/<iid>/fees")
def list_item_fees(iid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService"})
    it = _get_item(iid)
    require_ownership(role, uid, _owner_of(it))
    fees = by_seq([f for f in DB.fees.values() if f["box_item_id"] == iid])
    page, meta = paginate(fees)
    return ok_list([serialize_fee(f) for f in page], meta)


@bp.get("/toy-rental/box-items/<iid>/swaps")
def list_item_swaps(iid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager"})
    it = _get_item(iid)
    require_ownership(role, uid, _owner_of(it))
    children = by_seq([
        x for x in DB.box_items.values() if x["swapped_from_item_id"] == iid
    ])
    page, meta = paginate(children)
    return ok_list([serialize_box_item(x) for x in page], meta)


@bp.post("/toy-rental/box-items/<iid>/swap")
def swap_item(iid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    it = _get_item(iid)
    data = body()
    shape = parse_fields(data, [F("new_toy_copy_id", True, "str")])
    new_copy_id = shape.values.get("new_toy_copy_id")
    new_copy = DB.copies.get(new_copy_id) if isinstance(new_copy_id, str) else None
    if isinstance(new_copy_id, str) and new_copy is None:
        raise not_found("ERR_COPY_NOT_FOUND", "ToyCopy id does not exist.")
    owner = _owner_of(it)
    require_ownership(role, uid, owner)
    _check_member_active(owner)
    box = DB.boxes.get(it["rotation_box_id"])
    if it["loan_status"] != "PENDING_RETURN" or box is None or box["status"] != "PLANNED":
        raise invalid_state("Item is not PENDING_RETURN in a PLANNED box.")
    if new_copy is not None:
        available = new_copy["status"] == "AVAILABLE"
        self_reserved = (
            new_copy["status"] == "RESERVED"
            and new_copy["reserved_member_id"] == owner
        )
        if not (available or self_reserved):
            raise derr("ERR_COPY_NOT_AVAILABLE", 409,
                       "Copy is not AVAILABLE or RESERVED to this member.")
        cat = DB.catalog_items.get(new_copy["catalog_item_id"])
        if cat is not None and not age_gate_passes(owner, cat):
            raise derr("ERR_AGE_INCOMPATIBLE", 422,
                       "No child of the member passes the age gate for this toy.")
        if not sanitization_valid(new_copy):
            raise derr("ERR_NEEDS_RESANITIZATION", 422,
                       "Copy sanitization is stale.")
    if box["swap_count"] >= box["plan_snapshot"]["swap_allowance_per_cycle"]:
        raise derr("ERR_SWAP_ALLOWANCE_EXCEEDED", 422,
                   "This box's swap allowance is exhausted.")
    finalize_shape(shape)
    # Retire the old slot, create the replacement, reserve the new copy.
    it["loan_status"] = "SWAPPED_OUT"
    touch(it)
    new_item = base_fields()
    new_item.update({
        "rotation_box_id": box["id"],
        "toy_copy_id": new_copy_id,
        "swapped_from_item_id": it["id"],
        "loan_status": "PENDING_RETURN",
        "resolution_status": "NONE",
        "condition_returned": None,
        "damage_severity": None,
        "missing_piece_count": 0,
        "buyout_price_cents": None,
        "wallet_applied_cents": None,
        "net_charge_cents": None,
    })
    DB.box_items[new_item["id"]] = new_item
    if new_copy["status"] != "RESERVED" or new_copy["reserved_member_id"] != owner:
        new_copy["status"] = "RESERVED"
        new_copy["reserved_member_id"] = owner
    touch(new_copy)
    box["swap_count"] += 1
    touch(box)
    # Release the old copy and run the targeted sweep (transitive cascade).
    old_copy = DB.copies.get(it["toy_copy_id"])
    if old_copy is not None and old_copy["status"] == "RESERVED":
        release_reserved_copy(old_copy)
    return ok_object(serialize_box_item(new_item), status=201)


@bp.post("/toy-rental/box-items/<iid>/buyout")
def buyout_item(iid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    it = _get_item(iid)
    owner = _owner_of(it)
    require_ownership(role, uid, owner)
    _check_member_active(owner)
    box = DB.boxes.get(it["rotation_box_id"])
    if (
        it["loan_status"] != "PENDING_RETURN"
        or box is None
        or box["status"] not in ("DELIVERED", "RETURNING")
    ):
        raise invalid_state("Item is not PENDING_RETURN in a DELIVERED or RETURNING box.")
    data = body()
    shape = parse_fields(data, [])
    finalize_shape(shape)
    copy = DB.copies.get(it["toy_copy_id"])
    cat = DB.catalog_items.get(copy["catalog_item_id"]) if copy else None
    price = buyout_price_cents(box, copy, cat)
    wallet0 = wallet_of(owner)
    wallet_applied = min(max(wallet0, 0), price - MIN_NET_CHARGE_CENTS)
    net_charge = price - wallet_applied
    it["buyout_price_cents"] = price
    it["wallet_applied_cents"] = wallet_applied
    it["net_charge_cents"] = net_charge
    it["loan_status"] = "KEPT_BUYOUT"
    it["resolution_status"] = "RESOLVED"
    touch(it)
    if copy is not None:
        copy["status"] = "SOLD"
        touch(copy)
    if wallet_applied > 0:
        ledger_append(owner, -wallet_applied, "BUYOUT_CREDIT_APPLIED")
    return ok_object(serialize_box_item(it))


@bp.post("/toy-rental/box-items/<iid>/report-lost")
def report_lost(iid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    it = _get_item(iid)
    owner = _owner_of(it)
    require_ownership(role, uid, owner)
    _check_member_active(owner)
    box = DB.boxes.get(it["rotation_box_id"])
    if (
        it["loan_status"] != "PENDING_RETURN"
        or box is None
        or box["status"] not in ("DELIVERED", "RETURNING")
    ):
        raise invalid_state("Item is not PENDING_RETURN in a DELIVERED or RETURNING box.")
    data = body()
    shape = parse_fields(data, [F("note", False, "str")])
    finalize_shape(shape)
    copy = DB.copies.get(it["toy_copy_id"])
    cat = DB.catalog_items.get(copy["catalog_item_id"]) if copy else None
    sub = DB.subscriptions.get(box["subscription_id"])
    it["loan_status"] = "LOST_REPORTED"
    it["resolution_status"] = "FEE_ASSESSED"
    touch(it)
    if copy is not None:
        copy["status"] = "LOST"
        touch(copy)
    if cat is not None and sub is not None:
        create_fee(sub["id"], it["id"], box["id"], "LOSS", cat["replacement_value_cents"])
    return ok_object(serialize_box_item(it))
