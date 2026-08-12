"""Specialized moves (PRD 3.8) and the client ledger listing (PRD 2.12)."""

from datetime import timedelta

from flask import Blueprint, jsonify, request

import calc
import serialize
from core import (
    DB, LOCK, MOVE_STATUSES, Ctx, by_created, fail, make_row, need_instrument,
    need_location, need_other, not_terminal, ok, page, parse_iso, touch,
)

bp = Blueprint("moves", __name__)

MOVE_TERMINAL = ("DELIVERED", "CANCELLED")
MOVE_EDGES = {
    ("DRAFT", "SCHEDULED"),
    ("SCHEDULED", "DISPATCHED"),
    ("DRAFT", "CANCELLED"),
    ("SCHEDULED", "CANCELLED"),
}


@bp.post("/move-jobs")
def create_move_job():
    with LOCK:
        ctx = Ctx(["MoveCoordinator", "ShopManager", "PlatformAdmin"])
        body = ctx.read_body(["instrument_id", "origin_location_id",
                              "destination_location_id", "distance_miles",
                              "scheduled_window_start_utc",
                              "scheduled_window_end_utc"])
        ctx.number("distance_miles", lo=0, lo_exclusive=True)
        start_dt = parse_iso(body["scheduled_window_start_utc"])
        end_dt = parse_iso(body["scheduled_window_end_utc"])
        if start_dt is None or end_dt is None:
            fail("ERR_VALIDATION", "The move window must carry ISO instants.")
        if not end_dt > start_dt:
            fail("ERR_VALUE_OUT_OF_RANGE",
                 "scheduled_window_end_utc must be strictly after the start.")

        origin = need_location(body["origin_location_id"])
        destination = need_location(body["destination_location_id"])
        instrument = need_instrument(body["instrument_id"])
        tech = None
        if body.get("move_technician_id") is not None:
            tech = need_other("technicians", body["move_technician_id"])

        if origin["client_id"] != instrument["client_id"] \
                or destination["client_id"] != instrument["client_id"]:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "A move location is owned by a different client.")

        crane_required = bool(body.get("crane_required") or False)
        climate_transport = bool(body.get("climate_controlled_transport") or False)
        flights_total, stair_cents = calc.move_stair_component(origin, destination)
        if instrument["instrument_class"] == "CONCERT_GRAND" \
                and flights_total >= calc.MOVE_CRANE_REQUIRED_MIN_FLIGHTS_CONCERT_GRAND \
                and not crane_required:
            fail("ERR_CRANE_REQUIRED",
                 "A concert grand over two flights must set crane_required.")

        widened_start = start_dt - timedelta(minutes=calc.MOVE_WINDOW_BUFFER_MINUTES)
        widened_end = end_dt + timedelta(minutes=calc.MOVE_WINDOW_BUFFER_MINUTES)
        for other in DB.move_jobs.values():
            if other["instrument_id"] != instrument["id"]:
                continue
            if other["status"] not in ("DRAFT", "SCHEDULED", "DISPATCHED",
                                       "IN_TRANSIT"):
                continue
            o_start = parse_iso(other["scheduled_window_start_utc"])
            o_end = parse_iso(other["scheduled_window_end_utc"])
            if o_start is None or o_end is None:
                continue
            if widened_start <= o_end and o_start <= widened_end:  # closed
                fail("ERR_MOVE_WINDOW_CONFLICT",
                     "The widened window collides with another move.")

        band, variant, distance_cents = calc.move_distance_component(
            body["distance_miles"])
        base_cents = calc.MOVE_BASE_CENTS[instrument["instrument_class"]]
        crane_cents = calc.MOVE_CRANE_CENTS if crane_required else 0
        climate_cents = calc.MOVE_CLIMATE_TRANSPORT_CENTS if climate_transport else 0
        row = make_row(
            instrument_id=instrument["id"],
            client_id=instrument["client_id"],
            origin_location_id=origin["id"],
            destination_location_id=destination["id"],
            move_technician_id=tech["id"] if tech else None,
            distance_miles=body["distance_miles"],
            distance_band=band,
            distance_variant=variant,
            stair_flights_total=flights_total,
            crane_required=crane_required,
            climate_controlled_transport=climate_transport,
            scheduled_window_start_utc=body["scheduled_window_start_utc"],
            scheduled_window_end_utc=body["scheduled_window_end_utc"],
            base_cents=base_cents,
            stair_cents=stair_cents,
            crane_cents=crane_cents,
            distance_cents=distance_cents,
            climate_cents=climate_cents,
            total_cents=(base_cents + stair_cents + crane_cents + distance_cents
                         + climate_cents),
            status="DRAFT",
        )
        DB.move_jobs[row["id"]] = row
        payload, status = ok(serialize.move_job(row), 201)
        return jsonify(payload), status


