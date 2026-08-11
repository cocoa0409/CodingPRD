"""Cheques and deposit batches."""

from flask import Blueprint, request

import calc
import domain
import ladder as L
import serializers as S
import store
from errors import ApiError
from response import created, listing, ok, touch
from store import DB, insert
from util import (
    BATCH_MAX_CHECKS, BATCH_MAX_TOTAL_CENTS, CHECK_MAX_AMOUNT_CENTS, CLOCK,
    STATUS_ENUMS, parse_date,
)

bp = Blueprint("checks", __name__)


@bp.post("/boxes/<ident>/deposit-batches")
@L.endpoint(roles=["CmraOperator"], primary="box")
def create_batch(box):
    b = L.body()
    raw = L.req_str(b, "business_date")
    if parse_date(raw) is None:
        L._bad("business_date", "must be a YYYY-MM-DD calendar date")
    L.gate_b("deposit_batch_create", box)
    row = insert(DB.deposit_batches, {
        "box_id": box["id"], "business_date": raw, "closed": False, "closed_at": None,
    })
    return created(S.deposit_batch(row))


@bp.get("/boxes/<ident>/deposit-batches")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"], primary="box", scope=True)
def list_batches(box):
    status = L.enum_query("status", members=STATUS_ENUMS["deposit_batch"])
    data = store.batches_of_box(box["id"])
    if status is not None:
        data = [x for x in data if ("CLOSED" if x["closed"] else "OPEN") == status]
    items, total, limit, offset = L.paginate(data, S.deposit_batch)
    return listing(items, total, limit, offset)


@bp.get("/deposit-batches/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"],
            primary="deposit_batch", scope=True)
def read_batch(batch):
    return ok(S.deposit_batch(batch))


@bp.post("/deposit-batches/<ident>/checks")
@L.endpoint(roles=["CmraOperator"], primary="deposit_batch")
def create_check(batch):
    b = L.body()
    # rung 7 -- see the friction-2 adjudication note in routes_disposition.py
    mail_item_id = b.get("mail_item_id")
    if mail_item_id is not None:
        if not isinstance(mail_item_id, str) or mail_item_id not in DB.mail_items:
            raise ApiError("ERR_MAIL_ITEM_NOT_FOUND")
    mail_item_id = L.req_str(b, "mail_item_id")                     # rung 9
    payee = L.req_str(b, "payee_name_on_check")
    amount = L.req_int(b, "amount_cents", 1)
    endorsed = L.req_bool(b, "endorsed", False)
    L.req_int(b, "expected_deposit_batch_version", 0)
    box = DB.boxes.get(batch["box_id"])
    L.gate_a("check_create", box)                                   # rung 11
    L.gate_b("check_create", box)                                   # rung 12
    L.occ(b, "expected_deposit_batch_version", batch)               # rung 13
    if batch["closed"]:                                             # rung 14
        raise ApiError("ERR_INVALID_STATE")

    matched, mode = calc.payee_match(batch["box_id"], payee)
    # Adjudication of friction 1 (reading A): Gate C applies to this operation
    # -- the PRD lists it in Gate C's blocked table -- evaluated over the member
    # payee matching resolves inside this request.  When matching resolves
    # nobody there is no matched Recipient to evaluate, so the gate is skipped
    # and the declared PAYEE_MISMATCH hold stays reachable.
    if matched is not None:
        L.gate_c_for_recipient(matched)                             # rungs 17-19

    L.clock_hour_cutoff()                                           # rung 29

    checks = store.checks_of_batch(batch["id"])                     # rung 31
    received = sum(c["amount_cents"] for c in checks)
    if (amount > CHECK_MAX_AMOUNT_CENTS
            or received + amount > BATCH_MAX_TOTAL_CENTS
            or len(checks) >= BATCH_MAX_CHECKS):
        raise ApiError("ERR_DEPOSIT_CAP_EXCEEDED")

    if matched is not None and endorsed:
        status, hold_reason = "MATCHED", "NONE"
    else:
        status = "HELD"
        hold_reason = "NOT_ENDORSED" if matched is not None else "PAYEE_MISMATCH"
    row = insert(DB.check_deposits, {
        "mail_item_id": mail_item_id, "deposit_batch_id": batch["id"],
        "matched_recipient_id": matched["id"] if (matched is not None and status == "MATCHED")
                                else None,
        "payee_name_on_check": payee, "amount_cents": amount, "endorsed": endorsed,
        "match_mode": mode if status == "MATCHED" else "NONE",
        "status": status, "hold_reason": hold_reason,
    })
    touch(batch)
    return created(S.check_deposit(row))


