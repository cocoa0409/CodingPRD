"""Residual events and union fringe configuration."""
from flask import Blueprint, request

from db import db, now_iso, new_id
from errors import err
from middleware import authenticate, authorize
from helpers import (get_json_body, require_string, require_enum, require_int,
                     require_int_range, optional_int, parse_pagination, paginate)
from response import success_object, success_array
from services.serialize import public
from services.recompute import touch
from services import calc

bp = Blueprint("finance", __name__)

MARKETS = {"THEATRICAL", "SVOD", "BASIC_CABLE", "NETWORK", "HOME_VIDEO"}
FRINGE_UNIONS = {"SAG_AFTRA", "IATSE", "DGA"}


# --- ResidualEvent (immutable: only id + created_at) ------------------------
@bp.route("/residual-events", methods=["POST"])
def create_residual_event():
    role = authenticate()
    authorize(role, {"PayrollCoordinator"})
    body = get_json_body()
    production_id = require_string(body, "production_id")
    prod = db.productions.get(production_id)
    if not prod:
        raise err("ERR_NOT_FOUND", "Production not found.")
    market = require_enum(body, "market", MARKETS)
    gross = require_int(body, "gross_receipts_cents", minimum=0)
    event_date = require_string(body, "event_date")
    with db.lock:
        ts = now_iso()
        seq = db.next_seq()
        # prior cumulative = sum gross of EARLIER events of this production,
        # ordered event_date ASC then created_at ASC. "Earlier" = strictly before
        # this new event in that ordering. An existing event sorts before the new
        # one iff its (event_date, _seq) tuple is strictly less than the new
        # event's. Since the new event has the newest _seq, an existing event
        # with the SAME event_date is earlier (smaller _seq); an existing event
        # with a LATER event_date is NOT earlier and must be excluded.
        new_key = (event_date, seq)
        prior_cumulative = sum(
            e["gross_receipts_cents"] for e in db.residual_events.values()
            if e["production_id"] == production_id
            and (e["event_date"], e["_seq"]) < new_key)
        new_cumulative = prior_cumulative + gross
        residual = calc.residual_amount(prior_cumulative, new_cumulative)
        event = {
            "id": new_id(),
            "production_id": production_id,
            "market": market,
            "gross_receipts_cents": gross,
            "event_date": event_date,
            "residual_amount_cents": residual,
            "created_at": ts,
            "_seq": seq,
        }
        db.residual_events[event["id"]] = event
        # accrue into production reserve (a mutation of the production)
        prod["residual_reserve_cents"] += residual
        touch(prod)
        return success_object(public(event), status=201)


@bp.route("/residual-events/<eid>", methods=["GET"])
def get_residual_event(eid):
    role = authenticate()
    authorize(role, {"PayrollCoordinator", "LineProducer", "UnionRep"})
    event = db.residual_events.get(eid)
    if not event:
        raise err("ERR_NOT_FOUND", "Residual event not found.")
    return success_object(public(event))


@bp.route("/residual-events", methods=["GET"])
def list_residual_events():
    role = authenticate()
    authorize(role, {"PayrollCoordinator", "LineProducer", "UnionRep"})
    limit, offset = parse_pagination()
    production_id = request.args.get("production_id")
    items = list(db.residual_events.values())
    if production_id is not None:
        items = [e for e in items if e["production_id"] == production_id]
    page, total = paginate(items, limit, offset)
    return success_array([public(e) for e in page], limit, offset, total)


# --- UnionFringe ------------------------------------------------------------
@bp.route("/union-fringes", methods=["POST"])
def create_union_fringe():
    role = authenticate()
    authorize(role, {"LineProducer"})
    body = get_json_body()
    production_id = require_string(body, "production_id")
    if production_id not in db.productions:
        raise err("ERR_NOT_FOUND", "Production not found.")
    union_code = require_enum(body, "union_code", FRINGE_UNIONS)
    fringe_rate_bps = require_int_range(body, "fringe_rate_bps", 0, 10000)
    flat = optional_int(body, "pension_health_flat_cents", default=0, minimum=0)
    with db.lock:
        # ERR_DUPLICATE_FRINGE (priority 14): unique union_code per production
        for f in db.union_fringes.values():
            if f["production_id"] == production_id and f["union_code"] == union_code:
                raise err("ERR_DUPLICATE_FRINGE",
                          "A union fringe already exists for this production and union.")
        ts = now_iso()
        fringe = {
            "id": new_id(),
            "production_id": production_id,
            "union_code": union_code,
            "fringe_rate_bps": fringe_rate_bps,
            "pension_health_flat_cents": flat,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.union_fringes[fringe["id"]] = fringe
        return success_object(public(fringe), status=201)


@bp.route("/union-fringes/<fid>", methods=["GET"])
def get_union_fringe(fid):
    role = authenticate()
    authorize(role, {"LineProducer", "PayrollCoordinator", "UnionRep"})
    fringe = db.union_fringes.get(fid)
    if not fringe:
        raise err("ERR_NOT_FOUND", "Union fringe not found.")
    return success_object(public(fringe))


@bp.route("/union-fringes", methods=["GET"])
def list_union_fringes():
    role = authenticate()
    authorize(role, {"LineProducer", "PayrollCoordinator", "UnionRep"})
    limit, offset = parse_pagination()
    production_id = request.args.get("production_id")
    items = list(db.union_fringes.values())
    if production_id is not None:
        items = [f for f in items if f["production_id"] == production_id]
    page, total = paginate(items, limit, offset)
    return success_array([public(f) for f in page], limit, offset, total)
