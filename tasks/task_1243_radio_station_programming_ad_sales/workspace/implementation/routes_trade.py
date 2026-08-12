"""Routes: trade agreements and the append-only trade ledger."""
from flask import Blueprint, request

import store
from helpers import (err, get_body, opt_str, paginate, req_int, req_number,
                     req_present, req_str, require_role, success_object)
from logic import (append_ledger, find, ser_agreement, ser_ledger_entry,
                   stamp_new, touch)

bp = Blueprint("trade", __name__)

ALL = ("ProgramDirector", "TrafficDirector", "SalesRep", "SalesManager",
       "BillingAdmin")


@bp.post("/trade-agreements")
def create_agreement():
    body = get_body()
    station_id = req_str(body, "station_id")
    vendor_name = req_str(body, "vendor_name")
    credit_limit = req_int(body, "credit_limit_cents", minimum=1)
    trade_ratio = req_number(body, "trade_ratio", minimum=0,
                             exclusive_minimum=True)
    require_role("SalesRep", "SalesManager")
    find(store.stations, station_id)
    rec = {"id": store.new_id(), "station_id": station_id,
           "vendor_name": vendor_name, "credit_limit_cents": credit_limit,
           "trade_ratio": trade_ratio, "status": "ACTIVE"}
    stamp_new(rec)
    store.trade_agreements[rec["id"]] = rec
    return success_object(ser_agreement(rec), 201)


@bp.get("/trade-agreements/<aid>")
def get_agreement(aid):
    require_role(*ALL)
    return success_object(ser_agreement(find(store.trade_agreements, aid)),
                          200)


@bp.get("/trade-agreements")
def list_agreements():
    require_role(*ALL)
    recs = list(store.trade_agreements.values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_agreement)


@bp.post("/trade-agreements/<aid>/suspend")
def suspend_agreement(aid):
    require_role("BillingAdmin")
    agreement = find(store.trade_agreements, aid)
    if agreement["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Suspend requires status ACTIVE")
    agreement["status"] = "SUSPENDED"
    touch(agreement)
    return success_object(ser_agreement(agreement), 200)


@bp.post("/trade-agreements/<aid>/close")
def close_agreement(aid):
    require_role("BillingAdmin")
    agreement = find(store.trade_agreements, aid)
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE",
            "Close requires status ACTIVE or SUSPENDED")
    # Precondition: no spot of any order pointing at this agreement may be
    # SCHEDULED.
    for spot in store.spots.values():
        if spot["status"] != "SCHEDULED":
            continue
        order = store.orders.get(spot["order_id"])
        if order and order["trade_agreement_id"] == agreement["id"]:
            err("ERR_INVALID_STATE",
                "Agreement still has SCHEDULED trade spots")
    agreement["status"] = "CLOSED"
    touch(agreement)
    return success_object(ser_agreement(agreement), 200)


@bp.post("/trade-agreements/<aid>/ledger-entries")
def append_manual_adjustment(aid):
    body = get_body()
    kind = req_present(body, "entry_kind")
    amount = req_int(body, "amount_cents")
    note = opt_str(body, "note")
    require_role("BillingAdmin")
    agreement = find(store.trade_agreements, aid)
    if kind != "ADJUSTMENT":
        # DEBIT/REVERSAL are system-generated from the spot lifecycle; only
        # manual ADJUSTMENT entries are accepted here.
        err("ERR_BAD_REQUEST",
            "Only manual ADJUSTMENT entries may be appended directly")
    # Fiscal: available may never go negative.
    from logic import trade_totals
    _, _, available = trade_totals(agreement)
    if available + amount < 0:
        err("ERR_TRADE_CREDIT_EXCEEDED",
            "Negative ADJUSTMENT would drive available_cents below 0")
    entry = append_ledger(agreement, "ADJUSTMENT", amount, spot_id=None,
                          note=note)
    return success_object(ser_ledger_entry(entry), 201)


@bp.get("/trade-agreements/<aid>/ledger-entries")
def list_agreement_ledger(aid):
    require_role(*ALL)
    agreement = find(store.trade_agreements, aid)
    from logic import ledger_entries_of
    return paginate(ledger_entries_of(agreement["id"]), ser_ledger_entry)


@bp.get("/spots/<sid>/ledger-entries")
def list_spot_ledger(sid):
    require_role(*ALL)
    spot = find(store.spots, sid)
    entries = sorted(
        (e for e in store.trade_ledger_entries.values()
         if e["spot_id"] == spot["id"]),
        key=lambda e: e["entry_seq"])
    return paginate(entries, ser_ledger_entry)