@bp.get("/check-deposits")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"])
def list_checks():
    from flask import g
    status = L.enum_query("status", members=STATUS_ENUMS["check_deposit"])
    data = store.rows(DB.check_deposits)
    for key in ("mail_item_id", "deposit_batch_id", "matched_recipient_id"):
        val = request.args.get(key)
        if val is not None:
            data = [c for c in data if c[key] == val]
    if status is not None:
        data = [c for c in data if c["status"] == status]
    if g.role == "BoxHolder":
        data = [c for c in data
                if (store.box_of_check(c) or {}).get("id") == g.user_id]
    items, total, limit, offset = L.paginate(data, S.check_deposit)
    return listing(items, total, limit, offset)


@bp.get("/check-deposits/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"],
            primary="check_deposit", scope=True)
def read_check(c):
    return ok(S.check_deposit(c))


@bp.post("/check-deposits/<ident>/rematch")
@L.endpoint(roles=["CmraOperator"], primary="check_deposit")
def rematch_check(c):
    batch = DB.deposit_batches[c["deposit_batch_id"]]
    L.gate_b("check_rematch", store.box_of_check(c))
    if c["status"] != "HELD" or not c["endorsed"]:                  # rung 14
        raise ApiError("ERR_INVALID_STATE")
    matched, mode = calc.payee_match(batch["box_id"], c["payee_name_on_check"])
    if matched is None:                                             # rung 30
        raise ApiError("ERR_PAYEE_MISMATCH")
    c["status"] = "MATCHED"
    c["matched_recipient_id"] = matched["id"]
    c["match_mode"] = mode
    c["hold_reason"] = "NONE"
    touch(c)
    return ok(S.check_deposit(c))


@bp.post("/check-deposits/<ident>/return")
@L.endpoint(roles=["CmraOperator"], primary="check_deposit")
def return_check(c):
    L.gate_b("check_return", store.box_of_check(c))
    if c["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE")
    c["status"] = "RETURNED"
    touch(c)
    return ok(S.check_deposit(c))


@bp.post("/deposit-batches/<ident>/close")
@L.endpoint(roles=["CmraOperator"], primary="deposit_batch")
def close_batch(batch):
    L.gate_b("deposit_batch_close", DB.boxes.get(batch["box_id"]))
    if batch["closed"]:
        raise ApiError("ERR_INVALID_STATE")
    for c in store.checks_of_batch(batch["id"]):
        if c["status"] != "MATCHED":
            continue
        c["status"] = "DEPOSITED"
        touch(c)
        item = store.mail_item(c["mail_item_id"])
        if item is None or item["handling_status"] != "PENDING_DISPOSITION":
            continue
        winner = domain.winning_disposition(item["id"])
        if winner is None or winner["disposition_type"] != "DEPOSIT":
            continue
        winner["status"] = "EXECUTED"
        winner["resolution_reason"] = "EXECUTED"
        winner["executed_at"] = CLOCK.now
        touch(winner)
        item["handling_status"] = "DEPOSITED"
        domain.end_custody(item)
        touch(item)
    batch["closed"] = True
    batch["closed_at"] = CLOCK.now
    touch(batch)
    return ok(S.deposit_batch(batch))
