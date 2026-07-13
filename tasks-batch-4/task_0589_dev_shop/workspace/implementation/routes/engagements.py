"""Clients and engagements — PRD §3.1."""
import re
from decimal import Decimal

from flask import Blueprint, g

from core import (auth, created, err, fk, get_body, invalid, must_get, new_entity, ok,
                  ok_list, pagination, paginate, req_date, req_enum, req_number, req_str,
                  scope_client, store, touch, clock, ZERO, r2)
import services as S

bp = Blueprint("engagements", __name__)

SOURCE_CHANNELS = {"REFERRAL", "INBOUND", "OUTBOUND", "PARTNER"}
BILLING_MODELS = {"FIXED", "TIME_AND_MATERIALS"}


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------
@bp.post("/clients")
def create_client():
    auth("AccountManager", "PlatformAdmin")
    b = get_body()
    name = req_str(b, "name")
    email = req_str(b, "billing_email")
    country = req_str(b, "country_code")
    if not re.fullmatch(r"[A-Z]{2}", country):
        invalid("country_code must be exactly two uppercase letters.")
    row = new_entity({"name": name, "billing_email": email, "country_code": country})
    store.clients[row["id"]] = row
    return created(S.ser_client(row))


@bp.get("/clients/<cid>")
def get_client(cid):
    auth()
    c = must_get("client", cid)
    return ok(S.ser_client(c))


# --------------------------------------------------------------------------
# Engagements
# --------------------------------------------------------------------------
@bp.post("/engagements")
def create_engagement():
    auth("AccountManager")
    b = get_body()
    client = fk(b, "client_id", "client")          # step 4 — FK existence
    if client is None:
        invalid("client_id is required.")
    req_str(b, "title")
    req_enum(b, "source_channel", SOURCE_CHANNELS)  # step 5 — well-formedness
    row = new_entity({
        "client_id": client["id"],
        "title": b["title"],
        "source_channel": b["source_channel"],
        "status": "LEAD",
        "billing_status": "UNBILLED",
        "billing_model": None,
        "contract_value": None,
        "budget_hours_cap": None,
        "standard_hourly_rate": None,
        "start_date": None,
        "end_date": None,
        "signed_at": None,
        "approved_hours": Decimal("0.00"),
        "burned_cost": Decimal("0.00"),
        "burn_ratio": Decimal("0.0000"),
        "budget_posture": "HEALTHY",
        "invoiced_amount": Decimal("0.00"),
        "scope_hours_added": Decimal("0.00"),
    })
    store.engagements[row["id"]] = row
    return created(S.ser_engagement(row))


@bp.get("/engagements/<eid>")
def get_engagement(eid):
    auth()
    e = must_get("engagement", eid)
    scope_client(e["client_id"])
    return ok(S.ser_engagement(e))


@bp.get("/engagements")
def list_engagements():
    auth()
    limit, offset = pagination()
    from flask import request
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    billing_model = request.args.get("billing_model")
    rows = list(store.engagements.values())
    if g.role == "ClientContact":
        rows = [e for e in rows if e["client_id"] == g.user_id]
    if client_id:
        rows = [e for e in rows if e["client_id"] == client_id]
    if status:
        rows = [e for e in rows if e["status"] == status]
    if billing_model:
        rows = [e for e in rows if e["billing_model"] == billing_model]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_engagement(e) for e in page], limit, offset, total)


@bp.post("/engagements/<eid>/qualify")
def qualify(eid):
    auth("AccountManager")
    e = must_get("engagement", eid)
    b = get_body()
    outcome = req_enum(b, "outcome", {"QUALIFY", "DISQUALIFY"})
    if e["status"] != "LEAD":
        err("ERR_INVALID_TRANSITION", "Qualification is only available from LEAD.")
    e["status"] = "QUALIFIED" if outcome == "QUALIFY" else "DISQUALIFIED"
    touch(e)
    return ok(S.ser_engagement(e))


@bp.post("/engagements/<eid>/sow")
def issue_sow(eid):
    auth("AccountManager")
    e = must_get("engagement", eid)
    b = get_body()
    billing_model = req_enum(b, "billing_model", BILLING_MODELS)
    contract_value = req_number(b, "contract_value", positive=True, max_dp=2)
    budget_hours_cap = req_number(b, "budget_hours_cap", positive=True)
    rate = req_number(b, "standard_hourly_rate", positive=True, max_dp=2)
    start = req_date(b, "start_date")
    end = req_date(b, "end_date")
    if start > end:
        invalid("start_date must be no later than end_date.")
    if e["status"] != "QUALIFIED":
        err("ERR_INVALID_TRANSITION", "Only a QUALIFIED engagement may receive a SOW.")
    e["billing_model"] = billing_model
    e["contract_value"] = r2(contract_value)
    e["budget_hours_cap"] = r2(budget_hours_cap)
    e["standard_hourly_rate"] = r2(rate)
    e["start_date"] = start
    e["end_date"] = end
    e["status"] = "SOW_ISSUED"
    S.recompute_burn_ledger(e)   # burn_ratio -> 0.0, budget_posture -> HEALTHY
    touch(e)
    return ok(S.ser_engagement(e))


@bp.post("/engagements/<eid>/sign")
def sign(eid):
    auth("ClientContact")
    e = must_get("engagement", eid)
    b = get_body()
    req_str(b, "signed_by_name")
    scope_client(e["client_id"])
    if e["status"] != "SOW_ISSUED":
        err("ERR_INVALID_TRANSITION", "Only a SOW_ISSUED engagement may be signed.")
    e["signed_at"] = clock.now
    e["status"] = "ACTIVE"
    touch(e)
    return ok(S.ser_engagement(e))


@bp.post("/engagements/<eid>/close")
def close(eid):
    auth("DeliveryLead")
    e = must_get("engagement", eid)
    if e["status"] != "ACTIVE":
        err("ERR_INVALID_TRANSITION", "Only an ACTIVE engagement may be closed.")
    sprints = S.sprints_of_engagement(e["id"])
    if any(s["status"] == "ACTIVE" for s in sprints):
        err("ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT", "Close the active sprints first.")
    for s in sprints:
        if s["status"] != "PLANNED":
            continue
        changed = False
        for t in S.tickets_of_sprint(s["id"]):
            if t["status"] == "TODO":
                t["status"] = "CANCELLED"
                touch(t)
                changed = True
        if changed:
            S.recompute_committed_hours(s)
    e["status"] = "CLOSED"
    touch(e)
    return ok(S.ser_engagement(e))


@bp.get("/engagements/<eid>/burn-rate")
def burn_rate(eid):
    auth()
    e = must_get("engagement", eid)
    scope_client(e["client_id"])
    ah, ac, ar = S.approved_burn(e)
    ch, cc, cr = S.committed_burn(e)
    return ok({
        "engagement_id": e["id"],
        "approved_hours": ah,
        "burned_cost": ac,
        "burn_ratio": ar,
        "budget_posture": e["budget_posture"],
        "committed_hours": ch,
        "committed_burned_cost": cc,
        "committed_burn_ratio": cr,
        "contract_value": e["contract_value"],
        "budget_hours_cap": e["budget_hours_cap"],
    })
