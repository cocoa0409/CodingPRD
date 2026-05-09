"""Flight routes (incl. status events and archive)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db, gen_id, now_iso_z
from errors import (
    ERR_DUPLICATE_EVENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_api_error,
)
from middleware import require_roles
from response import list_response, success_response
from services.calculations import NINETY_DAYS_MS
from services.common import (
    append_audit,
    check_version,
    get_flight_or_404,
    get_insurer_or_404,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_field,
    require_int,
    sort_by_created_at,
)
from services.eligibility import recompute_claim_segments
from services.quorum import classify_cause, evaluate_quorum

bp = Blueprint("flights", __name__)


VALID_SOURCES = {"AIRLINE", "AIRPORT", "AVIATION_AUTHORITY"}
VALID_REPORTED = {"DELAYED", "CANCELLED", "DIVERTED", "RETURNED", "ON_TIME"}
VALID_CAUSES = {"WEATHER", "ATC", "SECURITY", "AIRLINE", "OTHER"}

TERMINAL_FLIGHT = {"LANDED", "CANCELLED", "DIVERTED", "RETURNED"}


def _serialize_flight(f: dict) -> dict:
    return dict(f)


def _serialize_event(e: dict) -> dict:
    return dict(e)


@bp.post("/insurers/<insurer_id>/flights")
@require_roles("ClaimsAdmin", "PolicyAdmin")
def create_flight(insurer_id: str):
    get_insurer_or_404(insurer_id)
    body = get_json_body()

    carrier_code = require_field(body, "carrier_code", type_=str)
    flight_number = require_field(body, "flight_number", type_=str)
    origin = require_field(body, "origin_airport", type_=str)
    destination = require_field(body, "destination_airport", type_=str)
    sched_dep = require_int(body, "scheduled_departure_epoch_ms", allow_negative=False)
    sched_arr = require_int(body, "scheduled_arrival_epoch_ms", allow_negative=False)
    if sched_arr <= sched_dep:
        raise_api_error(ERR_INVALID_REQUEST,
                        "scheduled_arrival_epoch_ms must be > scheduled_departure_epoch_ms.")

    # Uniqueness on (insurer_id, carrier_code, flight_number, scheduled_departure_epoch_ms)
    for f in db.flights.values():
        if (f.get("insurer_id") == insurer_id
            and f.get("carrier_code") == carrier_code
            and f.get("flight_number") == flight_number
            and f.get("scheduled_departure_epoch_ms") == sched_dep):
            raise_api_error(ERR_INVALID_STATE, "Flight already exists with that key.")

    flight = {
        "id": gen_id(),
        "insurer_id": insurer_id,
        "carrier_code": carrier_code,
        "flight_number": flight_number,
        "origin_airport": origin,
        "destination_airport": destination,
        "scheduled_departure_epoch_ms": sched_dep,
        "scheduled_arrival_epoch_ms": sched_arr,
        "actual_departure_epoch_ms": None,
        "actual_arrival_epoch_ms": None,
        "classified_cause": None,
        "status": "SCHEDULED",
        "archived_at_epoch_ms": None,
    }
    db.stamp_create(flight)
    db.flights[flight["id"]] = flight
    return jsonify(success_response(_serialize_flight(flight))), 201


@bp.get("/insurers/<insurer_id>/flights/<flight_id>")
@require_roles("Any")
def get_flight(insurer_id: str, flight_id: str):
    get_insurer_or_404(insurer_id)
    f = get_flight_or_404(insurer_id, flight_id)
    return jsonify(success_response(_serialize_flight(f))), 200


@bp.get("/insurers/<insurer_id>/flights")
@require_roles("Any")
def list_flights(insurer_id: str):
    get_insurer_or_404(insurer_id)
    limit, offset = parse_pagination()
    carrier_code = request.args.get("carrier_code")
    flight_number = request.args.get("flight_number")
    status = request.args.get("status")
    sched_after = request.args.get("scheduled_departure_after_epoch_ms")
    sched_after_int = None
    if sched_after is not None:
        try:
            sched_after_int = int(sched_after)
        except ValueError:
            raise_api_error(ERR_INVALID_REQUEST, "scheduled_departure_after_epoch_ms must be int.")

    flights = [f for f in db.flights.values() if f.get("insurer_id") == insurer_id]
    if carrier_code is not None:
        flights = [f for f in flights if f.get("carrier_code") == carrier_code]
    if flight_number is not None:
        flights = [f for f in flights if f.get("flight_number") == flight_number]
    if status is not None:
        flights = [f for f in flights if f.get("status") == status]
    if sched_after_int is not None:
        flights = [f for f in flights if f.get("scheduled_departure_epoch_ms") >= sched_after_int]
    flights = sort_by_created_at(flights)
    page, total = paginate(flights, limit, offset)
    return jsonify(list_response([_serialize_flight(f) for f in page], limit, offset, total)), 200


def _agreed_actuals(events: list[dict]) -> tuple[int | None, int | None]:
    """Pick representative actual departure/arrival across quorum events."""
    deps = [e["reported_actual_departure_epoch_ms"] for e in events
            if e.get("reported_actual_departure_epoch_ms") is not None]
    arrs = [e["reported_actual_arrival_epoch_ms"] for e in events
            if e.get("reported_actual_arrival_epoch_ms") is not None]
    # Use the latest reported timestamp (max). Aligns with "most recent feed".
    dep = max(deps) if deps else None
    arr = max(arrs) if arrs else None
    return dep, arr


def _terminal_status_from_reported(reported: str) -> str:
    """Map a reported_status that wins quorum to the resulting Flight terminal status."""
    if reported in ("ON_TIME", "DELAYED"):
        return "LANDED"
    return reported  # CANCELLED, DIVERTED, RETURNED


@bp.post("/insurers/<insurer_id>/flights/<flight_id>/events")
@require_roles("ClaimsAdmin", "system")
def ingest_event(insurer_id: str, flight_id: str):
    get_insurer_or_404(insurer_id)
    flight = get_flight_or_404(insurer_id, flight_id)
    body = get_json_body()

    source = require_field(body, "source", type_=str)
    if source not in VALID_SOURCES:
        raise_api_error(ERR_INVALID_REQUEST, "Invalid source.")
    source_event_id = require_field(body, "source_event_id", type_=str)
    reported_status = require_field(body, "reported_status", type_=str)
    if reported_status not in VALID_REPORTED:
        raise_api_error(ERR_INVALID_REQUEST, "Invalid reported_status.")
    rep_dep = optional_field(body, "reported_actual_departure_epoch_ms", default=None)
    rep_arr = optional_field(body, "reported_actual_arrival_epoch_ms", default=None)
    if rep_dep is not None and (not isinstance(rep_dep, int) or isinstance(rep_dep, bool)):
        raise_api_error(ERR_INVALID_REQUEST, "reported_actual_departure_epoch_ms must be int.")
    if rep_arr is not None and (not isinstance(rep_arr, int) or isinstance(rep_arr, bool)):
        raise_api_error(ERR_INVALID_REQUEST, "reported_actual_arrival_epoch_ms must be int.")
    rep_cause = optional_field(body, "reported_cause", default=None, type_=str)
    if rep_cause is not None and rep_cause not in VALID_CAUSES:
        raise_api_error(ERR_INVALID_REQUEST, "Invalid reported_cause.")
    report_epoch_ms = require_int(body, "report_epoch_ms", allow_negative=False)

    # Idempotency: (insurer_id, source, source_event_id) must be unique
    for ev in db.flight_status_events.values():
        if (ev.get("insurer_id") == insurer_id
            and ev.get("source") == source
            and ev.get("source_event_id") == source_event_id):
            raise_api_error(ERR_DUPLICATE_EVENT, "Duplicate event.")

    insurer = db.insurers[insurer_id]
    ingested_epoch_ms = insurer["now_epoch_ms"]
    event = {
        "id": gen_id(),
        "flight_id": flight_id,
        "insurer_id": insurer_id,
        "source": source,
        "source_event_id": source_event_id,
        "reported_status": reported_status,
        "reported_actual_departure_epoch_ms": rep_dep,
        "reported_actual_arrival_epoch_ms": rep_arr,
        "reported_cause": rep_cause,
        "report_epoch_ms": report_epoch_ms,
        "ingested_epoch_ms": ingested_epoch_ms,
        "created_at": now_iso_z(),
    }
    db.flight_status_events[event["id"]] = event

    # Quorum evaluation only if flight not terminal
    if flight["status"] in ("SCHEDULED", "ACTIVE"):
        winner_status, winner_events = evaluate_quorum(flight)
        if winner_status is not None:
            new_status = _terminal_status_from_reported(winner_status)
            prev_status = flight["status"]
            flight["status"] = new_status

            agreed_dep, agreed_arr = _agreed_actuals(winner_events)
            if new_status == "CANCELLED":
                flight["actual_departure_epoch_ms"] = None
                flight["actual_arrival_epoch_ms"] = None
            elif new_status == "DIVERTED":
                flight["actual_departure_epoch_ms"] = agreed_dep
                flight["actual_arrival_epoch_ms"] = agreed_arr
            elif new_status == "RETURNED":
                flight["actual_departure_epoch_ms"] = agreed_dep
                flight["actual_arrival_epoch_ms"] = agreed_arr
            else:  # LANDED
                flight["actual_departure_epoch_ms"] = agreed_dep
                flight["actual_arrival_epoch_ms"] = agreed_arr

            flight["classified_cause"] = classify_cause(winner_events)
            db.stamp_update(flight)
            append_audit(insurer_id, "FLIGHT", flight["id"], "STATUS_CHANGE",
                         {"from": prev_status, "to": new_status,
                          "classified_cause": flight["classified_cause"]})

            # Recompute eligibility for any claim referencing tickets bound to this flight
            for claim in db.claims.values():
                if claim.get("insurer_id") != insurer_id:
                    continue
                touches_flight = False
                for seg_id in claim.get("segment_ids", []):
                    seg = db.claim_segments.get(seg_id)
                    if seg and seg.get("flight_id") == flight_id:
                        touches_flight = True
                        break
                if touches_flight:
                    recompute_claim_segments(claim)

    return jsonify(success_response(_serialize_event(event))), 201


@bp.post("/insurers/<insurer_id>/flights/<flight_id>/archive")
@require_roles("ClaimsAdmin")
def archive_flight(insurer_id: str, flight_id: str):
    get_insurer_or_404(insurer_id)
    flight = get_flight_or_404(insurer_id, flight_id)
    body = get_json_body()
    check_version(body, flight)

    if flight["status"] not in TERMINAL_FLIGHT:
        raise_api_error(ERR_INVALID_STATE, f"Flight in status {flight['status']} cannot be archived.")

    # Precondition: no claim in non-terminal review_status references this flight
    for c in db.claims.values():
        if c.get("insurer_id") != insurer_id:
            continue
        for seg_id in c.get("segment_ids", []):
            seg = db.claim_segments.get(seg_id)
            if seg and seg.get("flight_id") == flight_id:
                if c.get("review_status") in ("PENDING_MATCH", "MATCHED", "UNDER_REVIEW", "APPROVED"):
                    raise_api_error(ERR_INVALID_STATE,
                                    "Flight has non-terminal claims referencing it.")
                break

    insurer = db.insurers[insurer_id]
    prev = flight["status"]
    flight["status"] = "ARCHIVED"
    flight["archived_at_epoch_ms"] = insurer["now_epoch_ms"]
    db.stamp_update(flight)
    append_audit(insurer_id, "FLIGHT", flight["id"], "STATUS_CHANGE",
                 {"from": prev, "to": "ARCHIVED"})
    return jsonify(success_response(_serialize_flight(flight))), 200
