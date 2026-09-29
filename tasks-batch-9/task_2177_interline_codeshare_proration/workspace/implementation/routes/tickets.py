"""Tickets and proration runs (PRD sections 3.4, 3.5)."""

from flask import Blueprint

from calculations import commit_proration, coupons_of_ticket, plan_proration
from errors import ApiError
from responses import ok, ok_list
from store import db, must_find, new_row, serialize, touch
import validation as V

bp = Blueprint("tickets", __name__)


@bp.route("/interline/tickets", methods=["POST"])
def create_ticket():
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    data = V.body()
    ticket_number = V.req_str(data, "ticket_number")
    validating_carrier_id = V.req_str(data, "validating_carrier_id")
    sale_currency = V.req_enum(data, "sale_currency", V.CURRENCIES)
    total_fare = V.req_int(data, "total_fare_minor", minimum=1)
    issue_raw, issue_dt = V.req_dt(data, "issue_date")

    carrier = must_find("carrier", validating_carrier_id)

    V.require_ownership(user_id, role, carrier["id"])

    if carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    for other in db.tickets.values():
        if other["ticket_number"] == ticket_number:
            raise ApiError("ERR_DUPLICATE_TICKET_NUMBER")

    ticket = new_row({
        "ticket_number": ticket_number,
        "validating_carrier_id": carrier["id"],
        "sale_currency": sale_currency,
        "total_fare_minor": total_fare,
        "issue_date": issue_raw,
        "proration_status": "UNPRORATED",
        "billing_status": "UNBILLED",
        "coupon_count": 0,
        "unallocated_residual_minor": total_fare,
        "last_run_type": "NONE",
    })
    ticket["_issue_date"] = issue_dt
    db.tickets[ticket["id"]] = ticket
    return ok(serialize(ticket), 201)


@bp.route("/interline/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    V.require(V.ALL_ROLES)
    ticket = must_find("ticket", ticket_id)
    return ok(serialize(ticket))


@bp.route("/interline/tickets", methods=["GET"])
def list_tickets():
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    validating_carrier_id = V.filter_str("validating_carrier_id")
    proration_status = V.filter_enum("proration_status", V.PRORATION_STATUSES)
    billing_status = V.filter_enum("billing_status", V.BILLING_STATUSES)
    rows = list(db.tickets.values())
    if validating_carrier_id is not None:
        rows = [r for r in rows
                if r["validating_carrier_id"] == validating_carrier_id]
    if proration_status is not None:
        rows = [r for r in rows if r["proration_status"] == proration_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/tickets/<ticket_id>/prorate", methods=["POST"])
def prorate_ticket(ticket_id):
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    data = V.body()
    run_type = V.req_enum(data, "run_type", V.RUN_TYPES)
    expected_version = V.req_int(data, "expected_ticket_version")

    ticket = must_find("ticket", ticket_id)

    V.require_ownership(user_id, role, ticket["validating_carrier_id"])

    # Ladder steps 27, 34 and 39 are raised by the planner before any write.
    plan = plan_proration(ticket, run_type)

    # Ladder step 45 — optimistic concurrency sits at the very bottom.
    if expected_version != ticket["version"]:
        raise ApiError("ERR_STALE_TICKET_VERSION")

    run = commit_proration(ticket, run_type, plan)
    touch(ticket)
    return ok(serialize(run), 201)


@bp.route("/interline/tickets/<ticket_id>/proration-runs", methods=["GET"])
def list_proration_runs(ticket_id):
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    ticket = must_find("ticket", ticket_id)
    rows = [r for r in db.runs.values() if r["ticket_id"] == ticket["id"]]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/tickets/<ticket_id>/void-proration", methods=["POST"])
def void_proration(ticket_id):
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    data = V.body()
    expected_version = V.req_int(data, "expected_ticket_version")

    ticket = must_find("ticket", ticket_id)

    V.require_ownership(user_id, role, ticket["validating_carrier_id"])

    if ticket["proration_status"] not in ("PROVISIONAL", "FINAL",
                                          "REPRORATION_REQUIRED"):
        raise ApiError("ERR_TICKET_NOT_PRORATED")

    if expected_version != ticket["version"]:
        raise ApiError("ERR_STALE_TICKET_VERSION")

    for coupon in coupons_of_ticket(ticket["id"]):
        coupon["allocated_amount_minor"] = 0
        coupon["allocation_basis"] = "UNALLOCATED"

    ticket["unallocated_residual_minor"] = ticket["total_fare_minor"]
    ticket["last_run_type"] = "NONE"
    ticket["proration_status"] = "UNPRORATED"
    touch(ticket)
    return ok(serialize(ticket))
