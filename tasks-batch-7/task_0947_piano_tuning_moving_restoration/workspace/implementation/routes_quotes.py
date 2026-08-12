"""Quoting the work (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint, jsonify, request

import calc
import serialize
import services
from core import (
    CLOCK, DB, LOCK, QUOTE_STATUSES, SERVICE_TYPES, Ctx, by_created, fail,
    make_row, need_instrument, need_quote, not_terminal, ok, page, parse_iso,
    touch,
)

bp = Blueprint("quotes", __name__)

QUOTE_TERMINAL = ("APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED")
# PRD 3.5 declares the EXPIRED -> SUPERSEDED edge explicitly, so the terminal
# gate of rung 21 cannot include EXPIRED on the re-issue operation without
# making that edge unreachable.
QUOTE_TERMINAL_FOR_REISSUE = ("APPROVED", "DECLINED", "SUPERSEDED")

SERVICE_LADDER = {
    "VOICE": ("SERVICEABLE", "NEEDS_VOICING", "RESTORED"),
    "REGULATE": ("SERVICEABLE", "NEEDS_REGULATION", "NEEDS_VOICING", "RESTORED"),
}


def _check_service_ladder(service_type, condition_status):
    if service_type in SERVICE_LADDER:
        if condition_status not in SERVICE_LADDER[service_type]:
            fail("ERR_SERVICE_PREREQUISITE_NOT_MET",
                 "A %s quote is not permitted from %s."
                 % (service_type, condition_status))
    elif service_type in ("TUNE", "PITCH_RAISE"):
        if condition_status == "REBUILD_REQUIRED":
            fail("ERR_SERVICE_PREREQUISITE_NOT_MET",
                 "A %s quote is not permitted from REBUILD_REQUIRED."
                 % service_type)


def _price_quote(instrument, service_type, client):
    location = DB.locations.get(instrument["current_location_id"])
    zone = location["zone_code"] if location else "ZONE_A"
    priced = calc.quote_pricing(service_type, instrument["instrument_class"],
                                instrument["pitch_raise_tier"],
                                client["client_type"], zone)
    deposit_cents, deposit_variant = calc.deposit_required(
        priced["total_cents"], service_type, client["client_type"])
    priced["deposit_required_cents"] = deposit_cents
    priced["deposit_variant"] = deposit_variant
    return priced


@bp.post("/quotes")
def create_quote():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["instrument_id", "service_type",
                              "expected_instrument_version"])
        service_type = ctx.enum("service_type", SERVICE_TYPES)
        instrument = need_instrument(body["instrument_id"])
        client = DB.clients.get(instrument["client_id"])
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        if body["expected_instrument_version"] != instrument["version"]:
            fail("ERR_STALE_INSTRUMENT_VERSION",
                 "expected_instrument_version does not match.")
        _check_service_ladder(service_type, instrument["condition_status"])

        priced = _price_quote(instrument, service_type, client)
        row = make_row(
            instrument_id=instrument["id"],
            client_id=instrument["client_id"],
            supersedes_quote_id=None,
            service_type=service_type,
            version_number=1,
            issued_at=None,
            expires_at=None,
            status="DRAFT",
            **priced
        )
        DB.quotes[row["id"]] = row
        touch(instrument)
        payload, status = ok(serialize.quote(row), 201)
        return jsonify(payload), status


@bp.get("/quotes")
def list_quotes():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        client_filter = request.args.get("client_id")
        if client_filter:
            ctx.scope_client(client_filter)
        status_f = ctx.enum_q("status", QUOTE_STATUSES)
        service_type = ctx.enum_q("service_type", SERVICE_TYPES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("quotes"))
        for key in ("instrument_id", "client_id", "supersedes_quote_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if service_type:
            rows = [r for r in rows if r["service_type"] == service_type]
        if ctx.is_client:
            rows = [r for r in rows if r["client_id"] == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.quote)
        return jsonify(payload), http


@bp.get("/quotes/<qid>")
def read_quote(qid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        existing = DB.quotes.get(qid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        row = need_quote(qid)
        payload, status = ok(serialize.quote(row))
        return jsonify(payload), status


@bp.post("/quotes/<qid>/issue")
def issue_quote(qid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        ctx.read_body([])
        quote = need_quote(qid)
        client = DB.clients.get(quote["client_id"])
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        not_terminal(quote["status"], QUOTE_TERMINAL)
        if quote["status"] != "DRAFT":
            fail("ERR_INVALID_STATE",
                 "No quote edge from %s to ISSUED." % quote["status"])
        clash = [q for q in DB.quotes.values()
                 if q["id"] != quote["id"]
                 and q["instrument_id"] == quote["instrument_id"]
                 and q["service_type"] == quote["service_type"]
                 and q["status"] == "ISSUED"]
        if clash:
            fail("ERR_DUPLICATE_ACTIVE_QUOTE",
                 "Another quote for this instrument and service type is ISSUED.")
        quote["status"] = "ISSUED"
        quote["issued_at"] = CLOCK.stamp()
        quote["expires_at"] = CLOCK.stamp(
            CLOCK.dt + timedelta(days=calc.QUOTE_VALID_DAYS))
        touch(quote)
        payload, status = ok(serialize.quote(quote))
        return jsonify(payload), status


@bp.post("/quotes/<qid>/approve")
def approve_quote(qid):
    with LOCK:
        ctx = Ctx(["Client", "PlatformAdmin"])
        existing = DB.quotes.get(qid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        ctx.read_body([])
        quote = need_quote(qid)
        client = DB.clients.get(quote["client_id"])
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        not_terminal(quote["status"], QUOTE_TERMINAL)
        if quote["status"] != "ISSUED":
            fail("ERR_INVALID_STATE",
                 "No quote edge from %s to APPROVED." % quote["status"])
        expires = parse_iso(quote["expires_at"]) if quote["expires_at"] else None
        if expires is not None and not CLOCK.dt < expires:
            fail("ERR_QUOTE_EXPIRED", "The quote has expired.")

        quote["status"] = "APPROVED"
        touch(quote)
        if quote["service_type"] == "REBUILD":
            instrument = DB.instruments.get(quote["instrument_id"])
            if instrument is not None and instrument["condition_status"] in (
                    "SERVICEABLE", "NEEDS_REGULATION"):
                instrument["condition_status"] = "REBUILD_REQUIRED"
                touch(instrument)
            services.cascade_b(quote["instrument_id"])
        payload, status = ok(serialize.quote(quote))
        return jsonify(payload), status


@bp.post("/quotes/<qid>/decline")
def decline_quote(qid):
    with LOCK:
        ctx = Ctx(["Client", "PlatformAdmin"])
        existing = DB.quotes.get(qid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        ctx.read_body([])
        quote = need_quote(qid)
        not_terminal(quote["status"], QUOTE_TERMINAL)
        if quote["status"] != "ISSUED":
            fail("ERR_INVALID_STATE",
                 "No quote edge from %s to DECLINED." % quote["status"])
        quote["status"] = "DECLINED"
        touch(quote)
        payload, status = ok(serialize.quote(quote))
        return jsonify(payload), status


@bp.post("/quotes/<qid>/reissue")
def reissue_quote(qid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["expected_instrument_version"])
        quote = need_quote(qid)
        instrument = need_instrument(quote["instrument_id"])
        not_terminal(quote["status"], QUOTE_TERMINAL_FOR_REISSUE)
        if quote["status"] not in ("ISSUED", "EXPIRED"):
            fail("ERR_INVALID_STATE",
                 "No quote edge from %s to SUPERSEDED." % quote["status"])
        if body["expected_instrument_version"] != instrument["version"]:
            fail("ERR_STALE_INSTRUMENT_VERSION",
                 "expected_instrument_version does not match.")
        _check_service_ladder(quote["service_type"],
                              instrument["condition_status"])

        client = DB.clients.get(instrument["client_id"])
        priced = _price_quote(instrument, quote["service_type"], client)
        replacement = make_row(
            instrument_id=instrument["id"],
            client_id=instrument["client_id"],
            supersedes_quote_id=quote["id"],
            service_type=quote["service_type"],
            version_number=quote["version_number"] + 1,
            issued_at=None,
            expires_at=None,
            status="DRAFT",
            **priced
        )
        DB.quotes[replacement["id"]] = replacement
        quote["status"] = "SUPERSEDED"
        touch(quote)
        touch(instrument)
        payload, status = ok(serialize.quote(replacement), 201)
        return jsonify(payload), status
