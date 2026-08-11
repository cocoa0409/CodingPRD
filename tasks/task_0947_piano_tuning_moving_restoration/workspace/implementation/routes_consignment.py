"""Consignment, the showroom floor and the sale (PRD 3.10)."""

from datetime import timedelta

from flask import Blueprint, jsonify, request

import calc
import serialize
import services
from core import (
    CLOCK, CONSIGNMENT_STATUSES, DB, LOCK, Ctx, by_created, date_str, fail,
    make_row, need_client, need_instrument, need_other, not_terminal, ok, page,
    parse_iso, touch,
)

bp = Blueprint("consignment", __name__)

CONSIGNMENT_TERMINAL = ("SOLD", "EXPIRED", "WITHDRAWN")


@bp.post("/consignment-agreements")
def create_agreement():
    with LOCK:
        ctx = Ctx(["ShowroomAgent", "ShopManager", "PlatformAdmin"], sod=True)
        body = ctx.read_body(["instrument_id", "consignor_client_id",
                              "reserve_price_cents",
                              "expected_instrument_version"])
        ctx.number("reserve_price_cents", lo=calc.CONSIGNMENT_MIN_RESERVE_CENTS,
                   integer=True)
        consignor = need_client(body["consignor_client_id"])
        instrument = need_instrument(body["instrument_id"])
        if instrument["client_id"] != consignor["id"]:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "The consignor must be the instrument's owner.")
        if body["expected_instrument_version"] != instrument["version"]:
            fail("ERR_STALE_INSTRUMENT_VERSION",
                 "expected_instrument_version does not match.")
        row = make_row(
            instrument_id=instrument["id"],
            consignor_client_id=consignor["id"],
            buyer_client_id=None,
            reserve_price_cents=body["reserve_price_cents"],
            advanced_restoration_cents=0,
            start_date=None,
            expires_at=None,
            sale_price_cents=None,
            split_variant=None,
            advance_recovered_cents=0,
            shop_commission_cents=0,
            consignor_payout_cents=0,
            created_by_user_id=ctx.user_id,
            status="DRAFT",
        )
        DB.consignment_agreements[row["id"]] = row
        touch(instrument)
        payload, status = ok(serialize.consignment_agreement(row), 201)
        return jsonify(payload), status


