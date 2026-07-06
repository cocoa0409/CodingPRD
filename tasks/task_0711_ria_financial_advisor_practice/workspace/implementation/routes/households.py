"""Household endpoints (PRD §2.8)."""

from flask import Blueprint, request

from db import db
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from util import body, require_str, opt_enum, pagination, paginate

bp = Blueprint("households", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}
BILLING_METHODS = {"ARREARS", "ADVANCE"}


def serialize(h):
    return {
        "id": h["id"],
        "name": h["name"],
        "lead_advisor_id": h["lead_advisor_id"],
        "fee_schedule_id": h["fee_schedule_id"],
        "billing_method": h["billing_method"],
        "billable_aum_cents": h["billable_aum_cents"],
        "aggregated_aum_cents": h["aggregated_aum_cents"],
        "breakpoint_tier_index": h["breakpoint_tier_index"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


@bp.route("/households", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    name = require_str(data, "name")
    lead_advisor_id = require_str(data, "lead_advisor_id")
    fee_schedule_id = require_str(data, "fee_schedule_id")
    billing_method = opt_enum(data, "billing_method", BILLING_METHODS, "ARREARS")
    # body-reference existence (priority 4)
    ref_or_422(db.fee_schedules, fee_schedule_id, "fee_schedule_id")
    h = {
        "name": name,
        "lead_advisor_id": lead_advisor_id,
        "fee_schedule_id": fee_schedule_id,
        "billing_method": billing_method,
        "billable_aum_cents": 0,
        "aggregated_aum_cents": 0,
        "breakpoint_tier_index": 0,
        "status": "ACTIVE",
    }
    stamp_new(h)
    db.households[h["id"]] = h
    return created(serialize(h))


@bp.route("/households/<hid>", methods=["GET"])
def read(hid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h = get_or_404(db.households, hid)
    return ok(serialize(h))


@bp.route("/households", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    fee_schedule_id = request.args.get("fee_schedule_id")
    items = list(db.households.values())
    if fee_schedule_id is not None:
        items = [h for h in items if h["fee_schedule_id"] == fee_schedule_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/households/<hid>/close", methods=["POST"])
def close(hid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    h = get_or_404(db.households, hid)
    h["status"] = "CLOSED"
    touch(h)
    return ok(serialize(h))


@bp.route("/households/<hid>/clients", methods=["GET"])
def list_clients(hid):
    from routes.clients import serialize as serialize_client
    _, role = authenticate()
    authorize(role, READ_ROLES)
    get_or_404(db.households, hid)
    limit, offset = pagination()
    items = [c for c in db.clients.values() if c["household_id"] == hid]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize_client(x) for x in page], limit, offset, len(items))


@bp.route("/households/<hid>/accounts", methods=["GET"])
def list_accounts(hid):
    from routes.accounts import serialize as serialize_account
    _, role = authenticate()
    authorize(role, READ_ROLES)
    get_or_404(db.households, hid)
    limit, offset = pagination()
    items = [a for a in db.accounts.values() if a["household_id"] == hid]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize_account(x) for x in page], limit, offset, len(items))
