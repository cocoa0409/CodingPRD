"""CharitableReceipt endpoints: append-only receipting (PRD 3.7)."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import CHARITY_TREASURER, PARTICIPANT, TOURNAMENT_DIRECTOR, auth
from envelope import created, ok, paginate
from errors import fail
from lookup import item as get_item
from lookup import outing as get_outing
from lookup import receipt as get_receipt
from lookup import registration as get_registration
from store import touch

bp = Blueprint("receipts", __name__)

READ_ROLES = (CHARITY_TREASURER, TOURNAMENT_DIRECTOR, PARTICIPANT)

CREATE_FIELDS = ("outing_id", "receipt_kind", "registration_id",
                 "fundraising_item_id", "reverses_receipt_id")


@bp.post("/outing-ops/receipts")
def issue_receipt():
    user_id, _role = auth((CHARITY_TREASURER,))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    outing_id = validate.req_ref(body, "outing_id")
    kind = validate.req_enum(body, "receipt_kind", enums.RECEIPT_KIND)
    registration_id = validate.opt_ref(body, "registration_id")
    item_id = validate.opt_ref(body, "fundraising_item_id")
    reverses_id = validate.opt_ref(body, "reverses_receipt_id")
    outing = get_outing(outing_id)
    reg = get_registration(registration_id) if registration_id else None
    item = get_item(item_id) if item_id else None
    original = get_receipt(reverses_id) if reverses_id else None
    if reg is not None and reg["outing_id"] != outing_id:
        fail("ERR_CROSS_OUTING_REFERENCE",
             "The registration belongs to another outing.")
    if item is not None and item["outing_id"] != outing_id:
        fail("ERR_CROSS_OUTING_REFERENCE",
             "The fundraising item belongs to another outing.")
    if original is not None and original["outing_id"] != outing_id:
        fail("ERR_CROSS_OUTING_REFERENCE",
             "The reversed receipt belongs to another outing.")

    # tier 7 - receipt subject arity
    named = [x for x in (registration_id, item_id, reverses_id) if x]
    if len(named) != 1:
        fail("ERR_RECEIPT_SUBJECT_AMBIGUOUS",
             "A receipt names exactly one subject.")
    if kind == "REGISTRATION" and reg is None:
        fail("ERR_RECEIPT_SUBJECT_AMBIGUOUS",
             "A REGISTRATION receipt names a registration_id.")
    if kind == "FUNDRAISING_ITEM" and item is None:
        fail("ERR_RECEIPT_SUBJECT_AMBIGUOUS",
             "A FUNDRAISING_ITEM receipt names a fundraising_item_id.")
    if kind == "REVERSAL" and original is None:
        fail("ERR_RECEIPT_SUBJECT_AMBIGUOUS",
             "A REVERSAL receipt names a reverses_receipt_id.")

    if kind == "REVERSAL":
        _require_reversible(original)
        row = derive.append_reversal(original, user_id)
        return created(serial.dump(row))

    # tier 12 - safety, then the constraint sub-tier
    if item is not None:
        if item["recorded_by_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The user who recorded the sale may not issue its receipt.")
        if item["item_type"] == "RAFFLE":
            fail("ERR_RAFFLE_NOT_DEDUCTIBLE",
                 "A raffle purchase buys a chance rather than making a gift.")
    if kind == "REGISTRATION":
        if derive.live_forward_receipt(outing_id, registration_id=reg["id"]) is not None:
            fail("ERR_DUPLICATE_RECEIPT",
                 "The registration already carries a live receipt.")
        payment = reg["amount_paid_cents"] - reg["amount_refunded_cents"]
        tier = derive.tier_of(reg)
        declared = tier["gsv_cents"] if tier is not None else 0
        gsv, deductible = calc.registration_deduction(payment, declared)
    else:
        if derive.live_forward_receipt(outing_id, fundraising_item_id=item["id"]) is not None:
            fail("ERR_DUPLICATE_RECEIPT",
                 "The fundraising item already carries a live receipt.")
        payment = item["collected_cents"]
        if item["item_type"] == "AUCTION":
            gsv = item["fmv_cents"]
        else:
            gsv = 0
        deductible = payment - gsv
        if deductible < 0:
            deductible = 0

    row = store.new_row("CharitableReceipt", {
        "outing_id": outing_id,
        "receipt_kind": kind,
        "registration_id": registration_id if kind == "REGISTRATION" else None,
        "fundraising_item_id": item_id if kind == "FUNDRAISING_ITEM" else None,
        "reverses_receipt_id": None,
        "payment_cents": payment,
        "gsv_cents": gsv,
        "deductible_amount_cents": deductible,
        "receipt_number": derive.next_receipt_number(outing_id),
        "issued_by_user_id": user_id,
        "issued_at": store.now_iso(),
    }, common=False)
    if kind == "REGISTRATION":
        reg["receipt_issued"] = True
        touch(reg)
    elif item["status"] == "PAID":
        item["status"] = "RECEIPTED"
        touch(item)
    derive.rederive_receipted_total(outing)
    return created(serial.dump(row))


def _require_reversible(original):
    if original["receipt_kind"] == "REVERSAL":
        fail("ERR_RECEIPT_IMMUTABLE", "A reversal may not itself be reversed.")
    if derive.reversal_of(original["id"]) is not None:
        fail("ERR_RECEIPT_IMMUTABLE",
             "The receipt already carries a live reversal.")


@bp.get("/outing-ops/receipts/<row_id>")
def read_receipt(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_receipt(row_id)))


@bp.get("/outing-ops/receipts")
def list_receipts():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    registration_id = validate.q_str("registration_id")
    item_id = validate.q_str("fundraising_item_id")
    reverses_id = validate.q_str("reverses_receipt_id")
    kind = validate.q_enum("receipt_kind", enums.RECEIPT_KIND)
    rows = store.sorted_rows(store.receipts.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    if item_id is not None:
        rows = [r for r in rows if r["fundraising_item_id"] == item_id]
    if reverses_id is not None:
        rows = [r for r in rows if r["reverses_receipt_id"] == reverses_id]
    if kind is not None:
        rows = [r for r in rows if r["receipt_kind"] == kind]
    return paginate(rows, limit, offset, serial.dump)


@bp.post("/outing-ops/receipts/<row_id>/reversal")
def reverse_receipt(row_id):
    user_id, _role = auth((CHARITY_TREASURER,))
    body = validate.body()
    validate.only_fields(body, ("reversal_reason",))
    validate.opt_str(body, "reversal_reason")
    original = get_receipt(row_id)
    _require_reversible(original)
    row = derive.append_reversal(original, user_id)
    return created(serial.dump(row))
