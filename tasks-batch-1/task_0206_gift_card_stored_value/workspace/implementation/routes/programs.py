"""Program, StateRule, PromoCampaign, and the test-driving clock (PRD §3.1, §3.10)."""

from flask import Blueprint

from db import db
from core import (
    get_body, stamp_new, paginate,
    check_str, check_int, check_number, check_enum, check_bool, parse_iso,
)
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_program, get_state_rule, get_campaign
import serialize
from domain import sync_campaign, compute_campaign_status

bp = Blueprint("programs", __name__)


# ---------------------------------------------------------------- Program
@bp.post("/v1/programs")
def create_program():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    body = get_body()
    name = check_str(body, "name")
    default_currency = check_str(body, "default_currency", required=False)
    reload_min = check_int(body, "reload_min_cents", required=False)
    reload_max = check_int(body, "reload_max_balance_cents", required=False)
    hold_ttl = check_int(body, "hold_ttl_seconds", required=False)
    b2b_discount = check_number(body, "b2b_discount_pct", required=False)

    p = {
        "name": name,
        "default_currency": default_currency if default_currency is not None else "USD",
        "reload_min_cents": reload_min if reload_min is not None else 500,
        "reload_max_balance_cents": reload_max if reload_max is not None else 100000,
        "hold_ttl_seconds": hold_ttl if hold_ttl is not None else 900,
        "b2b_discount_pct": b2b_discount if b2b_discount is not None else 0.035,
    }
    stamp_new(p)
    db.programs[p["id"]] = p
    return success(serialize.program(p), status=201)


@bp.get("/v1/programs/<program_id>")
def read_program(program_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "StoreAssociate", "FraudAnalyst", "B2BBuyer", "Customer"})
    p = get_program(program_id)
    return success(serialize.program(p))


# ---------------------------------------------------------------- StateRule
@bp.post("/v1/state-rules")
def create_state_rule():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    body = get_body()
    program_id = check_str(body, "program_id")
    state_code = check_str(body, "state_code")
    expiration_allowed = check_bool(body, "expiration_allowed", default=None)
    dormancy_fee_allowed = check_bool(body, "dormancy_fee_allowed", default=None)
    if expiration_allowed is None or "expiration_allowed" not in body:
        raise err("ERR_VALIDATION", "Missing required field: expiration_allowed.")
    if dormancy_fee_allowed is None or "dormancy_fee_allowed" not in body:
        raise err("ERR_VALIDATION", "Missing required field: dormancy_fee_allowed.")
    breakage_policy = check_enum(body, "breakage_policy", {"RECOGNIZE", "ESCHEAT"})
    escheat_rate = check_number(body, "escheat_rate", required=False)
    dormancy_threshold = check_int(body, "dormancy_threshold_months", required=False)

    # Body FK existence (priority 5).
    if program_id not in db.programs:
        raise err("ERR_REFERENCE_NOT_FOUND", "program_id does not exist.")

    # Domain shape (priority 6): unique (program_id, state_code).
    for r in db.state_rules.values():
        if r["program_id"] == program_id and r["state_code"] == state_code:
            raise err("ERR_INVALID_REDEMPTION", "Duplicate state rule for this program/state.")

    r = {
        "program_id": program_id,
        "state_code": state_code,
        "expiration_allowed": expiration_allowed,
        "dormancy_fee_allowed": dormancy_fee_allowed,
        "breakage_policy": breakage_policy,
        "escheat_rate": escheat_rate if escheat_rate is not None else 0.60,
        "dormancy_threshold_months": dormancy_threshold if dormancy_threshold is not None else 12,
    }
    stamp_new(r)
    db.state_rules[r["id"]] = r
    return success(serialize.state_rule(r), status=201)


@bp.get("/v1/state-rules/<state_rule_id>")
def read_state_rule(state_rule_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "StoreAssociate", "FraudAnalyst"})
    r = get_state_rule(state_rule_id)
    return success(serialize.state_rule(r))


@bp.get("/v1/state-rules")
def list_state_rules():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "StoreAssociate", "FraudAnalyst"})
    from flask import request
    items = list(db.state_rules.values())
    pid = request.args.get("program_id")
    sc = request.args.get("state_code")
    if pid is not None:
        items = [r for r in items if r["program_id"] == pid]
    if sc is not None:
        items = [r for r in items if r["state_code"] == sc]
    page, pg = paginate(items)
    return success([serialize.state_rule(r) for r in page], pagination=pg)


# ---------------------------------------------------------------- PromoCampaign
@bp.post("/v1/campaigns")
def create_campaign():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    body = get_body()
    program_id = check_str(body, "program_id")
    name = check_str(body, "name")
    bonus_pct = check_number(body, "bonus_pct")
    window_start = check_str(body, "window_start")
    window_end = check_str(body, "window_end")

    if program_id not in db.programs:
        raise err("ERR_REFERENCE_NOT_FOUND", "program_id does not exist.")

    try:
        new_start = parse_iso(window_start)
        new_end = parse_iso(window_end)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "window_start/window_end must be ISO 8601.")

    # Window overlap with existing program campaign (priority 12).
    for c in db.campaigns.values():
        if c["program_id"] != program_id:
            continue
        ex_start = parse_iso(c["window_start"])
        ex_end = parse_iso(c["window_end"])
        # half-open intervals overlap iff new_start < ex_end and ex_start < new_end
        if new_start < ex_end and ex_start < new_end:
            raise err("ERR_CAMPAIGN_OVERLAP", "Campaign window overlaps an existing campaign.")

    c = {
        "program_id": program_id,
        "name": name,
        "bonus_pct": bonus_pct,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    }
    stamp_new(c)
    db.campaigns[c["id"]] = c
    return success(serialize.campaign(c), status=201)


@bp.get("/v1/campaigns/<campaign_id>")
def read_campaign(campaign_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "StoreAssociate"})
    c = get_campaign(campaign_id)
    return success(serialize.campaign(c))


@bp.get("/v1/campaigns")
def list_campaigns():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "StoreAssociate"})
    from flask import request
    items = list(db.campaigns.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [c for c in items if c["program_id"] == pid]
    page, pg = paginate(items)
    return success([serialize.campaign(c) for c in page], pagination=pg)


@bp.post("/v1/campaigns/<campaign_id>/sync-status")
def sync_status(campaign_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    c = get_campaign(campaign_id)
    sync_campaign(c, db.clock.now())
    return success(serialize.campaign(c))


# ---------------------------------------------------------------- Test clock
@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    body = get_body()
    to_iso = check_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "to_iso8601 must be ISO 8601.")
    db.clock.set(dt)
    # Clock advance may recompute campaign statuses (PRD §3.10).
    from domain import sync_all_campaigns
    sync_all_campaigns(dt)
    return success({})
