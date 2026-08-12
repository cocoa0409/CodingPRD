"""Clients, addresses and the climate record (PRD 3.1)."""

from flask import Blueprint, jsonify, request

import calc
import serialize
import services
from core import (
    CLIENT_STATUSES, CLIENT_TYPES, CLOCK, DB, LOCK, ZONES, Ctx, by_created,
    fail, make_append_row, make_row, need_client, need_location, not_terminal,
    ok, page, touch,
)

bp = Blueprint("clients", __name__)

CLIENT_TERMINAL = ("CLOSED",)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

@bp.post("/clients")
def create_client():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["display_name", "email", "phone", "home_zone_code"])
        ctx.enum("home_zone_code", ZONES)
        ctx.enum("client_type", CLIENT_TYPES)
        email = body["email"]
        if not isinstance(email, str) or "@" not in email:
            fail("ERR_VALIDATION", "email must contain an at-sign.")
        row = make_row(
            display_name=body["display_name"],
            email=email,
            phone=body["phone"],
            client_type=body.get("client_type") or "INDIVIDUAL",
            home_zone_code=body["home_zone_code"],
            account_credit_cents=0,
            status="ACTIVE",
        )
        DB.clients[row["id"]] = row
        payload, status = ok(serialize.client(row), 201)
        return jsonify(payload), status


@bp.get("/clients")
def list_clients():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        client_type = ctx.enum_q("client_type", CLIENT_TYPES)
        status_f = ctx.enum_q("status", CLIENT_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("clients"))
        if client_type:
            rows = [r for r in rows if r["client_type"] == client_type]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        payload, http = page(rows, limit, offset, serialize.client)
        return jsonify(payload), http


@bp.get("/clients/<cid>")
def read_client(cid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        existing = DB.clients.get(cid)
        if existing is not None:
            ctx.scope_client(existing["id"])
        row = need_client(cid)
        services.recompute_balance(row)
        payload, status = ok(serialize.client(row))
        return jsonify(payload), status


@bp.patch("/clients/<cid>")
def update_client(cid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body([])
        ctx.enum("home_zone_code", ZONES)
        ctx.enum("client_type", CLIENT_TYPES)
        target_status = ctx.enum("status", CLIENT_STATUSES)
        if "email" in body and body["email"] is not None:
            if not isinstance(body["email"], str) or "@" not in body["email"]:
                fail("ERR_VALIDATION", "email must contain an at-sign.")
        row = need_client(cid)

        if target_status is not None:
            not_terminal(row["status"], CLIENT_TERMINAL)
            edge = (row["status"], target_status)
            if edge not in (("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"),
                            ("ACTIVE", "CLOSED")):
                fail("ERR_INVALID_STATE",
                     "No client status edge from %s to %s." % edge)
            if target_status == "CLOSED":
                blocking = [o for o in DB.service_orders.values()
                            if o["client_id"] == row["id"]
                            and o["status"] in ("PENDING", "IN_PROGRESS", "ON_HOLD")]
                if blocking:
                    fail("ERR_INVALID_STATE",
                         "Client still has in-flight service orders.")

        for field in ("display_name", "email", "phone", "home_zone_code",
                      "client_type"):
            if field in body and body[field] is not None:
                row[field] = body[field]
        if target_status is not None:
            row["status"] = target_status
        touch(row)
        payload, status = ok(serialize.client(row))
        return jsonify(payload), status


@bp.post("/clients/<cid>/credit-adjustments")
def credit_adjustment(cid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["amount_cents"])
        amount = body["amount_cents"]
        if isinstance(amount, bool) or not isinstance(amount, int):
            fail("ERR_VALIDATION", "amount_cents must be an integer.")
        row = need_client(cid)
        entry = services.post_ledger(row["id"], "MANUAL_ADJUSTMENT", amount,
                                     memo=body.get("memo"))
        services.recompute_balance(row, bump=True)
        payload, status = ok(serialize.ledger_entry(entry), 201)
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@bp.post("/locations")
def create_location():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "MoveCoordinator"])
        body = ctx.read_body(["client_id", "label", "zone_code", "address_key",
                              "distance_miles_from_shop"])
        ctx.enum("zone_code", ZONES)
        ctx.number("stair_flights", lo=0, hi=calc.MAX_STAIR_FLIGHTS_PER_LOCATION,
                   integer=True)
        ctx.number("distance_miles_from_shop", lo=0)
        client = need_client(body["client_id"])
        row = make_row(
            client_id=client["id"],
            label=body["label"],
            zone_code=body["zone_code"],
            address_key=body["address_key"],
            stair_flights=body.get("stair_flights") if body.get("stair_flights") is not None else 0,
            has_service_elevator=bool(body.get("has_service_elevator") or False),
            climate_controlled=bool(body.get("climate_controlled") or False),
            distance_miles_from_shop=body["distance_miles_from_shop"],
            out_of_band_flag=False,
            readings_in_window=0,
            out_of_band_count=0,
        )
        DB.locations[row["id"]] = row
        payload, status = ok(serialize.location(row), 201)
        return jsonify(payload), status


