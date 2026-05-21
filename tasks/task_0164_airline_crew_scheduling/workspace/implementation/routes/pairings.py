"""Pairing, DutyPeriod, FlightLeg endpoints."""
from flask import Blueprint, request, g

import store
import validators
import serializers
import responses
from auth import require_roles
from errors import raise_error
from clock import parse_iso, format_iso
from services import pairing_service, counters


bp = Blueprint("pairings", __name__)


# ---------------------- Pairing CRUD ----------------------

@bp.post("/pairings")
@require_roles("CrewScheduler")
def create_pairing():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "pairing_code", "base_airport", "required_rank_composition")

    pairing_code = validators.require_string(body, "pairing_code")
    base = validators.require_iata(body["base_airport"], "base_airport")
    comp = body["required_rank_composition"]
    if not isinstance(comp, dict):
        raise_error("ERR_VALIDATION_FAILED",
                    "required_rank_composition must be an object.")

    for p in store.pairings.values():
        if p["pairing_code"] == pairing_code:
            raise_error("ERR_VALIDATION_FAILED", "pairing_code must be unique.")

    row = {
        "pairing_code": pairing_code,
        "base_airport": base,
        "start_at": None,
        "end_at": None,
        "required_rank_composition": comp,
        "total_block_minutes": 0,
        "total_duty_minutes": 0,
        "status": "DRAFT",
        "bid_window_id": None,
    }
    store.init_common(row)
    store.pairings[row["id"]] = row
    return responses.success(serializers.pairing(row), http_status=201)


@bp.get("/pairings/<pairing_id>")
def get_pairing(pairing_id):
    row = store.pairings.get(pairing_id)
    if row is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Pairing not found.")
    return responses.success(serializers.pairing(row))