@bp.get("/move-jobs")
def list_move_jobs():
    with LOCK:
        ctx = Ctx(["MoveCoordinator", "ShopManager", "PlatformAdmin", "Client"])
        client_filter = request.args.get("client_id")
        if client_filter:
            ctx.scope_client(client_filter)
        status_f = ctx.enum_q("status", MOVE_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("move_jobs"))
        for key in ("instrument_id", "client_id", "origin_location_id",
                    "destination_location_id", "move_technician_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if ctx.is_client:
            rows = [r for r in rows if r["client_id"] == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.move_job)
        return jsonify(payload), http


@bp.get("/move-jobs/<jid>")
def read_move_job(jid):
    with LOCK:
        ctx = Ctx(["MoveCoordinator", "ShopManager", "PlatformAdmin", "Client"])
        existing = DB.move_jobs.get(jid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        row = need_other("move_jobs", jid)
        payload, status = ok(serialize.move_job(row))
        return jsonify(payload), status


@bp.post("/move-jobs/<jid>/status-transitions")
def move_job_transition(jid):
    with LOCK:
        ctx = Ctx(["MoveCoordinator", "ShopManager", "PlatformAdmin"])
        ctx.read_body(["to_status"])
        target = ctx.enum("to_status", MOVE_STATUSES)
        job = need_other("move_jobs", jid)
        current = job["status"]
        not_terminal(current, MOVE_TERMINAL)
        if (current, target) not in MOVE_EDGES:
            fail("ERR_INVALID_STATE",
                 "No move edge from %s to %s." % (current, target))

        instrument = DB.instruments.get(job["instrument_id"])
        if target == "SCHEDULED":
            if not job["move_technician_id"]:
                fail("ERR_INVALID_STATE", "The move has no crew lead.")
            needs_cert = job["crane_required"] or (
                instrument is not None
                and instrument["instrument_class"] == "CONCERT_GRAND")
            if needs_cert:
                tech = DB.technicians.get(job["move_technician_id"])
                if tech is None or not tech["move_certified"]:
                    fail("ERR_MOVE_CREW_NOT_CERTIFIED",
                         "The crew lead is not move certified.")
        if target == "DISPATCHED":
            if instrument is None or instrument["custody_status"] not in (
                    "AT_CLIENT_SITE", "IN_SHOP", "SHOWROOM_FLOOR"):
                fail("ERR_INVALID_STATE",
                     "The instrument's custody does not permit dispatch.")

        job["status"] = target
        touch(job)
        payload, status = ok(serialize.move_job(job))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Ledger listing
# ---------------------------------------------------------------------------

@bp.get("/ledger-entries")
def list_ledger_entries():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        client_filter = request.args.get("client_id")
        if client_filter:
            ctx.scope_client(client_filter)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("ledger_entries"))
        for key in ("client_id", "service_order_id", "warranty_claim_id",
                    "consignment_agreement_id", "reverses_entry_id",
                    "entry_type"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if ctx.is_client:
            rows = [r for r in rows if r["client_id"] == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.ledger_entry)
        return jsonify(payload), http


@bp.get("/ledger-entries/<eid>")
def read_ledger_entry(eid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        existing = DB.ledger_entries.get(eid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        row = need_other("ledger_entries", eid)
        payload, status = ok(serialize.ledger_entry(row))
        return jsonify(payload), status
