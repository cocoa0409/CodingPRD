"""Retainers, support incidents and the logical clock — PRD §3.9, §2.4."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, g, request

from core import (auth, clock, created, err, fk, get_body, invalid, iso3, must_get,
                  new_entity, ok, ok_list, pagination, paginate, r2, req_enum, req_number,
                  req_str, opt_str, scope_client, store, touch)
import services as S

bp = Blueprint("support", __name__)

SLA_TIERS = {"GOLD", "SILVER", "BRONZE"}
SEVERITIES = {"SEV1", "SEV2", "SEV3"}


# --------------------------------------------------------------------------
# Retainers
# --------------------------------------------------------------------------
@bp.post("/retainers")
def create_retainer():
    auth("AccountManager")
    b = get_body()
    client = fk(b, "client_id", "client")
    if client is None:
        invalid("client_id is required.")
    eng = fk(b, "engagement_id", "engagement")
    if eng is None:
        invalid("engagement_id is required.")
    from core import req_date
    start = req_date(b, "start_date")
    end = req_date(b, "end_date")
    monthly_fee = req_number(b, "monthly_fee", positive=True, max_dp=2)
    included_hours = req_number(b, "included_hours", non_negative=True)
    sla_tier = req_enum(b, "sla_tier", SLA_TIERS)
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    # Closed windows with a 7-day cooldown buffer on both sides (PRD 3.9).
    cd = timedelta(days=S.RETAINER_COOLDOWN_DAYS)
    for r in store.retainers.values():
        if r["client_id"] != client["id"]:
            continue
        if start <= r["end_date"] + cd and r["start_date"] <= end + cd:
            err("ERR_RETAINER_WINDOW_CONFLICT",
                "The retainer window collides with an existing retainer of this client.")
    row = new_entity({
        "client_id": client["id"], "engagement_id": eng["id"],
        "start_date": start, "end_date": end, "monthly_fee": r2(monthly_fee),
        "included_hours": r2(included_hours), "sla_tier": sla_tier,
    })
    store.retainers[row["id"]] = row
    return created(S.ser_retainer(row))


@bp.get("/retainers/<rid>")
def get_retainer(rid):
    auth()
    r = must_get("retainer", rid)
    scope_client(r["client_id"])
    return ok(S.ser_retainer(r))


@bp.get("/retainers")
def list_retainers():
    auth()
    limit, offset = pagination()
    rows = list(store.retainers.values())
    if g.role == "ClientContact":
        rows = [r for r in rows if r["client_id"] == g.user_id]
    for key in ("client_id", "engagement_id", "sla_tier"):
        val = request.args.get(key)
        if val:
            rows = [r for r in rows if r[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_retainer(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Support incidents
# --------------------------------------------------------------------------
@bp.post("/support-incidents")
def create_incident():
    auth("ClientContact")
    b = get_body()
    retainer = fk(b, "retainer_id", "retainer")
    if retainer is None:
        invalid("retainer_id is required.")
    severity = req_enum(b, "severity", SEVERITIES)
    summary = req_str(b, "summary")
    scope_client(retainer["client_id"])
    today = clock.today()
    if not (retainer["start_date"] <= today <= retainer["end_date"]):
        err("ERR_RETAINER_WINDOW_INACTIVE", "The retainer's coverage window is not live.")
    row = new_entity({
        "retainer_id": retainer["id"], "severity": severity, "summary": summary,
        "status": "OPEN", "opened_at": clock.now, "responded_at": None,
        "resolved_at": None, "response_minutes": None, "resolution_minutes": None,
        "sla_response_breached": False, "sla_resolution_breached": False,
        "sla_credit_amount": Decimal("0.00"),
    })
    store.incidents[row["id"]] = row
    return created(S.ser_incident(row))


@bp.get("/support-incidents/<iid>")
def get_incident(iid):
    auth()
    inc = must_get("incident", iid)
    scope_client(store.retainers[inc["retainer_id"]]["client_id"])
    return ok(S.ser_incident(inc))


@bp.get("/support-incidents")
def list_incidents():
    auth()
    limit, offset = pagination()
    rows = list(store.incidents.values())
    if g.role == "ClientContact":
        rows = [i for i in rows
                if store.retainers[i["retainer_id"]]["client_id"] == g.user_id]
    for key in ("retainer_id", "status", "severity"):
        val = request.args.get(key)
        if val:
            rows = [i for i in rows if i[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_incident(i) for i in page], limit, offset, total)


@bp.post("/support-incidents/<iid>/respond")
def respond(iid):
    auth("Engineer")
    inc = must_get("incident", iid)
    b = get_body()
    opt_str(b, "note")
    if inc["status"] != "OPEN":
        err("ERR_INVALID_TRANSITION", "Only an OPEN incident may be responded to.")
    inc["status"] = "RESPONDED"
    inc["responded_at"] = clock.now
    minutes = S.sla_minutes(inc["severity"], inc["opened_at"], inc["responded_at"])
    inc["response_minutes"] = minutes
    inc["sla_response_breached"] = minutes > S.SLA_RESPONSE_MINUTES[inc["severity"]]
    touch(inc)
    return ok(S.ser_incident(inc))


@bp.post("/support-incidents/<iid>/resolve")
def resolve(iid):
    auth("Engineer")
    inc = must_get("incident", iid)
    b = get_body()
    req_str(b, "resolution_note")
    if inc["status"] != "RESPONDED":
        err("ERR_INVALID_TRANSITION", "Only a RESPONDED incident may be resolved.")
    inc["status"] = "RESOLVED"
    inc["resolved_at"] = clock.now
    minutes = S.sla_minutes(inc["severity"], inc["opened_at"], inc["resolved_at"])
    inc["resolution_minutes"] = minutes
    inc["sla_resolution_breached"] = minutes > S.SLA_RESOLUTION_MINUTES[inc["severity"]]
    retainer = store.retainers[inc["retainer_id"]]
    inc["sla_credit_amount"] = S.compute_sla_credit(inc, retainer)
    touch(inc)
    return ok(S.ser_incident(inc))


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def _parse_iso(value):
    if not isinstance(value, str):
        invalid("to_iso8601 must be an ISO 8601 instant string.")
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        invalid("to_iso8601 must be an ISO 8601 instant string.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("PlatformAdmin")
    b = get_body()
    if "to_iso8601" not in b:
        invalid("to_iso8601 is required.")
    clock.set(_parse_iso(b["to_iso8601"]))
    return ok({"current_utc": iso3(clock.now)})
