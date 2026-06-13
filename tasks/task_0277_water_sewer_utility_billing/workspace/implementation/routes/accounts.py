"""Account routes (PRD §3.2)."""
from flask import Blueprint, request

import db
import middleware
from response import object_response, array_response
from services import lookup
from services.common import (
    get_json_body, require_str, public, public_list, parse_pagination, paginate,
)

bp = Blueprint("accounts", __name__)


@bp.post("/accounts")
def create_account():
    middleware.require_role({"BillingClerk"})
    body = get_json_body()

    # FK existence checked before body well-formedness ordering is satisfied
    # because rate_schedule_id is itself a required body FK (PRD §2.8).
    rate_schedule_id = require_str(body, "rate_schedule_id")
    lookup.rate_schedule(rate_schedule_id)
    holder_name = require_str(body, "holder_name")
    service_address = require_str(body, "service_address")

    rec = db.make_record({
        "rate_schedule_id": rate_schedule_id,
        "holder_name": holder_name,
        "service_address": service_address,
        # PRD §3.2: starts CURRENT / ACTIVE, balance 0.
        "billing_status": "CURRENT",
        "service_status": "ACTIVE",
        "balance_due_cents": 0,
        "past_due_cents": 0,
        "budget_billing_enrolled": False,
        "assistance_enrolled": False,
        "_trueup_adjustment_cents": 0,
    })
    db.accounts[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/accounts/<rid>")
def get_account(rid):
    middleware.require_role({"BillingClerk", "FieldOps", "AssistanceCaseworker", "Customer"})
    rec = lookup.account(rid)
    middleware.require_owner(rec["id"])
    return object_response(public(rec), 200)


@bp.get("/accounts")
def list_accounts():
    middleware.require_role({"BillingClerk", "FieldOps", "AssistanceCaseworker"})
    limit, offset = parse_pagination()

    billing_status = request.args.get("billing_status")
    service_status = request.args.get("service_status")
    rate_schedule_id = request.args.get("rate_schedule_id")

    records = list(db.accounts.values())
    if billing_status is not None:
        records = [r for r in records if r["billing_status"] == billing_status]
    if service_status is not None:
        records = [r for r in records if r["service_status"] == service_status]
    if rate_schedule_id is not None:
        records = [r for r in records if r["rate_schedule_id"] == rate_schedule_id]

    window, total = paginate(records, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)
