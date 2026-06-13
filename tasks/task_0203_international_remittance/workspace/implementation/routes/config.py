"""Config & admin endpoints: corridors, fx-rates, sanctions-list, clock.

All write/config ops are PlatformAdmin-exclusive (SCAFFOLD §1.7).
"""
from flask import Blueprint

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import (stamp_create, touch, public, get_json,
                             paginate, require_fields, now_iso)
from services.clock import expire_quotes, parse_iso

bp = Blueprint("config", __name__)

PAYOUT_METHODS = {"BANK", "CASH_PICKUP", "WALLET"}
ALL_ROLES = {"PlatformAdmin", "RemittanceAgent", "ComplianceOfficer", "PayoutOperator"}


# ---------------------------------------------------------------------------
# Corridors
# ---------------------------------------------------------------------------
@bp.route("/corridors", methods=["POST"])
def create_corridor():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json()
    require_fields(body, ["name", "send_country", "receive_country", "send_currency",
                          "receive_currency", "enabled_payout_methods", "fx_margin_bps",
                          "fee_flat_minor", "fee_pct_bps", "fee_tier_threshold_minor",
                          "fee_pct_tier2_bps", "per_transfer_max_minor",
                          "rolling_window_cap_minor"])
    methods = body["enabled_payout_methods"]
    if not isinstance(methods, list) or not methods or \
            any(m not in PAYOUT_METHODS for m in methods):
        raise err("ERR_INVALID_REQUEST", "enabled_payout_methods must be a non-empty "
                                         "subset of BANK/CASH_PICKUP/WALLET")

    corridor = {
        "name": body["name"],
        "send_country": body["send_country"],
        "receive_country": body["receive_country"],
        "send_currency": body["send_currency"],
        "receive_currency": body["receive_currency"],
        "enabled_payout_methods": list(methods),
        "fx_margin_bps": body["fx_margin_bps"],
        "fee_flat_minor": body["fee_flat_minor"],
        "fee_pct_bps": body["fee_pct_bps"],
        "fee_tier_threshold_minor": body["fee_tier_threshold_minor"],
        "fee_pct_tier2_bps": body["fee_pct_tier2_bps"],
        "per_transfer_max_minor": body["per_transfer_max_minor"],
        "rolling_window_hours": body.get("rolling_window_hours", 24),
        "rolling_window_cap_minor": body["rolling_window_cap_minor"],
        "rate_lock_ttl_seconds": body.get("rate_lock_ttl_seconds", 1800),
        "reserved_minor": 0,
        "status": "ACTIVE",
    }
    stamp_create(corridor)
    db.corridors[corridor["id"]] = corridor
    return success(public(corridor), 201)


@bp.route("/corridors/<corridor_id>", methods=["GET"])
def get_corridor(corridor_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    corridor = db.corridors.get(corridor_id)
    if corridor is None:
        raise err("ERR_NOT_FOUND", "Corridor not found")
    return success(public(corridor), 200)


@bp.route("/corridors", methods=["GET"])
def list_corridors():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    from flask import request
    items = list(db.corridors.values())
    sc = request.args.get("send_country")
    rc = request.args.get("receive_country")
    st = request.args.get("status")
    if sc is not None:
        items = [c for c in items if c["send_country"] == sc]
    if rc is not None:
        items = [c for c in items if c["receive_country"] == rc]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, meta = paginate(items)
    return success([public(c) for c in page], 200, pagination=meta)


@bp.route("/corridors/<corridor_id>/suspend", methods=["POST"])
def suspend_corridor(corridor_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    corridor = db.corridors.get(corridor_id)
    if corridor is None:
        raise err("ERR_NOT_FOUND", "Corridor not found")
    corridor["status"] = "SUSPENDED"
    touch(corridor)
    return success(public(corridor), 200)


# ---------------------------------------------------------------------------
# FxRate (immutable audit record)
# ---------------------------------------------------------------------------
@bp.route("/fx-rates", methods=["POST"])
def create_fx_rate():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json()
    require_fields(body, ["corridor_id", "mid_rate_micro", "effective_at"])
    if body["corridor_id"] not in db.corridors:
        raise err("ERR_NOT_FOUND", "Corridor not found")
    fx = {
        "corridor_id": body["corridor_id"],
        "mid_rate_micro": body["mid_rate_micro"],
        "effective_at": body["effective_at"],
    }
    stamp_create(fx, versioned=False)
    db.fx_rates[fx["id"]] = fx
    return success(public(fx), 201)


@bp.route("/fx-rates/<fx_rate_id>", methods=["GET"])
def get_fx_rate(fx_rate_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "RemittanceAgent"})
    fx = db.fx_rates.get(fx_rate_id)
    if fx is None:
        raise err("ERR_NOT_FOUND", "FX rate not found")
    return success(public(fx), 200)


@bp.route("/fx-rates", methods=["GET"])
def list_fx_rates():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "RemittanceAgent"})
    from flask import request
    items = list(db.fx_rates.values())
    cid = request.args.get("corridor_id")
    if cid is not None:
        items = [f for f in items if f["corridor_id"] == cid]
    page, meta = paginate(items)
    return success([public(f) for f in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# SanctionsListEntry (immutable audit record)
# ---------------------------------------------------------------------------
@bp.route("/sanctions-list", methods=["POST"])
def create_sanctions_entry():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json()
    require_fields(body, ["listed_name", "listed_country", "program"])
    entry = {
        "listed_name": body["listed_name"],
        "listed_country": body["listed_country"],
        "program": body["program"],
        "weight_name_bps": body.get("weight_name_bps", 7000),
        "weight_country_bps": body.get("weight_country_bps", 3000),
    }
    stamp_create(entry, versioned=False)
    db.sanctions_list[entry["id"]] = entry
    return success(public(entry), 201)


@bp.route("/sanctions-list/<entry_id>", methods=["GET"])
def get_sanctions_entry(entry_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "ComplianceOfficer"})
    entry = db.sanctions_list.get(entry_id)
    if entry is None:
        raise err("ERR_NOT_FOUND", "Sanctions list entry not found")
    return success(public(entry), 200)


@bp.route("/sanctions-list", methods=["GET"])
def list_sanctions_entries():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "ComplianceOfficer"})
    from flask import request
    items = list(db.sanctions_list.values())
    program = request.args.get("program")
    country = request.args.get("listed_country")
    if program is not None:
        items = [e for e in items if e["program"] == program]
    if country is not None:
        items = [e for e in items if e["listed_country"] == country]
    page, meta = paginate(items)
    return success([public(e) for e in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# Logical clock (PlatformAdmin only). Returns 200 with null data.
# ---------------------------------------------------------------------------
@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json()
    require_fields(body, ["to_iso8601"])
    db.set_clock(parse_iso(body["to_iso8601"]))
    expire_quotes()
    return success(None, 200)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json()
    require_fields(body, ["seconds"])
    seconds = body["seconds"]
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise err("ERR_INVALID_REQUEST", "seconds must be a number")
    db.advance_clock(seconds)
    expire_quotes()
    return success(None, 200)
