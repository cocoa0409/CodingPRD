"""Routes: endorsement contracts, live reads, discrepancies, remote events."""
from flask import Blueprint, request

import store
from helpers import (err, get_body, opt_int, paginate, req_date, req_int,
                     req_str, req_weekday_set, require_role, success_object,
                     weekday_of)
from logic import (auto_resolve_linked_discrepancy, contract_reads_completed,
                   find, live_read_fits, ser_contract, ser_discrepancy,
                   ser_live_read, ser_remote_event, stamp_new, touch)

bp = Blueprint("endorsements", __name__)

ALL = ("ProgramDirector", "TrafficDirector", "SalesRep", "SalesManager",
       "BillingAdmin")

LIVE_READ_DURATIONS = {30, 60}


# ---------------------------------------------------------------------------
# Endorsement contracts
# ---------------------------------------------------------------------------
@bp.post("/endorsement-contracts")
def create_contract():
    body = get_body()
    station_id = req_str(body, "station_id")
    advertiser_name = req_str(body, "advertiser_name")
    host_name = req_str(body, "host_name")
    program_weekdays = req_weekday_set(body, "program_weekdays")
    start_hour = req_int(body, "program_start_hour", minimum=0, maximum=23)
    end_hour = req_int(body, "program_end_hour")
    reads_per_week = req_int(body, "reads_per_week", minimum=1)
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    require_role("SalesRep")
    find(store.stations, station_id)
    if end_hour <= start_hour or end_hour > 24:
        err("ERR_BAD_REQUEST",
            "program_end_hour must be > program_start_hour and <= 24")
    if end_date < start_date:
        err("ERR_BAD_REQUEST", "end_date must be >= start_date")
    # endorsement_contracted_total: whole weeks only.
    window_days = (end_date - start_date).days + 1
    contracted_total = reads_per_week * (window_days // 7)
    rec = {"id": store.new_id(), "station_id": station_id,
           "advertiser_name": advertiser_name, "host_name": host_name,
           "program_weekdays": program_weekdays,
           "program_start_hour": start_hour, "program_end_hour": end_hour,
           "reads_per_week": reads_per_week,
           "start_date": start_date.isoformat(),
           "end_date": end_date.isoformat(),
           "contracted_reads_total": contracted_total, "status": "DRAFT"}
    stamp_new(rec)
    store.endorsement_contracts[rec["id"]] = rec
    return success_object(ser_contract(rec), 201)


@bp.get("/endorsement-contracts/<cid>")
def get_contract(cid):
    require_role(*ALL)
    return success_object(
        ser_contract(find(store.endorsement_contracts, cid)), 200)


@bp.get("/endorsement-contracts")
def list_contracts():
    require_role(*ALL)
    recs = list(store.endorsement_contracts.values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_contract)


@bp.post("/endorsement-contracts/<cid>/activate")
def activate_contract(cid):
    require_role("SalesManager")
    contract = find(store.endorsement_contracts, cid)
    if contract["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Activate requires status DRAFT")
    today = store.current_date().isoformat()
    if not (contract["start_date"] <= today <= contract["end_date"]):
        err("ERR_FLIGHT_WINDOW_INVALID",
            "Logical clock date must fall inside the contract window")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(ser_contract(contract), 200)


@bp.post("/endorsement-contracts/<cid>/close")
def close_contract(cid):
    require_role("SalesManager")
    contract = find(store.endorsement_contracts, cid)
    if contract["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Close requires status ACTIVE")
    today = store.current_date().isoformat()
    if not today > contract["end_date"]:
        err("ERR_FLIGHT_WINDOW_INVALID",
            "Logical clock date must be strictly past end_date")
    if contract_reads_completed(contract) >= contract["contracted_reads_total"]:
        contract["status"] = "COMPLETED"
    else:
        contract["status"] = "BREACHED"
    touch(contract)
    return success_object(ser_contract(contract), 200)


@bp.post("/endorsement-contracts/<cid>/cancel")
def cancel_contract(cid):
    require_role("SalesRep", "SalesManager")
    contract = find(store.endorsement_contracts, cid)
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        err("ERR_INVALID_STATE", "Cancel requires status DRAFT or ACTIVE")
    for read in store.live_reads.values():
        if (read["contract_id"] == contract["id"]
                and read["status"] == "SCHEDULED"):
            read["status"] = "CANCELLED"
            touch(read)
    contract["status"] = "CANCELLED"
    touch(contract)
    return success_object(ser_contract(contract), 200)


# ---------------------------------------------------------------------------
# Live reads
# ---------------------------------------------------------------------------
def _contract_window_gate(contract, air_date, hour):
    from datetime import date as _date
    wd = weekday_of(_date.fromisoformat(air_date))
    if (wd not in contract["program_weekdays"]
            or not (contract["program_start_hour"] <= hour
                    < contract["program_end_hour"])
            or not (contract["start_date"] <= air_date
                    <= contract["end_date"])):
        err("ERR_CONTRACT_WINDOW_VIOLATION",
            "Live read outside contract program weekdays, hour window, or "
            "date range")


@bp.post("/live-reads")
def schedule_live_read():
    body = get_body()
    contract_id = req_str(body, "contract_id")
    log_id = req_str(body, "log_id")
    hour = req_int(body, "hour", minimum=0, maximum=23)
    duration_sec = opt_int(body, "duration_sec")
    if duration_sec is None:
        duration_sec = 60
    if duration_sec not in LIVE_READ_DURATIONS:
        err("ERR_BAD_REQUEST", "duration_sec must be one of 30, 60")
    require_role("TrafficDirector")
    contract = find(store.endorsement_contracts, contract_id)
    log = find(store.logs, log_id)
    if log["posture"] not in ("DRAFT", "LOCKED"):
        err("ERR_LOG_POSTURE_BLOCKED",
            "Live read scheduling requires log posture DRAFT or LOCKED")
    if contract["status"] != "ACTIVE":
        err("ERR_CONTRACT_NOT_ACTIVE",
            "Contract is not in ACTIVE status")
    _contract_window_gate(contract, log["log_date"], hour)
    if not live_read_fits(log, hour):
        err("ERR_HOUR_CAPACITY_EXCEEDED",
            "Hour LIVE_READ_WINDOW pool cannot fit the read")
    rec = {"id": store.new_id(), "station_id": contract["station_id"],
           "contract_id": contract["id"], "log_id": log["id"],
           "air_date": log["log_date"], "hour": hour,
           "duration_sec": duration_sec, "makeup_of_live_read_id": None,
           "status": "SCHEDULED"}
    stamp_new(rec)
    store.live_reads[rec["id"]] = rec
    return success_object(ser_live_read(rec), 201)


@bp.get("/live-reads/<rid>")
def get_live_read(rid):
    require_role(*ALL)
    return success_object(ser_live_read(find(store.live_reads, rid)), 200)


@bp.get("/live-reads")
def list_live_reads():
    require_role(*ALL)
    recs = list(store.live_reads.values())
    station_id = request.args.get("station_id")
    contract_id = request.args.get("contract_id")
    log_id = request.args.get("log_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if contract_id is not None:
        recs = [r for r in recs if r["contract_id"] == contract_id]
    if log_id is not None:
        recs = [r for r in recs if r["log_id"] == log_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_live_read)


@bp.post("/live-reads/<rid>/reschedule")
def reschedule_live_read(rid):
    body = get_body()
    target_log_id = req_str(body, "target_log_id")
    target_hour = req_int(body, "target_hour", minimum=0, maximum=23)
    require_role("TrafficDirector")
    read = find(store.live_reads, rid)
    target_log = find(store.logs, target_log_id)
    if read["status"] != "MAKE_GOOD_PENDING":
        err("ERR_INVALID_STATE",
            "Reschedule requires status MAKE_GOOD_PENDING")
    if target_log["posture"] not in ("DRAFT", "LOCKED"):
        err("ERR_LOG_POSTURE_BLOCKED",
            "Reschedule target log must be DRAFT or LOCKED")
    contract = store.endorsement_contracts[read["contract_id"]]
    _contract_window_gate(contract, target_log["log_date"], target_hour)
    if not live_read_fits(target_log, target_hour):
        err("ERR_HOUR_CAPACITY_EXCEEDED",
            "Target hour LIVE_READ_WINDOW pool cannot fit the make-good")
    read["status"] = "RESOLVED"
    touch(read)
    successor = {"id": store.new_id(), "station_id": read["station_id"],
                 "contract_id": read["contract_id"],
                 "log_id": target_log["id"],
                 "air_date": target_log["log_date"], "hour": target_hour,
                 "duration_sec": read["duration_sec"],
                 "makeup_of_live_read_id": read["id"], "status": "SCHEDULED"}
    stamp_new(successor)
    store.live_reads[successor["id"]] = successor
    auto_resolve_linked_discrepancy("MISSED_READ", "live_read_id",
                                    read["id"])
    return success_object(ser_live_read(successor), 201)


@bp.post("/live-reads/<rid>/issue-credit")
def issue_live_read_credit(rid):
    body = get_body()
    note = body.get("note")
    if note is None:
        note = body.get("resolution_note")
    if note is not None and not isinstance(note, str):
        err("ERR_BAD_REQUEST", "note must be a string")
    require_role("BillingAdmin")
    read = find(store.live_reads, rid)
    if read["status"] != "MAKE_GOOD_PENDING":
        err("ERR_INVALID_STATE",
            "Issue credit requires status MAKE_GOOD_PENDING")
    read["status"] = "RESOLVED"
    touch(read)
    linked = auto_resolve_linked_discrepancy("MISSED_READ", "live_read_id",
                                             read["id"])
    if linked is not None and note is not None:
        linked["resolution_note"] = note
    return success_object(ser_live_read(read), 200)


# ---------------------------------------------------------------------------
# Discrepancies
# ---------------------------------------------------------------------------
@bp.get("/discrepancies/<did>")
def get_discrepancy(did):
    require_role(*ALL)
    return success_object(ser_discrepancy(find(store.discrepancies, did)),
                          200)


@bp.get("/discrepancies")
def list_discrepancies():
    require_role(*ALL)
    recs = list(store.discrepancies.values())
    station_id = request.args.get("station_id")
    log_id = request.args.get("log_id")
    spot_id = request.args.get("spot_id")
    live_read_id = request.args.get("live_read_id")
    barter_avail_id = request.args.get("barter_avail_id")
    status = request.args.get("status")
    kind = request.args.get("discrepancy_kind")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if log_id is not None:
        recs = [r for r in recs if r["log_id"] == log_id]
    if spot_id is not None:
        recs = [r for r in recs if r["spot_id"] == spot_id]
    if live_read_id is not None:
        recs = [r for r in recs if r["live_read_id"] == live_read_id]
    if barter_avail_id is not None:
        recs = [r for r in recs if r["barter_avail_id"] == barter_avail_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if kind is not None:
        recs = [r for r in recs if r["discrepancy_kind"] == kind]
    return paginate(recs, ser_discrepancy)


def _read_note(body):
    note = body.get("resolution_note")
    if note is None:
        note = body.get("note")
    if note is not None and not isinstance(note, str):
        err("ERR_BAD_REQUEST", "resolution_note must be a string")
    return note


@bp.post("/discrepancies/<did>/resolve")
def resolve_discrepancy(did):
    body = get_body()
    note = _read_note(body)
    user_id, _ = require_role("TrafficDirector")
    disc = find(store.discrepancies, did)
    if disc["status"] != "UNRESOLVED":
        err("ERR_INVALID_STATE", "Resolve requires status UNRESOLVED")
    # Explicit resolve is allowed only for UNFILLED_BARTER; MISSED_SPOT and
    # MISSED_READ resolve via their obligation.
    if disc["discrepancy_kind"] != "UNFILLED_BARTER":
        err("ERR_DISCREPANCY_NOT_WAIVABLE",
            "Only UNFILLED_BARTER discrepancies are manually resolvable")
    disc["status"] = "RESOLVED"
    disc["resolved_by_user_id"] = user_id
    if note is not None:
        disc["resolution_note"] = note
    touch(disc)
    log = store.logs.get(disc["log_id"])
    if log is not None:
        touch(log)  # unresolved_discrepancy_count recomputed
    return success_object(ser_discrepancy(disc), 200)


@bp.post("/discrepancies/<did>/waive")
def waive_discrepancy(did):
    body = get_body()
    note = _read_note(body)
    user_id, _ = require_role("BillingAdmin")
    disc = find(store.discrepancies, did)
    if disc["status"] != "UNRESOLVED":
        err("ERR_INVALID_STATE", "Waive requires status UNRESOLVED")
    if disc["discrepancy_kind"] != "UNFILLED_BARTER":
        err("ERR_DISCREPANCY_NOT_WAIVABLE",
            "Only UNFILLED_BARTER discrepancies are waivable")
    disc["status"] = "WAIVED"
    disc["resolved_by_user_id"] = user_id
    if note is not None:
        disc["resolution_note"] = note
    touch(disc)
    log = store.logs.get(disc["log_id"])
    if log is not None:
        touch(log)  # unresolved_discrepancy_count recomputed
    return success_object(ser_discrepancy(disc), 200)


# ---------------------------------------------------------------------------
# Remote events (remote broadcast & event sponsorship packages)
# ---------------------------------------------------------------------------
@bp.post("/remote-events")
def create_remote_event():
    body = get_body()
    station_id = req_str(body, "station_id")
    event_name = req_str(body, "event_name")
    sponsor_name = req_str(body, "sponsor_name")
    event_date = req_date(body, "event_date")
    spot_units_promised = req_int(body, "spot_units_promised", minimum=1)
    package_price = req_int(body, "package_price_cents", minimum=1)
    require_role("SalesRep")
    find(store.stations, station_id)
    rec = {"id": store.new_id(), "station_id": station_id,
           "event_name": event_name, "sponsor_name": sponsor_name,
           "event_date": event_date.isoformat(),
           "spot_units_promised": spot_units_promised,
           "package_price_cents": package_price, "status": "PLANNED"}
    stamp_new(rec)
    store.remote_events[rec["id"]] = rec
    return success_object(ser_remote_event(rec), 201)


@bp.get("/remote-events/<eid>")
def get_remote_event(eid):
    require_role(*ALL)
    return success_object(ser_remote_event(find(store.remote_events, eid)),
                          200)


@bp.get("/remote-events")
def list_remote_events():
    require_role(*ALL)
    recs = list(store.remote_events.values())
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_remote_event)


@bp.post("/remote-events/<eid>/confirm")
def confirm_remote_event(eid):
    require_role("SalesManager")
    event = find(store.remote_events, eid)
    if event["status"] != "PLANNED":
        err("ERR_INVALID_STATE", "Confirm requires status PLANNED")
    today = store.current_date().isoformat()
    if not event["event_date"] >= today:
        err("ERR_FLIGHT_WINDOW_INVALID",
            "event_date must be on or after the current logical clock date")
    event["status"] = "CONFIRMED"
    touch(event)
    return success_object(ser_remote_event(event), 200)


@bp.post("/remote-events/<eid>/cancel")
def cancel_remote_event(eid):
    require_role("SalesManager")
    event = find(store.remote_events, eid)
    if event["status"] not in ("PLANNED", "CONFIRMED"):
        err("ERR_INVALID_STATE",
            "Cancel requires status PLANNED or CONFIRMED")
    # Spots already booked with this event_id stand (NOT cancelled).
    event["status"] = "CANCELLED"
    touch(event)
    return success_object(ser_remote_event(event), 200)


@bp.post("/remote-events/<eid>/settle")
def settle_remote_event(eid):
    require_role("SalesManager")
    event = find(store.remote_events, eid)
    if event["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", "Settle requires status CONFIRMED")
    # Cross-entity gate: the event date's log must exist and hold an issued
    # affidavit (AFFIDAVIT_ISSUED or CLOSED).
    log = next((l for l in store.logs.values()
                if l["station_id"] == event["station_id"]
                and l["log_date"] == event["event_date"]), None)
    if log is None:
        err("ERR_NOT_FOUND",
            "No DailyLog exists for (station_id, event_date)")
    if log["posture"] not in ("AFFIDAVIT_ISSUED", "CLOSED"):
        err("ERR_LOG_POSTURE_BLOCKED",
            "Event date's log must have an issued affidavit before settle")
    from logic import event_spots_delivered
    if event_spots_delivered(event) >= event["spot_units_promised"]:
        event["status"] = "DELIVERED"
    else:
        event["status"] = "DEFAULTED"
    touch(event)
    return success_object(ser_remote_event(event), 200)
