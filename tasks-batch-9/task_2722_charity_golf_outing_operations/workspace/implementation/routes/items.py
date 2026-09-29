"""FundraisingItem endpoints: auctions, raffles and donations (PRD 3.7)."""

from flask import Blueprint

import derive
import enums
import serial
import store
import validate
from auth import CHARITY_TREASURER, SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR, auth
from envelope import created, ok, paginate
from errors import fail
from lookup import item as get_item
from lookup import outing as get_outing
from lookup import registration as get_registration
from store import touch

bp = Blueprint("items", __name__)

READ_ROLES = (CHARITY_TREASURER, TOURNAMENT_DIRECTOR)


@bp.post("/outing-ops/fundraising-items")
def create_item():
    auth((CHARITY_TREASURER,))
    body = validate.body()
    validate.only_fields(body, ("outing_id", "item_type", "description",
                                "fmv_cents", "ask_cents"))
    outing_id = validate.req_ref(body, "outing_id")
    item_type = validate.req_enum(body, "item_type", enums.ITEM_TYPE)
    description = validate.req_str(body, "description")
    fmv = validate.opt_money(body, "fmv_cents", 0)
    ask = validate.opt_money(body, "ask_cents", 0)
    get_outing(outing_id)
    row = store.new_row("FundraisingItem", {
        "outing_id": outing_id,
        "item_type": item_type,
        "description": description,
        "fmv_cents": fmv,
        "ask_cents": ask,
        "buyer_registration_id": None,
        "bid_cents": 0,
        "collected_cents": 0,
        "status": "LISTED",
        "recorded_by_user_id": None,
        "sold_at": None,
        "void_count": 0,
    })
    return created(serial.dump(row))


@bp.get("/outing-ops/fundraising-items/<row_id>")
def read_item(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_item(row_id)))


@bp.get("/outing-ops/fundraising-items")
def list_items():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    buyer = validate.q_str("buyer_registration_id")
    item_type = validate.q_enum("item_type", enums.ITEM_TYPE)
    status = validate.q_enum("status", enums.ITEM_STATUS)
    rows = store.sorted_rows(store.fundraising_items.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    if buyer is not None:
        rows = [r for r in rows if r["buyer_registration_id"] == buyer]
    if item_type is not None:
        rows = [r for r in rows if r["item_type"] == item_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.dump)


@bp.post("/outing-ops/fundraising-items/<row_id>/sale")
def record_sale(row_id):
    user_id, _role = auth((CHARITY_TREASURER, SPONSORSHIP_MANAGER))
    body = validate.body()
    validate.only_fields(body, ("buyer_registration_id", "bid_cents"))
    buyer_id = validate.req_ref(body, "buyer_registration_id")
    bid = validate.req_money(body, "bid_cents")
    item = get_item(row_id)
    reg = get_registration(buyer_id)
    if reg["outing_id"] != item["outing_id"]:
        fail("ERR_CROSS_OUTING_REFERENCE", "The buyer belongs to another outing.")
    if item["status"] != "LISTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A sale is only recorded against a LISTED item.")
    outing = store.outings.get(item["outing_id"])
    if outing is None or outing["play_status"] != "OPEN":
        fail("ERR_REGISTRATION_CLOSED", "The outing's field is not open.")
    if bid < item["ask_cents"]:
        fail("ERR_INSUFFICIENT_BID",
             "The offer must reach the ask of %d cents." % item["ask_cents"])
    item["status"] = "SOLD"
    item["buyer_registration_id"] = buyer_id
    item["bid_cents"] = bid
    item["sold_at"] = store.now_iso()
    item["recorded_by_user_id"] = user_id
    touch(item)
    return ok(serial.dump(item))


@bp.post("/outing-ops/fundraising-items/<row_id>/payment")
def record_item_payment(row_id):
    auth((CHARITY_TREASURER,))
    body = validate.body()
    validate.only_fields(body, ("amount_cents",))
    amount = validate.req_money(body, "amount_cents")
    item = get_item(row_id)
    if item["status"] != "SOLD":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A payment is only collected against a SOLD item.")
    if amount != item["bid_cents"]:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "The payment must equal the recorded bid of %d cents."
             % item["bid_cents"])
    item["status"] = "PAID"
    item["collected_cents"] = amount
    touch(item)
    outing = store.outings.get(item["outing_id"])
    if outing is not None:
        derive.run_rollup(outing)
    return ok(serial.dump(item))


@bp.post("/outing-ops/fundraising-items/<row_id>/lifecycle")
def item_lifecycle(row_id):
    auth((CHARITY_TREASURER,))
    body = validate.body()
    validate.only_fields(body, ("action", "void_reason"))
    action = validate.req_enum(body, "action", enums.ITEM_ACTIONS)
    validate.opt_str(body, "void_reason")
    item = get_item(row_id)
    if action == "VOID":
        if item["status"] != "SOLD":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "VOID is not an edge out of %s." % item["status"])
        item["status"] = "VOID"
        item["buyer_registration_id"] = None
        item["bid_cents"] = 0
        item["recorded_by_user_id"] = None
        item["void_count"] = item["void_count"] + 1
    else:
        if item["status"] != "VOID":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "RELIST is not an edge out of %s." % item["status"])
        item["status"] = "LISTED"
    touch(item)
    outing = store.outings.get(item["outing_id"])
    if outing is not None:
        derive.run_rollup(outing)
    return ok(serial.dump(item))
