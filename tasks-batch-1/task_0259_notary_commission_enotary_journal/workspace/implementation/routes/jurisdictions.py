"""Jurisdiction + FeeSchedule routes (PRD §3.1)."""
from flask import Blueprint

from db import store, new_common_fields
from domain import find_jurisdiction, fee_schedule_for, ACT_TYPES, COMMISSION_TERMS
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, require_bool, require_int, require_enum,
    non_negative_cents, parse_pagination, paginate,
)

bp = Blueprint("jurisdictions", __name__)


@bp.post("/jurisdictions")
@endpoint(("CommissionAuthority",), exempt_auth=True)
def create_jurisdiction():
    body = get_body()
    state_code = require_str(body, "state_code")
    ron_allowed = require_bool(body, "ron_allowed")
    bond_minimum = require_int(body, "bond_minimum_cents")
    term_months = require_int(body, "commission_term_months")
    grace_days = require_int(body, "renewal_grace_days")
    session_cap = require_int(body, "session_act_fee_cap_cents")
    surcharge_cap = require_int(body, "ron_surcharge_cap_cents")

    # Semantic validation (422): state_code shape, term set, non-negative cents.
    if not (state_code.isupper() and len(state_code) == 2 and state_code.isalpha()):
        raise err("ERR_VALIDATION", "state_code must be two uppercase letters")
    if term_months not in COMMISSION_TERMS:
        raise err("ERR_VALIDATION", "commission_term_months must be one of 48,60,96,120")
    non_negative_cents(bond_minimum, "bond_minimum_cents")
    non_negative_cents(session_cap, "session_act_fee_cap_cents")
    non_negative_cents(surcharge_cap, "ron_surcharge_cap_cents")
    if grace_days < 0:
        raise err("ERR_VALIDATION", "renewal_grace_days must be >= 0")
    if any(j["state_code"] == state_code for j in store.jurisdictions.values()):
        raise err("ERR_VALIDATION", "state_code must be unique")

    rec = dict(new_common_fields())
    rec.update({
        "state_code": state_code,
        "ron_allowed": ron_allowed,
        "bond_minimum_cents": bond_minimum,
        "commission_term_months": term_months,
        "renewal_grace_days": grace_days,
        "session_act_fee_cap_cents": session_cap,
        "ron_surcharge_cap_cents": surcharge_cap,
    })
    store.jurisdictions[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/jurisdictions/<jurisdiction_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_jurisdiction(jurisdiction_id):
    return success(view(find_jurisdiction(jurisdiction_id)))


@bp.get("/jurisdictions")
@endpoint(("CommissionAuthority", "Notary"))
def list_jurisdictions():
    from flask import request
    limit, offset = parse_pagination()
    recs = list(store.jurisdictions.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        recs = [r for r in recs if r["state_code"] == state_code]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.post("/jurisdictions/<jurisdiction_id>/fee-schedules")
@endpoint(("CommissionAuthority",))
def create_fee_schedule(jurisdiction_id):
    juris = find_jurisdiction(jurisdiction_id)
    body = get_body()
    act_type = require_enum(body, "act_type", ACT_TYPES)
    max_fee = require_int(body, "max_act_fee_cents")
    non_negative_cents(max_fee, "max_act_fee_cents")
    if fee_schedule_for(jurisdiction_id, act_type) is not None:
        raise err("ERR_VALIDATION", "Fee schedule already exists for this act_type")

    rec = dict(new_common_fields())
    rec.update({
        "jurisdiction_id": jurisdiction_id,
        "act_type": act_type,
        "max_act_fee_cents": max_fee,
    })
    store.fee_schedules[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/jurisdictions/<jurisdiction_id>/fee-schedules")
@endpoint(("CommissionAuthority", "Notary"))
def list_jurisdiction_fee_schedules(jurisdiction_id):
    from flask import request
    find_jurisdiction(jurisdiction_id)
    limit, offset = parse_pagination()
    recs = [f for f in store.fee_schedules.values() if f["jurisdiction_id"] == jurisdiction_id]
    act_type = request.args.get("act_type")
    if act_type is not None:
        recs = [r for r in recs if r["act_type"] == act_type]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.get("/fee-schedules/<fee_schedule_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_fee_schedule(fee_schedule_id):
    rec = store.fee_schedules.get(fee_schedule_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Fee schedule not found")
    return success(view(rec))


@bp.get("/fee-schedules")
@endpoint(("CommissionAuthority", "Notary"))
def list_fee_schedules():
    from flask import request
    limit, offset = parse_pagination()
    recs = list(store.fee_schedules.values())
    jid = request.args.get("jurisdiction_id")
    act_type = request.args.get("act_type")
    if jid is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jid]
    if act_type is not None:
        recs = [r for r in recs if r["act_type"] == act_type]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)
