"""Dealer contract endpoints."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import (
    err_not_found,
    err_referenced_not_found,
    err_invalid_request,
    err_invalid_state,
    err_window_invalid,
    err_dealer_mismatch,
    err_stale_dealer_version,
    err_dealer_suspended,
)

bp = Blueprint("dealer_contracts", __name__)

READ_ROLES = ["CreditManager", "DealerUser", "SupplyPlanner"]
WRITE_ROLES = ["CreditManager"]


@bp.route("/dealer-contracts", methods=["POST"])
def create_dealer_contract():
    caller = mw.authenticate()
    mw.authorize(caller, WRITE_ROLES)
    body = mw.get_json_body(required=True)
    dealer_id = mw.req_string(body, "dealer_id")
    terminal_id = mw.req_string(body, "terminal_id")
    pricing_mode = mw.req_enum(body, "pricing_mode", {"INDEX", "FIXED"})
    volume_committed_gal = mw.req_int(body, "volume_committed_gal")
    window_start = mw.req_date(body, "window_start")
    window_end = mw.req_date(body, "window_end")

    fixed_price = None
    if pricing_mode == "FIXED":
        if body.get("fixed_price_mc_per_gal") is None:
            raise err_invalid_request("fixed_price_mc_per_gal is required when pricing_mode == FIXED")
        fixed_price = mw.req_int(body, "fixed_price_mc_per_gal")
        if fixed_price <= 0:
            raise err_invalid_request("fixed_price_mc_per_gal must be > 0")
    else:
        if body.get("fixed_price_mc_per_gal") is not None:
            fixed_price = mw.req_int(body, "fixed_price_mc_per_gal")

    # body FKs (priority 5)
    if dealer_id not in db.dealers:
        raise err_referenced_not_found("dealer_id does not resolve")
    if terminal_id not in db.terminals:
        raise err_referenced_not_found("terminal_id does not resolve")

    # business (priority 10)
    if window_end < window_start:
        raise err_window_invalid("window_end < window_start")
    if volume_committed_gal <= 0:
        raise err_invalid_request("volume_committed_gal must be > 0")

    now = svc.stamp_now()
    c = {
        "id": db.new_id(),
        "dealer_id": dealer_id,
        "terminal_id": terminal_id,
        "pricing_mode": pricing_mode,
        "fixed_price_mc_per_gal": fixed_price,
        "volume_committed_gal": volume_committed_gal,
        "volume_drawn_gal": 0,
        "window_start": window_start,
        "window_end": window_end,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.dealer_contracts[c["id"]] = c
    return resp.created(ser.serialize_dealer_contract(c))


@bp.route("/dealer-contracts/<cid>", methods=["GET"])
def get_dealer_contract(cid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    c = db.dealer_contracts.get(cid)
    if c is None:
        raise err_not_found()
    if caller["role"] == "DealerUser" and c["dealer_id"] != caller["user_id"]:
        raise err_dealer_mismatch()
    return resp.ok(ser.serialize_dealer_contract(c))


@bp.route("/dealer-contracts", methods=["GET"])
def list_dealer_contracts():
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    limit, offset = mw.pagination_params()
    dealer_id = mw.opt_query_string("dealer_id")
    terminal_id = mw.opt_query_string("terminal_id")
    status = mw.opt_query_enum("status", {"DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED", "CANCELLED"})
    if caller["role"] == "DealerUser":
        if dealer_id is not None and dealer_id != caller["user_id"]:
            raise err_dealer_mismatch()
        dealer_id = caller["user_id"]
    items = list(db.dealer_contracts.values())
    if dealer_id is not None:
        items = [c for c in items if c["dealer_id"] == dealer_id]
    if terminal_id is not None:
        items = [c for c in items if c["terminal_id"] == terminal_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_dealer_contract(c) for c in page], limit, offset, total)


@bp.route("/dealer-contracts/<cid>/activate", methods=["POST"])
def activate_dealer_contract(cid):
    caller = mw.authenticate()
    mw.authorize(caller, WRITE_ROLES)
    c = db.dealer_contracts.get(cid)
    if c is None:
        raise err_not_found()
    body = mw.get_json_body(required=True)
    expected_dealer_version = mw.req_int(body, "expected_dealer_version")
    dealer = db.dealers[c["dealer_id"]]

    # OCC (priority 6) precedes transition legality (7) and cross-entity state (8)
    if expected_dealer_version != dealer["version"]:
        raise err_stale_dealer_version()
    if c["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT dealer contract can be activated")
    committed = ser.committed_exposure(dealer)
    if ser.credit_status_of(committed, dealer["credit_limit_cents"]) == "SUSPENDED":
        raise err_dealer_suspended()

    # Supersede any other ACTIVE contract with same dealer_id + terminal_id and
    # overlapping [window_start, window_end]
    for other in list(db.dealer_contracts.values()):
        if other["id"] == c["id"]:
            continue
        if other["dealer_id"] != c["dealer_id"] or other["terminal_id"] != c["terminal_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if c["window_start"] <= other["window_end"] and other["window_start"] <= c["window_end"]:
            other["status"] = "SUPERSEDED"
            svc.touch(other)
            svc.cascade_cancel_contract_orders(other)

    c["status"] = "ACTIVE"
    svc.touch(c)
    svc.touch(dealer)  # activation supersede bookkeeping bumps Dealer.version
    return resp.ok(ser.serialize_dealer_contract(c))


@bp.route("/dealer-contracts/<cid>/cancel", methods=["POST"])
def cancel_dealer_contract(cid):
    caller = mw.authenticate()
    mw.authorize(caller, WRITE_ROLES)
    c = db.dealer_contracts.get(cid)
    if c is None:
        raise err_not_found()
    if c["status"] not in ("DRAFT", "ACTIVE"):
        raise err_invalid_state("Dealer contract cannot be cancelled from its current state")
    c["status"] = "CANCELLED"
    svc.touch(c)
    svc.cascade_cancel_contract_orders(c)
    return resp.ok(ser.serialize_dealer_contract(c))
