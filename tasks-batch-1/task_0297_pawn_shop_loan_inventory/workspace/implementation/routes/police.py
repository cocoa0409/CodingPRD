"""Police hold routes: place, release, execute, get, list (PRD §3.10)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from models import base_record, event_record, touch
from helpers import (
    get_body,
    as_str,
    as_enum,
    parse_pagination,
    paginate,
    sort_by_creation,
    serialize,
)
from response import success_object, success_array
from services.domain import loan_for_pawn_item

bp = Blueprint("police", __name__)

SUBJECT_KINDS = {"PAWN_ITEM", "INVENTORY_ITEM"}


def _drawer_for_shop(shop_id):
    for d in store.cash_drawers.values():
        if d["shop_id"] == shop_id:
            return d
    return None


def _append_tx(loan, kind, amount_cents, periods_in_charge):
    tx = event_record({
        "loan_id": loan["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "periods_in_charge": periods_in_charge,
    })
    store.finance_transactions[tx["id"]] = tx
    return tx


def _other_active_hold_on_pawn_item(pawn_item_id, exclude_hold_id):
    for h in store.police_holds.values():
        if (
            h["id"] != exclude_hold_id
            and h["status"] == "ACTIVE"
            and h["subject_kind"] == "PAWN_ITEM"
            and h["pawn_item_id"] == pawn_item_id
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Place a hold (PRD §3.10)
# ---------------------------------------------------------------------------
@bp.route("/pawn/police-holds", methods=["POST"])
def create_hold():
    require_auth(["LawEnforcement"])
    body = get_body()

    subject_kind = as_enum(body, "subject_kind", SUBJECT_KINDS)
    case_number = as_str(body, "case_number")
    pawn_item_id = as_str(body, "pawn_item_id", required=False)
    inventory_item_id = as_str(body, "inventory_item_id", required=False)

    # Well-formedness + existence depend on subject_kind.
    if subject_kind == "PAWN_ITEM":
        if not pawn_item_id:
            raise err("ERR_INVALID_REQUEST", "pawn_item_id is required for PAWN_ITEM.")
        if pawn_item_id not in store.pawn_items:
            raise err("ERR_NOT_FOUND", "Pawn item not found.")
        inventory_item_id = None
    else:  # INVENTORY_ITEM
        if not inventory_item_id:
            raise err("ERR_INVALID_REQUEST", "inventory_item_id is required for INVENTORY_ITEM.")
        if inventory_item_id not in store.inventory_items:
            raise err("ERR_NOT_FOUND", "Inventory item not found.")
        pawn_item_id = None

    hold = base_record({
        "subject_kind": subject_kind,
        "pawn_item_id": pawn_item_id,
        "inventory_item_id": inventory_item_id,
        "case_number": case_number,
        "status": "ACTIVE",
    })
    store.police_holds[hold["id"]] = hold

    # Side effects for a pawn-item subject (PRD §3.10).
    if subject_kind == "PAWN_ITEM":
        loan = loan_for_pawn_item(pawn_item_id, statuses=("ACTIVE", "IN_GRACE"))
        if loan is not None:
            loan["police_hold_flag"] = True
            loan["status"] = "POLICE_HELD"
            touch(loan)
        item = store.pawn_items.get(pawn_item_id)
        if item is not None:
            customer = store.customers.get(item["customer_id"])
            if customer is not None:
                customer["is_flagged"] = True
                touch(customer)

    return success_object(serialize(hold), 201)


@bp.route("/pawn/police-holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    require_auth(["LawEnforcement", "ShopManager"])
    hold = store.police_holds.get(hold_id)
    if hold is None:
        raise err("ERR_NOT_FOUND", "Police hold not found.")
    return success_object(serialize(hold))


@bp.route("/pawn/police-holds", methods=["GET"])
def list_holds():
    require_auth(["LawEnforcement", "ShopManager"])
    limit, offset = parse_pagination()
    pawn_item_id = request.args.get("pawn_item_id")
    inventory_item_id = request.args.get("inventory_item_id")
    items = list(store.police_holds.values())
    if pawn_item_id is not None:
        items = [h for h in items if h["pawn_item_id"] == pawn_item_id]
    if inventory_item_id is not None:
        items = [h for h in items if h["inventory_item_id"] == inventory_item_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(h) for h in window], limit, offset, total)


@bp.route("/pawn/police-holds/<hold_id>/release", methods=["POST"])
def release_hold(hold_id):
    require_auth(["LawEnforcement"])
    hold = store.police_holds.get(hold_id)
    if hold is None:
        raise err("ERR_NOT_FOUND", "Police hold not found.")

    # State (priority 5): must be ACTIVE.
    if hold["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Police hold is not ACTIVE.")

    hold["status"] = "RELEASED"
    touch(hold)

    # Clear the linked loan flag if no other ACTIVE hold names the collateral.
    if hold["subject_kind"] == "PAWN_ITEM":
        pawn_item_id = hold["pawn_item_id"]
        if not _other_active_hold_on_pawn_item(pawn_item_id, hold["id"]):
            loan = loan_for_pawn_item(pawn_item_id, statuses=("POLICE_HELD",))
            if loan is not None:
                loan["police_hold_flag"] = False
                loan["status"] = "ACTIVE"
                touch(loan)

    return success_object(serialize(hold))


@bp.route("/pawn/police-holds/<hold_id>/execute", methods=["POST"])
def execute_hold(hold_id):
    require_auth(["LawEnforcement"])
    hold = store.police_holds.get(hold_id)
    if hold is None:
        raise err("ERR_NOT_FOUND", "Police hold not found.")

    # State (priority 5): must be ACTIVE.
    if hold["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Police hold is not ACTIVE.")

    hold["status"] = "EXECUTED"
    touch(hold)

    if hold["subject_kind"] == "PAWN_ITEM":
        item = store.pawn_items.get(hold["pawn_item_id"])
        # If the surrendered pawn item is collateral on a live loan, void it.
        loan = loan_for_pawn_item(hold["pawn_item_id"], statuses=("ACTIVE", "POLICE_HELD"))
        if loan is not None:
            principal = loan["principal_cents"]
            _append_tx(loan, "VOID_REVERSAL", principal, 0)
            drawer = _drawer_for_shop(loan["shop_id"])
            if drawer is not None:
                drawer["balance_cents"] += principal
                touch(drawer)
            loan["status"] = "VOIDED"
            touch(loan)
        if item is not None:
            item["status"] = "RELEASED_TO_POLICE"
            touch(item)
    else:  # INVENTORY_ITEM
        inv = store.inventory_items.get(hold["inventory_item_id"])
        if inv is not None:
            inv["status"] = "RECALLED"
            touch(inv)
            pawn_item = store.pawn_items.get(inv["pawn_item_id"])
            if pawn_item is not None:
                pawn_item["status"] = "RELEASED_TO_POLICE"
                touch(pawn_item)

    return success_object(serialize(hold))
