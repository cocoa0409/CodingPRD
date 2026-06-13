"""Extra / bulk pickup requests (PRD §3.10)."""
from flask import Blueprint, request

import db
from errors import err
from response import ok, ok_list
from routes.helpers import gate, require_ownership
from services import validate as V
from services import calc
from services.common import new_record, touch, sort_by_created
from services.lookup import get_or_404
from services.serialize import extra_out
from services.schedule import _create_row
from util import parse_dt, to_midnight

bp = Blueprint("extras", __name__)


@bp.route("/accounts/<aid>/extra-pickups", methods=["POST"])
def create_extra(aid):
    user_id, role = gate({"AccountHolder", "Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    body = V.get_body(request)
    requested_date = V.require_dt(body, "requested_date")
    bulk_item_count = V.require_int(body, "bulk_item_count", minimum=0)

    from util import format_date
    rec = new_record({
        "account_id": a["id"],
        "requested_date": format_date(to_midnight(requested_date)),
        "bulk_item_count": bulk_item_count,
        "charge_cents": 0,
        "status": "REQUESTED",
    })
    db.extra_pickup_requests[rec["id"]] = rec
    return ok(extra_out(rec), 201)


@bp.route("/accounts/<aid>/extra-pickups", methods=["GET"])
def list_extras(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    limit, offset = V.parse_pagination(request.args)
    items = [r for r in db.extra_pickup_requests.values() if r["account_id"] == a["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([extra_out(r) for r in page], limit, offset, total)


@bp.route("/extra-pickups/<rid>", methods=["GET"])
def get_extra(rid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    r = get_or_404(db.extra_pickup_requests, rid)
    require_ownership(role, user_id, r["account_id"])
    return ok(extra_out(r))


@bp.route("/extra-pickups/<rid>/schedule", methods=["POST"])
def schedule_extra(rid):
    gate({"Dispatcher"})
    r = get_or_404(db.extra_pickup_requests, rid)
    account = db.service_accounts.get(r["account_id"])

    # priority 7: state legality (must be REQUESTED)
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Request is not REQUESTED.")
    # parent account must be ACTIVE (part of the transition precondition)
    if account is None or account["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Parent account is not ACTIVE.")

    # priority 11: no other SCHEDULED request on the same account holds this date
    rd = to_midnight(parse_dt(r["requested_date"]))
    for other in db.extra_pickup_requests.values():
        if other["id"] == r["id"]:
            continue
        if other["account_id"] != r["account_id"]:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if to_midnight(parse_dt(other["requested_date"])) == rd:
            raise err("ERR_DATE_DOUBLE_BOOKED", "Another scheduled extra pickup holds this date.")

    plan = db.service_plans[account["plan_id"]]
    r["charge_cents"] = calc.extra_pickup_charge(plan, r["bulk_item_count"])
    r["status"] = "SCHEDULED"

    # create a PLANNED schedule row (TRASH stream) for the requested date, flagged extra
    new_row = _create_row(account, rd, "TRASH", is_extra=True)
    r["_schedule_id"] = new_row["id"]

    touch(r)
    return ok(extra_out(r))


@bp.route("/extra-pickups/<rid>/complete", methods=["POST"])
def complete_extra(rid):
    gate({"CrewLead"})
    r = get_or_404(db.extra_pickup_requests, rid)
    if r["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Request is not SCHEDULED.")
    r["status"] = "COMPLETED"
    touch(r)
    return ok(extra_out(r))


@bp.route("/extra-pickups/<rid>/cancel", methods=["POST"])
def cancel_extra(rid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    r = get_or_404(db.extra_pickup_requests, rid)
    require_ownership(role, user_id, r["account_id"])
    if r["status"] not in ("REQUESTED", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Request is not REQUESTED or SCHEDULED.")

    if r["status"] == "SCHEDULED":
        # cancel the linked schedule row and reverse the charge
        sched_id = r.get("_schedule_id")
        if sched_id is not None:
            sched = db.pickup_schedules.get(sched_id)
            if sched is not None and sched["status"] == "PLANNED":
                sched["status"] = "CANCELLED"
                touch(sched)
        r["charge_cents"] = 0

    r["status"] = "CANCELLED"
    touch(r)
    return ok(extra_out(r))
