"""PaymentReminder endpoints: schedule, read, list, acknowledge (PRD §3.8)."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate

bp = Blueprint("reminders", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}


@bp.route("/payment-reminders", methods=["POST"])
def create_reminder():
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        body = validate.get_json_body()
        household_id = validate.require_str(body, "household_id")
        due_date = validate.require_datetime(body, "due_date")
        bill_id = body.get("bill_id")
        settlement_id = body.get("settlement_id")
        # existence: household first
        household = db.households.get(household_id)
        if not household:
            raise err("ERR_NOT_FOUND", "household_id does not exist.")
        # exactly one of bill_id / settlement_id (priority 20)
        has_bill = bill_id is not None
        has_settlement = settlement_id is not None
        if has_bill == has_settlement:
            raise err("ERR_REMINDER_TARGET_AMBIGUOUS", "Exactly one of bill_id or settlement_id must be set.")
        bill = None
        if has_bill:
            bill = db.bills.get(bill_id)
            if not bill:
                raise err("ERR_NOT_FOUND", "bill_id does not exist.")
            # a reminder for a bill may only be scheduled while not yet PAID
            if bill["payment_status"] == "PAID":
                raise err("ERR_INVALID_STATE", "Bill is already PAID.")
        if has_settlement:
            settlement = db.settlements.get(settlement_id)
            if not settlement:
                raise err("ERR_NOT_FOUND", "settlement_id does not exist.")

        reminder = {
            "household_id": household_id,
            "bill_id": bill_id if has_bill else None,
            "settlement_id": settlement_id if has_settlement else None,
            "due_date": due_date,
            "status": "SCHEDULED",
        }
        models.stamp_create(reminder)
        db.payment_reminders[reminder["id"]] = reminder
        # if targeting a bill whose reminder_status is NONE, advance it to SCHEDULED
        if bill is not None and bill["reminder_status"] == "NONE":
            bill["reminder_status"] = "SCHEDULED"
            models.touch(bill)
        return response.ok(models.serialize(reminder), 201)


@bp.route("/payment-reminders/<rid>", methods=["GET"])
def get_reminder(rid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        r = db.payment_reminders.get(rid)
        if not r:
            raise err("ERR_NOT_FOUND", "Reminder not found.")
        return response.ok(models.serialize(r))


@bp.route("/payment-reminders", methods=["GET"])
def list_reminders():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.payment_reminders.values())
        household_id = request.args.get("household_id")
        bill_id = request.args.get("bill_id")
        settlement_id = request.args.get("settlement_id")
        if household_id is not None:
            items = [x for x in items if x["household_id"] == household_id]
        if bill_id is not None:
            items = [x for x in items if x.get("bill_id") == bill_id]
        if settlement_id is not None:
            items = [x for x in items if x.get("settlement_id") == settlement_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/payment-reminders/<rid>/acknowledge", methods=["POST"])
def acknowledge_reminder(rid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        r = db.payment_reminders.get(rid)
        if not r:
            raise err("ERR_NOT_FOUND", "Reminder not found.")
        if r["status"] != "SENT":
            raise err("ERR_INVALID_STATE", "Reminder is not SENT.")
        r["status"] = "ACKNOWLEDGED"
        models.touch(r)
        return response.ok(models.serialize(r))
