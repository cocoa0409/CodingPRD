"""Routes: daily logs, music placements, as-run import, reconciliation,
affidavit issuance, close."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import store
from helpers import (err, get_body, paginate, req_date, req_int, req_str,
                     req_str_list, require_role, success_object, weekday_of)
from logic import AGENCY_COMMISSION_PCT
from logic import (append_ledger, compute_unit_rate, create_discrepancy,
                   find, post_trade_reversal, ser_log, stamp_new, touch,
                   trade_totals, trade_value_of)

bp = Blueprint("logs", __name__)

ALL = ("ProgramDirector", "TrafficDirector", "SalesRep", "SalesManager",
       "BillingAdmin")


@bp.post("/logs")
def create_log():
    body = get_body()
    station_id = req_str(body, "station_id")
    log_date = req_date(body, "log_date")
    require_role("TrafficDirector")
    find(store.stations, station_id)
    iso = log_date.isoformat()
    if any(l["station_id"] == station_id and l["log_date"] == iso
           for l in store.logs.values()):
        err("ERR_LOG_ALREADY_EXISTS",
            "A DailyLog already exists for (station_id, log_date)")
    rec = {"id": store.new_id(), "station_id": station_id, "log_date": iso,
           "clock_id": None, "clock_version": None, "posture": "DRAFT",
           "reconciled_by_user_id": None, "affidavit_issued_by_user_id": None,
           "affidavit_total_cents": None, "music_placements": []}
    stamp_new(rec)
    store.logs[rec["id"]] = rec
    return success_object(ser_log(rec), 201)


@bp.get("/logs/<lid>")
def get_log(lid):
    require_role(*ALL)
    return success_object(ser_log(find(store.logs, lid)), 200)


@bp.get("/logs")
def list_logs():
    require_role(*ALL)
    recs = list(store.logs.values())
    station_id = request.args.get("station_id")
    clock_id = request.args.get("clock_id")
    posture = request.args.get("posture")
    log_date = request.args.get("log_date")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if clock_id is not None:
        recs = [r for r in recs if r["clock_id"] == clock_id]
    if posture is not None:
        recs = [r for r in recs if r["posture"] == posture]
    if log_date is not None:
        recs = [r for r in recs if r["log_date"] == log_date]
    return paginate(recs, ser_log)


@bp.post("/logs/<lid>/lock")
def lock_log(lid):
    body = get_body()
    expected = req_int(body, "expected_log_version")
    require_role("TrafficDirector")
    log = find(store.logs, lid)
    # OCC is checked BEFORE from-state rules.
    if expected != log["version"]:
        err("ERR_STALE_VERSION",
            "expected_log_version does not match the log's current version")
    if log["posture"] != "DRAFT":
        err("ERR_INVALID_STATE", "Lock requires posture DRAFT")
    # clock_pin_selection: the unique ACTIVE clock covering weekday(log_date).
    wd = weekday_of(store_log_date(log))
    candidates = [
        c for c in store.clocks.values()
        if c["station_id"] == log["station_id"] and c["status"] == "ACTIVE"
        and wd in c["applies_weekdays"]]
    if not candidates:
        err("ERR_NO_ACTIVE_CLOCK",
            "No ACTIVE FormatClock covers weekday(log_date)")
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))
    chosen = candidates[0]
    log["clock_id"] = chosen["id"]
    log["clock_version"] = chosen["version"]
    log["posture"] = "LOCKED"
    touch(log)
    return success_object(ser_log(log), 200)


def store_log_date(log):
    from datetime import date as _d
    return _d.fromisoformat(log["log_date"])


@bp.post("/logs/<lid>/music-placements")
def place_music(lid):
    body = get_body()
    song_id = req_str(body, "song_id")
    hour = req_int(body, "hour", minimum=0, maximum=23)
    require_role("ProgramDirector", "TrafficDirector")
    log = find(store.logs, lid)
    song = find(store.songs, song_id)
    # Posture gate: music placements require LOCKED (clock pinned).
    if log["posture"] != "LOCKED":
        err("ERR_LOG_POSTURE_BLOCKED",
            "Music placements require posture LOCKED")
    # Compliance gates: song ACTIVE, then category not RETIRED.
    if song["status"] != "ACTIVE":
        err("ERR_SONG_NOT_ACTIVE",
            "Music placement references a RETIRED song")
    category = store.music_categories.get(song["category_id"])
    if category is not None and category["status"] == "RETIRED":
        err("ERR_CATEGORY_RETIRED",
            "Music placement references a song whose category is RETIRED")
    # Spin compliance, fixed order: song separation, artist separation, cap.
    # Hour-granular: minute_of_day = hour * 60; this log only.
    cand = hour * 60
    placements = log["music_placements"]
    for p in placements:
        if p["song_id"] == song_id:
            if abs(cand - p["hour"] * 60) < category["min_song_separation_min"]:
                err("ERR_SPIN_SEPARATION_VIOLATION",
                    "Same-song placement closer than min_song_separation_min")
    for p in placements:
        other = store.songs.get(p["song_id"])
        if other is not None and other["artist"] == song["artist"]:
            if abs(cand - p["hour"] * 60) < category["min_artist_separation_min"]:
                err("ERR_ARTIST_SEPARATION_VIOLATION",
                    "Same-artist placement closer than "
                    "min_artist_separation_min")
    spins = sum(1 for p in placements if p["song_id"] == song_id)
    if spins + 1 > category["max_spins_per_day"]:
        err("ERR_CATEGORY_SPIN_CAP_EXCEEDED",
            "Placement would exceed max_spins_per_day for this log")
    placements.append({"song_id": song_id, "hour": hour,
                       "placed_seq": len(placements) + 1})
    touch(log)
    return success_object(ser_log(log), 201)


@bp.post("/logs/<lid>/as-run-import")
def as_run_import(lid):
    body = get_body()
    aired_spot_ids = req_str_list(body, "aired_spot_ids")
    aired_live_read_ids = req_str_list(body, "aired_live_read_ids")
    aired_barter_avail_ids = req_str_list(body, "aired_barter_avail_ids")
    require_role("TrafficDirector")
    log = find(store.logs, lid)
    # Every listed id must exist and belong to this log (left-to-right).
    for sid in aired_spot_ids:
        spot = store.spots.get(sid)
        if spot is None or spot["log_id"] != log["id"]:
            err("ERR_NOT_FOUND",
                "aired_spot_ids contains an id not on this log")
    for rid in aired_live_read_ids:
        read = store.live_reads.get(rid)
        if read is None or read["log_id"] != log["id"]:
            err("ERR_NOT_FOUND",
                "aired_live_read_ids contains an id not on this log")
    for aid in aired_barter_avail_ids:
        avail = store.barter_avails.get(aid)
        if avail is None or avail["log_id"] != log["id"]:
            err("ERR_NOT_FOUND",
                "aired_barter_avail_ids contains an id not on this log")
    if log["posture"] != "LOCKED":
        err("ERR_INVALID_STATE", "As-run import requires posture LOCKED")

    spot_set = set(aired_spot_ids)
    read_set = set(aired_live_read_ids)
    avail_set = set(aired_barter_avail_ids)
    touched_orders = set()
    touched_contracts = set()

    # Spots: SCHEDULED -> AIRED when listed, else MAKE_GOOD_PENDING(MISSED)
    # + MISSED_SPOT discrepancy. Re-import also re-evaluates AIRED spots:
    # listed again -> stay AIRED; omitted -> MAKE_GOOD_PENDING + fresh
    # discrepancy.
    for spot in sorted((s for s in store.spots.values()
                        if s["log_id"] == log["id"]
                        and s["status"] in ("SCHEDULED", "AIRED")),
                       key=lambda s: s["_seq"]):
        if spot["id"] in spot_set:
            if spot["status"] == "SCHEDULED":
                spot["status"] = "AIRED"
                touch(spot)
                touched_orders.add(spot["order_id"])
        else:
            spot["status"] = "MAKE_GOOD_PENDING"
            spot["make_good_reason"] = "MISSED"
            touch(spot)
            create_discrepancy(log, "MISSED_SPOT", spot_id=spot["id"])
            post_trade_reversal(spot)
            touched_orders.add(spot["order_id"])

    # Live reads: only SCHEDULED units are swept.
    for read in sorted((r for r in store.live_reads.values()
                        if r["log_id"] == log["id"]
                        and r["status"] == "SCHEDULED"),
                       key=lambda r: r["_seq"]):
        if read["id"] in read_set:
            read["status"] = "AIRED"
            touch(read)
            touched_contracts.add(read["contract_id"])
        else:
            read["status"] = "MAKE_GOOD_PENDING"
            touch(read)
            create_discrepancy(log, "MISSED_READ", live_read_id=read["id"])

    # Barter avails: only SCHEDULED units are swept.
    for avail in sorted((a for a in store.barter_avails.values()
                         if a["log_id"] == log["id"]
                         and a["status"] == "SCHEDULED"),
                        key=lambda a: a["_seq"]):
        if avail["id"] in avail_set:
            avail["status"] = "AIRED"
        else:
            avail["status"] = "MISSED"
            create_discrepancy(log, "UNFILLED_BARTER",
                               barter_avail_id=avail["id"])
        touch(avail)

    # Under-coverage sweep: per CLEARED clearance covering this log date and
    # hour, fewer AIRED avails than barter_avails_per_hour -> one
    # UNFILLED_BARTER discrepancy (barter_avail_id null) per (clearance, hour).
    log_date = log["log_date"]
    wd = weekday_of(store_log_date(log))
    for clearance in sorted(
            (c for c in store.clearances.values()
             if c["station_id"] == log["station_id"]
             and c["status"] == "CLEARED"
             and wd in c["weekday_set"]
             and c["effective_from"] <= log_date <= c["effective_to"]),
            key=lambda c: (c["created_at"], c["_seq"])):
        for hour in range(clearance["start_hour"],
                          clearance["start_hour"] + clearance["duration_hours"]):
            aired_here = sum(
                1 for a in store.barter_avails.values()
                if a["clearance_id"] == clearance["id"]
                and a["log_id"] == log["id"] and a["hour"] == hour
                and a["status"] == "AIRED")
            if aired_here < clearance["barter_avails_per_hour"]:
                create_discrepancy(log, "UNFILLED_BARTER",
                                   barter_avail_id=None)

    # One version bump per affected order / contract for the whole import.
    for oid in touched_orders:
        order = store.orders.get(oid)
        if order is not None:
            touch(order)
    for cid in touched_contracts:
        contract = store.endorsement_contracts.get(cid)
        if contract is not None:
            touch(contract)

    log["posture"] = "AS_RUN"
    touch(log)
    return success_object(ser_log(log), 200)


@bp.post("/logs/<lid>/begin-reconciliation")
def begin_reconciliation(lid):
    require_role("TrafficDirector")
    log = find(store.logs, lid)
    if log["posture"] != "AS_RUN":
        err("ERR_INVALID_STATE",
            "Begin reconciliation requires posture AS_RUN")
    log["posture"] = "RECONCILING"
    touch(log)
    return success_object(ser_log(log), 200)


@bp.post("/logs/<lid>/reopen")
def reopen_log(lid):
    require_role("TrafficDirector")
    log = find(store.logs, lid)
    if log["posture"] == "RECONCILING":
        # Obligations and discrepancies persist; edits are possible again.
        log["posture"] = "LOCKED"
    elif log["posture"] == "RECONCILED":
        log["posture"] = "RECONCILING"
        log["reconciled_by_user_id"] = None
    else:
        err("ERR_INVALID_STATE",
            "Reopen requires posture RECONCILING or RECONCILED")
    touch(log)
    return success_object(ser_log(log), 200)


@bp.post("/logs/<lid>/reconcile")
def reconcile_log(lid):
    user_id, _ = require_role("TrafficDirector")
    log = find(store.logs, lid)
    if log["posture"] != "RECONCILING":
        err("ERR_INVALID_STATE", "Reconcile requires posture RECONCILING")
    from logic import log_unresolved_count
    if log_unresolved_count(log) != 0:
        err("ERR_UNRESOLVED_DISCREPANCIES",
            "Reconcile requires zero unresolved discrepancies")
    log["reconciled_by_user_id"] = user_id
    log["posture"] = "RECONCILED"
    touch(log)
    return success_object(ser_log(log), 200)


@bp.post("/logs/<lid>/issue-affidavit")
def issue_affidavit(lid):
    user_id, _ = require_role("BillingAdmin")
    log = find(store.logs, lid)
    # Segregation of duties is checked before the from-state rule.
    if (log["reconciled_by_user_id"] is not None
            and user_id == log["reconciled_by_user_id"]):
        err("ERR_SEGREGATION_OF_DUTIES",
            "Affidavit issuer must differ from the reconciler")
    if log["posture"] != "RECONCILED":
        err("ERR_INVALID_STATE",
            "Issue affidavit requires posture RECONCILED")

    station = store.stations[log["station_id"]]
    aired = sorted((s for s in store.spots.values()
                    if s["log_id"] == log["id"] and s["status"] == "AIRED"),
                   key=lambda s: s["_seq"])

    # Phase 1 (tentative): reprice REPRICED_AT_AFFIDAVIT spots and compute
    # per-agreement ADJUSTMENT deltas; reject atomically on credit breach.
    reprice_plan = []          # (spot, new_billed_rate)
    adjustment_plan = {}       # agreement_id -> list of signed deltas
    for spot in aired:
        order = store.orders[spot["order_id"]]
        if order["reprice_policy"] != "REPRICED_AT_AFFIDAVIT":
            continue
        new_rate, _ = compute_unit_rate(station, log, spot["daypart"],
                                        log["log_date"])
        reprice_plan.append((spot, new_rate))
        if order["order_kind"] == "TRADE":
            agreement = store.trade_agreements[order["trade_agreement_id"]]
            original_debit = sum(
                e["amount_cents"]
                for e in store.trade_ledger_entries.values()
                if e["spot_id"] == spot["id"] and e["entry_kind"] == "DEBIT")
            new_trade_value = trade_value_of(new_rate,
                                             agreement["trade_ratio"])
            delta = original_debit - new_trade_value
            adjustment_plan.setdefault(agreement["id"], []).append(delta)
    for agreement_id, deltas in adjustment_plan.items():
        agreement = store.trade_agreements[agreement_id]
        _, _, available = trade_totals(agreement)
        if available + sum(deltas) < 0:
            err("ERR_TRADE_CREDIT_EXCEEDED",
                "Affidavit repricing would drive available_cents below 0")

    # Phase 2 (commit): billed rates, trade ADJUSTMENT entries, total.
    for spot, new_rate in reprice_plan:
        spot["billed_rate_cents"] = new_rate
        touch(spot)
    for agreement_id, deltas in adjustment_plan.items():
        agreement = store.trade_agreements[agreement_id]
        for delta in deltas:
            append_ledger(agreement, "ADJUSTMENT", delta, spot_id=None,
                          note="affidavit repricing")

    # affidavit_billing_total: per-spot round-half-up FIRST, then sum.
    total = 0
    per_order = {}
    for spot in aired:
        per_order.setdefault(spot["order_id"], []).append(spot)
    for order_id, order_spots in per_order.items():
        order_net = 0
        for spot in order_spots:
            line = (Decimal(spot["billed_rate_cents"])
                    * (Decimal("1") - AGENCY_COMMISSION_PCT))
            order_net += int(line.quantize(Decimal("1"),
                                           rounding=ROUND_HALF_UP))
        total += order_net
    log["affidavit_total_cents"] = total
    log["affidavit_issued_by_user_id"] = user_id
    log["posture"] = "AFFIDAVIT_ISSUED"
    touch(log)
    return success_object(ser_log(log), 200)


@bp.post("/logs/<lid>/close")
def close_log(lid):
    require_role("BillingAdmin")
    log = find(store.logs, lid)
    if log["posture"] != "AFFIDAVIT_ISSUED":
        err("ERR_INVALID_STATE",
            "Close requires posture AFFIDAVIT_ISSUED")
    log["posture"] = "CLOSED"
    touch(log)
    return success_object(ser_log(log), 200)