@bp.get("/consignment-agreements")
def list_agreements():
    with LOCK:
        ctx = Ctx(["ShowroomAgent", "ShopManager", "PlatformAdmin", "Client"])
        for key in ("consignor_client_id", "buyer_client_id"):
            value = request.args.get(key)
            if value:
                ctx.scope_client(value)
        status_f = ctx.enum_q("status", CONSIGNMENT_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("consignment_agreements"))
        for key in ("instrument_id", "consignor_client_id", "buyer_client_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if ctx.is_client:
            rows = [r for r in rows
                    if ctx.user_id in (r["consignor_client_id"],
                                       r["buyer_client_id"])]
        payload, http = page(rows, limit, offset, serialize.consignment_agreement)
        return jsonify(payload), http


@bp.get("/consignment-agreements/<aid>")
def read_agreement(aid):
    with LOCK:
        ctx = Ctx(["ShowroomAgent", "ShopManager", "PlatformAdmin", "Client"])
        existing = DB.consignment_agreements.get(aid)
        if existing is not None:
            ctx.scope_client(existing["consignor_client_id"],
                             existing["buyer_client_id"])
        row = need_other("consignment_agreements", aid)
        payload, status = ok(serialize.consignment_agreement(row))
        return jsonify(payload), status


@bp.post("/consignment-agreements/<aid>/activate")
def activate_agreement(aid):
    with LOCK:
        ctx = Ctx(["ShowroomAgent", "ShopManager", "PlatformAdmin"])
        ctx.read_body([])
        agreement = need_other("consignment_agreements", aid)
        instrument = DB.instruments.get(agreement["instrument_id"])
        not_terminal(agreement["status"], CONSIGNMENT_TERMINAL)
        if instrument is None or instrument["custody_status"] != "IN_SHOP":
            fail("ERR_INVALID_CUSTODY_STATE",
                 "The instrument must be IN_SHOP to activate a consignment.")
        if agreement["status"] != "DRAFT":
            fail("ERR_INVALID_STATE",
                 "No agreement edge from %s to ACTIVE." % agreement["status"])
        agreement["status"] = "ACTIVE"
        agreement["start_date"] = date_str(CLOCK.date)
        agreement["expires_at"] = CLOCK.stamp(
            CLOCK.dt + timedelta(days=calc.CONSIGNMENT_TERM_DAYS))
        agreement["advanced_restoration_cents"] = sum(
            o["contract_total_cents"] for o in DB.service_orders.values()
            if o["instrument_id"] == instrument["id"]
            and o["service_type"] == "REBUILD" and o["status"] == "COMPLETED")
        touch(agreement)
        payload, status = ok(serialize.consignment_agreement(agreement))
        return jsonify(payload), status


@bp.post("/consignment-agreements/<aid>/list-showroom")
def list_showroom(aid):
    with LOCK:
        ctx = Ctx(["ShowroomAgent", "ShopManager", "PlatformAdmin"])
        ctx.read_body([])
        agreement = need_other("consignment_agreements", aid)
        instrument = DB.instruments.get(agreement["instrument_id"])
        not_terminal(agreement["status"], CONSIGNMENT_TERMINAL)
        if instrument is None or instrument["custody_status"] != "IN_SHOP":
            fail("ERR_INVALID_CUSTODY_STATE",
                 "The instrument must be IN_SHOP to reach the showroom floor.")
        if agreement["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE",
                 "No agreement edge from %s to LISTED." % agreement["status"])
        expires = parse_iso(agreement["expires_at"]) if agreement["expires_at"] else None
        if expires is not None and not CLOCK.dt < expires:
            fail("ERR_CONSIGNMENT_EXPIRED", "The agreement has expired.")
        agreement["status"] = "LISTED"
        touch(agreement)
        instrument["custody_status"] = "SHOWROOM_FLOOR"
        instrument["consignment_agreement_id"] = agreement["id"]
        touch(instrument)
        payload, status = ok(serialize.consignment_agreement(agreement))
        return jsonify(payload), status


@bp.post("/consignment-agreements/<aid>/record-sale")
def record_sale(aid):
    with LOCK:
        ctx = Ctx(["ShowroomAgent", "ShopManager", "PlatformAdmin"], sod=True)
        body = ctx.read_body(["buyer_client_id", "sale_price_cents"])
        ctx.number("sale_price_cents", lo=0, lo_exclusive=True, integer=True)
        buyer = need_client(body["buyer_client_id"])
        agreement = need_other("consignment_agreements", aid)
        if buyer["id"] == agreement["consignor_client_id"]:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "The buyer must differ from the consignor.")
        not_terminal(agreement["status"], CONSIGNMENT_TERMINAL)
        if agreement["status"] != "LISTED":
            fail("ERR_INVALID_STATE",
                 "No agreement edge from %s to SOLD." % agreement["status"])
        if ctx.user_id == agreement["created_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The creator of an agreement may not record its sale.")
        expires = parse_iso(agreement["expires_at"]) if agreement["expires_at"] else None
        if expires is not None and not CLOCK.dt < expires:
            fail("ERR_CONSIGNMENT_EXPIRED", "The agreement has expired.")
        floor_cents = calc.consignment_sale_floor(agreement["reserve_price_cents"])
        sale_price = body["sale_price_cents"]
        if sale_price < floor_cents:
            fail("ERR_SALE_BELOW_FLOOR", "The sale price is below the floor.")

        split = calc.consignment_proceeds_split(
            agreement["advanced_restoration_cents"],
            agreement["reserve_price_cents"], sale_price)
        agreement["status"] = "SOLD"
        agreement["buyer_client_id"] = buyer["id"]
        agreement["sale_price_cents"] = sale_price
        agreement["split_variant"] = split["split_variant"]
        agreement["advance_recovered_cents"] = split["advance_recovered_cents"]
        agreement["shop_commission_cents"] = split["shop_commission_cents"]
        agreement["consignor_payout_cents"] = split["consignor_payout_cents"]
        touch(agreement)

        consignor_id = agreement["consignor_client_id"]
        services.post_ledger(consignor_id, "CONSIGNMENT_PROCEEDS",
                             split["consignor_payout_cents"],
                             consignment_agreement_id=agreement["id"])
        services.recompute_balance_for(consignor_id)

        instrument = DB.instruments.get(agreement["instrument_id"])
        if instrument is not None:
            services.cascade_c(instrument, buyer["id"], consignor_id, CLOCK.date)
        payload, status = ok(serialize.consignment_agreement(agreement))
        return jsonify(payload), status


@bp.post("/consignment-agreements/<aid>/withdraw")
def withdraw_agreement(aid):
    with LOCK:
        ctx = Ctx(["ShowroomAgent", "ShopManager", "PlatformAdmin"])
        ctx.read_body([])
        agreement = need_other("consignment_agreements", aid)
        not_terminal(agreement["status"], CONSIGNMENT_TERMINAL)
        if agreement["status"] not in ("ACTIVE", "LISTED"):
            fail("ERR_INVALID_STATE",
                 "No agreement edge from %s to WITHDRAWN." % agreement["status"])
        agreement["status"] = "WITHDRAWN"
        touch(agreement)
        services.detach_instrument(agreement)
        payload, status = ok(serialize.consignment_agreement(agreement))
        return jsonify(payload), status