@bp.get("/pairings")
def list_pairings():
    limit, offset = validators.parse_pagination(request.args)
    status = request.args.get("status")
    base = request.args.get("base_airport")
    rows = list(store.pairings.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if base:
        rows = [r for r in rows if r["base_airport"] == base]
    rows.sort(key=lambda r: r["created_at"])
    page, pag = validators.paginate(rows, limit, offset)
    return responses.success([serializers.pairing(r) for r in page],
                             response_type="array", pagination=pag)


# ---------------------- DutyPeriod ----------------------

@bp.post("/pairings/<pairing_id>/duty-periods")
@require_roles("CrewScheduler")
def create_duty_period(pairing_id):
    pairing = store.pairings.get(pairing_id)
    if pairing is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Pairing not found.")

    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "sequence_no", "report_at", "release_at")

    # Pairing must be DRAFT
    if pairing["status"] != "DRAFT":
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing must be in DRAFT to add duty periods.")

    seq_no = validators.require_int(body, "sequence_no", min_value=1)
    report_at = validators.parse_dt(body["report_at"], "report_at")
    release_at = validators.parse_dt(body["release_at"], "release_at")

    if release_at <= report_at:
        raise_error("ERR_VALIDATION_FAILED",
                    "release_at must be after report_at.")

    duty_min = int((release_at - report_at).total_seconds() // 60)

    # Unique sequence_no within pairing
    for dp in store.duty_periods.values():
        if dp["pairing_id"] == pairing_id and dp["sequence_no"] == seq_no:
            raise_error("ERR_VALIDATION_FAILED",
                        "sequence_no must be unique within pairing.")

    row = {
        "pairing_id": pairing_id,
        "sequence_no": seq_no,
        "report_at": format_iso(report_at),
        "release_at": format_iso(release_at),
        "duty_minutes": duty_min,
        "block_minutes": 0,
    }
    store.init_common(row, with_top_level=False)
    store.duty_periods[row["id"]] = row

    # Recompute pairing aggregates
    pairing_service.recompute_pairing_aggregates(pairing_id)

    # Validate internal overlap
    try:
        pairing_service.check_pairing_internal_overlap(pairing_id)
    except Exception:
        # Roll back this duty period
        del store.duty_periods[row["id"]]
        pairing_service.recompute_pairing_aggregates(pairing_id)
        raise

    return responses.success(serializers.duty_period(row), http_status=201)


# ---------------------- FlightLeg ----------------------

@bp.post("/duty-periods/<duty_id>/flight-legs")
@require_roles("CrewScheduler")
def create_flight_leg(duty_id):
    dp = store.duty_periods.get(duty_id)
    if dp is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Duty period not found.")

    pairing = store.pairings.get(dp["pairing_id"])
    if pairing is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Parent pairing not found.")
    if pairing["status"] != "DRAFT":
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Parent pairing must be DRAFT to add flight legs.")

    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "leg_sequence_no", "flight_number",
                              "dep_airport", "arr_airport", "dep_at", "arr_at")

    leg_seq = validators.require_int(body, "leg_sequence_no", min_value=1)
    flight_no = validators.require_string(body, "flight_number")
    dep_airport = validators.require_iata(body["dep_airport"], "dep_airport")
    arr_airport = validators.require_iata(body["arr_airport"], "arr_airport")
    dep_at = validators.parse_dt(body["dep_at"], "dep_at")
    arr_at = validators.parse_dt(body["arr_at"], "arr_at")
    leg_type = body.get("leg_type", "REVENUE")
    validators.require_leg_type(leg_type)

    if dep_at >= arr_at:
        raise_error("ERR_FLIGHT_LEG_INVALID", "dep_at must be before arr_at.")

    # Sequential overlap inside duty period: arr_at <= next dep_at
    existing = pairing_service.get_flight_legs_of_duty(duty_id)
    for fl in existing:
        if fl["leg_sequence_no"] == leg_seq:
            raise_error("ERR_VALIDATION_FAILED",
                        "leg_sequence_no must be unique within duty period.")

    # Insert ordering check
    proposed = list(existing) + [{
        "leg_sequence_no": leg_seq,
        "dep_at_dt": dep_at,
        "arr_at_dt": arr_at,
    }]

    def get_dep(o):
        return o.get("dep_at_dt") or parse_iso(o["dep_at"])

    def get_arr(o):
        return o.get("arr_at_dt") or parse_iso(o["arr_at"])

    proposed.sort(key=lambda r: r["leg_sequence_no"])
    for i in range(len(proposed) - 1):
        if get_arr(proposed[i]) > get_dep(proposed[i + 1]):
            raise_error("ERR_FLIGHT_LEG_INVALID",
                        "Sequential legs overlap inside duty period.")

    block_min = int((arr_at - dep_at).total_seconds() // 60)

    row = {
        "duty_period_id": duty_id,
        "leg_sequence_no": leg_seq,
        "flight_number": flight_no,
        "dep_airport": dep_airport,
        "arr_airport": arr_airport,
        "dep_at": format_iso(dep_at),
        "arr_at": format_iso(arr_at),
        "block_minutes": block_min,
        "leg_type": leg_type,
    }
    store.init_common(row, with_top_level=False)
    store.flight_legs[row["id"]] = row

    # Recompute duty period block_minutes and pairing totals
    pairing_service.recompute_duty_block_minutes(duty_id)
    pairing_service.recompute_pairing_aggregates(dp["pairing_id"])

    return responses.success(serializers.flight_leg(row), http_status=201)


# ---------------------- State transitions ----------------------

@bp.post("/pairings/<pairing_id>/publish")
@require_roles("CrewScheduler")
def publish_pairing(pairing_id):
    pairing = store.pairings.get(pairing_id)
    if pairing is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Pairing not found.")
    if pairing["status"] != "DRAFT":
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing must be DRAFT to publish.")

    dps = pairing_service.get_duty_periods_of(pairing_id)
    if not dps:
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing has no duty periods.")
    for dp in dps:
        legs = pairing_service.get_flight_legs_of_duty(dp["id"])
        if not legs:
            raise_error("ERR_PAIRING_INVALID_STATE",
                        "Duty period has no flight legs.")

    # Validate internal overlap
    pairing_service.check_pairing_internal_overlap(pairing_id)

    # Recompute totals
    pairing_service.recompute_pairing_aggregates(pairing_id)
    pairing["status"] = "PUBLISHED"
    store.touch(pairing)
    return responses.success(serializers.pairing(pairing))


@bp.post("/pairings/<pairing_id>/open-bidding")
@require_roles("CrewScheduler")
def open_bidding(pairing_id):
    from clock import get_now
    pairing = store.pairings.get(pairing_id)
    if pairing is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Pairing not found.")
    if pairing["status"] != "PUBLISHED":
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing must be PUBLISHED to open bidding.")
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "bid_window_id")
    bid_window_id = validators.require_string(body, "bid_window_id")

    # Check start_at >= now + 24h
    start_at = parse_iso(pairing["start_at"]) if pairing.get("start_at") else None
    if start_at is None:
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing has no start_at.")
    now = get_now()
    if (start_at - now).total_seconds() < 24 * 3600:
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing start_at must be at least 24h in the future.")

    pairing["status"] = "BIDDING_OPEN"
    pairing["bid_window_id"] = bid_window_id
    store.touch(pairing)
    return responses.success(serializers.pairing(pairing))


@bp.post("/pairings/<pairing_id>/cancel")
@require_roles("CrewScheduler")
def cancel_pairing(pairing_id):
    pairing = store.pairings.get(pairing_id)
    if pairing is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Pairing not found.")

    if pairing["status"] not in {"DRAFT", "PUBLISHED", "BIDDING_OPEN", "AWARDED"}:
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing cannot be cancelled in its current state.")

    prev_state = pairing["status"]

    # Side effects per state
    if prev_state == "BIDDING_OPEN":
        # All SUBMITTED bids -> NOT_AWARDED
        for b in store.bids.values():
            if b["pairing_id"] == pairing_id and b["status"] == "SUBMITTED":
                b["status"] = "NOT_AWARDED"
                store.touch(b)
        # No AWARDED bids in BIDDING_OPEN state (theoretically)
        for b in store.bids.values():
            if b["pairing_id"] == pairing_id and b["status"] == "AWARDED":
                b["status"] = "NOT_AWARDED"
                store.touch(b)

    if prev_state == "AWARDED":
        # Release awarded assignments
        for a in list(store.assignments.values()):
            if a["pairing_id"] == pairing_id and a["status"] == "SCHEDULED":
                a["status"] = "RELEASED"
                store.touch(a)
                # Debit counters
                crew = store.crew_members.get(a["crew_member_id"])
                if crew:
                    counters.debit_for_release(crew, pairing, a)

    pairing["status"] = "CANCELLED"
    store.touch(pairing)
    return responses.success(serializers.pairing(pairing))