@bp.get("/locations")
def list_locations():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "MoveCoordinator", "Client"])
        client_filter = request.args.get("client_id")
        if client_filter:
            ctx.scope_client(client_filter)
        zone = ctx.enum_q("zone_code", ZONES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("locations"))
        if client_filter:
            rows = [r for r in rows if r["client_id"] == client_filter]
        if zone:
            rows = [r for r in rows if r["zone_code"] == zone]
        if ctx.is_client:
            rows = [r for r in rows if r["client_id"] == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.location)
        return jsonify(payload), http


@bp.get("/locations/<lid>")
def read_location(lid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "MoveCoordinator", "Client",
                   "Technician"])
        existing = DB.locations.get(lid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        row = need_location(lid)
        payload, status = ok(serialize.location(row))
        return jsonify(payload), status


@bp.patch("/locations/<lid>")
def update_location(lid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "MoveCoordinator"])
        body = ctx.read_body([])
        ctx.enum("zone_code", ZONES)
        ctx.number("stair_flights", lo=0, hi=calc.MAX_STAIR_FLIGHTS_PER_LOCATION,
                   integer=True)
        ctx.number("distance_miles_from_shop", lo=0)
        row = need_location(lid)
        for field in ("label", "zone_code", "stair_flights",
                      "has_service_elevator", "climate_controlled",
                      "distance_miles_from_shop"):
            if field in body and body[field] is not None:
                row[field] = body[field]
        touch(row)
        payload, status = ok(serialize.location(row))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Climate readings
# ---------------------------------------------------------------------------

@bp.post("/climate-readings")
def create_climate_reading():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician"])
        body = ctx.read_body(["location_id", "recorded_at_utc",
                              "relative_humidity_pct", "temperature_f"])
        ctx.number("relative_humidity_pct", lo=0.0, hi=100.0)
        ctx.number("temperature_f", lo=-20.0, hi=140.0)
        location = need_location(body["location_id"])
        row = make_append_row(
            location_id=location["id"],
            recorded_at_utc=body["recorded_at_utc"],
            relative_humidity_pct=body["relative_humidity_pct"],
            temperature_f=body["temperature_f"],
            in_band=calc.reading_in_band(body["relative_humidity_pct"]),
        )
        DB.climate_readings[row["id"]] = row
        services.evaluate_location(location, bump=True)
        payload, status = ok(serialize.climate_reading(row), 201)
        return jsonify(payload), status


@bp.get("/locations/<lid>/climate-readings")
def list_climate_readings(lid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician"])
        limit, offset = ctx.pagination()
        need_location(lid)
        rows = by_created([r for r in DB.climate_readings.values()
                           if r["location_id"] == lid])
        payload, http = page(rows, limit, offset, serialize.climate_reading)
        return jsonify(payload), http
