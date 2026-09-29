"""AdvancePayment endpoints and the 4-link void cascade."""
from decimal import Decimal

from flask import Blueprint, request

import derive
import ops
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing, require_open_posture
from store import clock_now, dec, money, touch

bp = Blueprint("advances", __name__)

BASES = ("ALE_MANDATE", "STRUCTURE_PARTIAL", "CONTENTS_PARTIAL")


@bp.post("/advance-payments")
def create_advance():
    user_id, _role = begin()
    soft = validate.soft_body()
    raw_claim = validate.raw_ref(soft, "claim_id")
    claim = validate.claim(raw_claim) if raw_claim is not None else None
    payload = validate.body()
    if claim is None:
        validate.req_string(payload, "claim_id")
    requested = validate.req_number(payload, "requested_amount", exclusive_min=0)
    basis = validate.req_enum(payload, "basis", BASES)

    event = store.events.get(claim["event_id"])
    # Position 20.
    if event is not None:
        require_open_posture(event)
    # Position 39 - headroom must be strictly positive.
    cap = derive.claim_advance_cap(claim)
    headroom = money(cap - derive.claim_advance_paid_total(claim["id"]))
    if headroom <= money(0):
        fail("ERR_ADVANCE_CAP_EXCEEDED")
    amount = money(min(money(requested), headroom))

    rec = store.base_record()
    rec.update({
        "claim_id": claim["id"],
        "reserve_entry_id": None,
        "requested_amount": requested,
        "amount": amount,
        "basis": basis,
        "status": "ISSUED",
        "void_reason": None,
        "voided_at_utc": None,
    })
    entry = ops.append_entry(claim, "PAYMENT", -amount, amount,
                            "Advance payment issued on basis %s" % basis)
    rec["reserve_entry_id"] = entry["id"]
    store.advances[rec["id"]] = rec

    if claim["payment_status"] == "NONE":
        claim["payment_status"] = "ADVANCE_ISSUED"
    if claim["advance_issuing_examiner_user_id"] is None:
        claim["advance_issuing_examiner_user_id"] = user_id
    touch(claim)
    if event is not None:
        touch(event)
    return created(derive.advance_out(rec))


@bp.get("/advance-payments")
def list_advances():
    begin()
    rows = list(store.advances.values())
    for param, field in (("claim_id", "claim_id"),
                         ("reserve_entry_id", "reserve_entry_id"),
                         ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.advance_out)


@bp.get("/advance-payments/<advance_id>")
def read_advance(advance_id):
    begin()
    return ok(derive.advance_out(validate.advance(advance_id)))


@bp.post("/advance-payments/<advance_id>/void")
def void_advance(advance_id):
    begin()
    rec = validate.advance(advance_id)
    payload = validate.body()
    void_reason = validate.req_string(payload, "void_reason")

    claim = store.claims.get(rec["claim_id"])
    if rec["status"] != "ISSUED":
        fail("ERR_ADVANCE_NOT_ISSUED")
    if claim is not None and claim["payment_status"] == "SETTLED":
        fail("ERR_CLAIM_ALREADY_SETTLED")
    # Position 40 - the mandated advance floor survives the void.
    pct = derive.governing_mandate_pct(claim["event_id"]) if claim else None
    if pct is not None:
        floor = money(dec(claim["reported_loss_amount"]) * dec(pct))
        remaining = money(derive.claim_advance_paid_total(claim["id"])
                          - dec(rec["amount"]))
        if remaining < floor:
            fail("ERR_ADVANCE_MANDATE_FLOOR")

    # Link 1.
    rec["status"] = "VOIDED"
    rec["void_reason"] = void_reason
    rec["voided_at_utc"] = clock_now()
    touch(rec)
    # Link 2 - the reversal keeps incurred_total exactly unchanged.
    ops.append_entry(claim, "REVERSAL", dec(rec["amount"]), -dec(rec["amount"]),
                     "Reversal of voided advance payment",
                     reverses_entry_id=rec["reserve_entry_id"])
    # Link 2b.
    if derive.claim_advance_paid_total(claim["id"]) == money(0) \
            and claim["payment_status"] == "ADVANCE_ISSUED":
        claim["payment_status"] = "NONE"
    touch(claim)
    # Links 3 and 4 are derived on read (snapshot staleness, event posture).
    event = store.events.get(claim["event_id"])
    if event is not None:
        touch(event)
    return ok(derive.advance_out(rec))
