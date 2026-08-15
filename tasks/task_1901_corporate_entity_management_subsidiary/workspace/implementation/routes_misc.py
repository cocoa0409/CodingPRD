"""Routes: test harness (clock/sweep), jurisdictions, registered agents, officers."""
from datetime import datetime, timezone

from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_JURISDICTION_NOT_FOUND, ERR_AGENT_NOT_FOUND,
    ERR_OFFICER_NOT_FOUND, ERR_DUPLICATE_OFFICER, ERR_OFFICER_NOT_ACTIVE,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records

bp = Blueprint("misc", __name__)

CS = ["CorporateSecretary"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a non-empty string" % field)
    return v


def _require_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if min_v is not None and v < min_v:
        raise_err(ERR_INVALID_REQUEST, "%s must be >= %s" % (field, min_v))
    if max_v is not None and v > max_v:
        raise_err(ERR_INVALID_REQUEST, "%s must be <= %s" % (field, max_v))
    return v


def _optional_int(body, field, min_v=None, max_v=None):
    if field not in body or body.get(field) is None:
        return None
    return _require_int(body, field, min_v, max_v)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(CS)
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or not raw:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    store.set_clock(dt)
    return ok_object({"current_utc": store.clock_echo()})


@bp.route("/_system/sweep", methods=["POST"])
def sweep():
    require_roles(CS)
    counters = svc.run_sweep()
    return ok_object(counters)


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------
@bp.route("/api/jurisdictions", methods=["POST"])
def create_jurisdiction():
    require_roles(CS)
    body = get_body()
    code = _require_str(body, "code")
    name = _require_str(body, "name")
    rule = body.get("annual_report_due_rule")
    if rule not in ("FIXED_MONTH_DAY", "FORMATION_ANNIVERSARY"):
        raise_err(ERR_INVALID_REQUEST, "annual_report_due_rule is invalid")
    month = body.get("annual_report_due_month")
    day = body.get("annual_report_due_day")
    if rule == "FIXED_MONTH_DAY":
        month = _require_int(body, "annual_report_due_month", 1, 12)
        day = _require_int(body, "annual_report_due_day", 1, 31)
    else:
        if month is not None or day is not None:
            raise_err(ERR_INVALID_REQUEST,
                      "annual_report_due_month/day must be null unless FIXED_MONTH_DAY")
        month = None
        day = None
    grace = _require_int(body, "grace_period_days", 0)
    method = body.get("franchise_tax_method")
    if method not in ("SHARES_TIERED", "FLAT", "NONE"):
        raise_err(ERR_INVALID_REQUEST, "franchise_tax_method is invalid")
    base = _require_int(body, "late_penalty_base_cents", 0)
    cap = _require_int(body, "late_penalty_cap_cents", 0)
    if cap < base:
        raise_err(ERR_INVALID_REQUEST, "late_penalty_cap_cents must be >= late_penalty_base_cents")
    counting = body.get("penalty_day_counting")
    if counting not in ("CALENDAR_DAYS", "BUSINESS_DAYS"):
        raise_err(ERR_INVALID_REQUEST, "penalty_day_counting is invalid")
    report_fee = _require_int(body, "report_fee_cents", 0)
    cert_fee = _require_int(body, "cert_fee_cents", 0)
    notice_days = _require_int(body, "ra_resignation_notice_days", 0)
    forfeiture = _require_int(body, "forfeiture_window_days", 0)

    rec = store.new_record()
    rec.update({
        "code": code,
        "name": name,
        "annual_report_due_rule": rule,
        "annual_report_due_month": month,
        "annual_report_due_day": day,
        "grace_period_days": grace,
        "franchise_tax_method": method,
        "late_penalty_base_cents": base,
        "late_penalty_cap_cents": cap,
        "penalty_day_counting": counting,
        "report_fee_cents": report_fee,
        "cert_fee_cents": cert_fee,
        "ra_resignation_notice_days": notice_days,
        "forfeiture_window_days": forfeiture,
    })
    store.jurisdictions[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/jurisdictions", methods=["GET"])
def list_jurisdictions():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.jurisdictions.values()))
    code = request.args.get("code")
    if code is not None:
        records = [r for r in records if r["code"] == code]
    return paginate([svc.serialize(r) for r in records], request.args)


@bp.route("/api/jurisdictions/<jurisdictionId>", methods=["GET"])
def get_jurisdiction(jurisdictionId):
    require_roles(ALL_ROLES)
    rec = store.jurisdictions.get(jurisdictionId)
    if rec is None:
        raise_err(ERR_JURISDICTION_NOT_FOUND)
    return ok_object(svc.serialize(rec))


# ---------------------------------------------------------------------------
# Registered agents
# ---------------------------------------------------------------------------
@bp.route("/api/registered-agents", methods=["POST"])
def create_agent():
    require_roles(CS)
    body = get_body()
    # Body FK existence (priority 3) before schema (priority 4)
    jurisdiction_id = body.get("jurisdiction_id")
    if jurisdiction_id is not None and jurisdiction_id not in store.jurisdictions:
        raise_err(ERR_JURISDICTION_NOT_FOUND)
    name = _require_str(body, "name")
    if jurisdiction_id is None:
        raise_err(ERR_INVALID_REQUEST, "jurisdiction_id is required")
    address = _require_str(body, "address")
    rec = store.new_record()
    rec.update({
        "name": name,
        "jurisdiction_id": jurisdiction_id,
        "address": address,
    })
    store.registered_agents[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/registered-agents", methods=["GET"])
def list_agents():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.registered_agents.values()))
    jid = request.args.get("jurisdiction_id")
    if jid is not None:
        records = [r for r in records if r["jurisdiction_id"] == jid]
    return paginate([svc.serialize(r) for r in records], request.args)


@bp.route("/api/registered-agents/<agentId>", methods=["GET"])
def get_agent(agentId):
    require_roles(ALL_ROLES)
    rec = store.registered_agents.get(agentId)
    if rec is None:
        raise_err(ERR_AGENT_NOT_FOUND)
    return ok_object(svc.serialize(rec))


# ---------------------------------------------------------------------------
# Officers
# ---------------------------------------------------------------------------
@bp.route("/api/officers", methods=["POST"])
def create_officer():
    require_roles(CS)
    body = get_body()
    full_name = _require_str(body, "full_name")
    email = _require_str(body, "email")
    if any(o for o in store.officers.values() if o["email"] == email):
        raise_err(ERR_DUPLICATE_OFFICER, "Officer email already registered")
    rec = store.new_record()
    rec.update({"full_name": full_name, "email": email, "status": "ACTIVE"})
    store.officers[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/officers", methods=["GET"])
def list_officers():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.officers.values()))
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([svc.serialize(r) for r in records], request.args)


@bp.route("/api/officers/<officerId>", methods=["GET"])
def get_officer(officerId):
    require_roles(ALL_ROLES)
    rec = store.officers.get(officerId)
    if rec is None:
        raise_err(ERR_OFFICER_NOT_FOUND)
    return ok_object(svc.serialize(rec))


@bp.route("/api/officers/<officerId>/deactivate", methods=["POST"])
def deactivate_officer(officerId):
    require_roles(CS)
    rec = store.officers.get(officerId)
    if rec is None:
        raise_err(ERR_OFFICER_NOT_FOUND)
    if rec["status"] != "ACTIVE":
        raise_err(ERR_OFFICER_NOT_ACTIVE, "Officer is not ACTIVE")
    rec["status"] = "DEACTIVATED"
    store.touch(rec)
    return ok_object(svc.serialize(rec))
