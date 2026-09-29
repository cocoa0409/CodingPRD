"""Weekly timesheet lines, the burn ledger and its exact compensation (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint, g

from calc import D, TIMESHEET_HOURS_MAX, time_entry_costing
from db import clock_date, db, new_row, rows, touch
from errors import fail
from middleware import (
    READ_ROLES,
    ROLE_CLIENT,
    ROLE_LEADERSHIP,
    ROLE_MANAGER,
    ROLE_PARTNER,
    ROLE_REVIEWER,
    client_scope,
    require_roles,
)
from response import ok
from routes.common import fetch, filtered, fk, paged
from serializers import time_entry_out
from services import economics
from validators import (
    filter_arg,
    get_bool,
    get_date,
    get_decimal,
    get_enum,
    get_id,
    get_str,
    json_body,
    parse_date,
)

bp = Blueprint("time_entries", __name__)

LOGGER_ROLES = (ROLE_PARTNER, ROLE_MANAGER, ROLE_REVIEWER, ROLE_LEADERSHIP)
BLOCKING_STATUSES = ("SUBMITTED", "APPROVED")


def manager_binding(engagement):
    if engagement is None or g.user_id != engagement["engagement_manager_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the engagement manager may decide a timesheet line.",
        )


def approved_billed_total(engagement_id):
    total = 0
    for entry in rows("time_entries"):
        if entry["engagement_id"] == engagement_id and entry["status"] == "APPROVED":
            total += int(entry["billed_value_cents"] or 0)
    return total


# ------------------------------------------------------------------ create


@bp.post("/time-entries")
def create_time_entry():
    require_roles(*LOGGER_ROLES)
    body = json_body()
    engagement_id = get_id(body, "engagement_id")
    deliverable_id = get_id(body, "deliverable_id")
    consultant_id = get_id(body, "consultant_id")
    week_ending = get_date(body, "week_ending_date")
    hours = get_decimal(body, "hours")
    billable = get_bool(body, "billable", required=False, default=True)

    engagement = fk("engagements", engagement_id)
    deliverable = fk("deliverables", deliverable_id)
    consultant = fk("consultants", consultant_id)

    if engagement["delivery_state"] == "CLOSED":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "No timesheet line may be logged on a CLOSED engagement.")

    if deliverable["opportunity_id"] != engagement["opportunity_id"]:
        fail(
            "ERR_DELIVERABLE_NOT_IN_ENGAGEMENT_SCOPE",
            "The deliverable does not belong to the engagement's pursuit.",
        )

    week_text = week_ending.isoformat()
    for entry in rows("time_entries"):
        if (
            entry["engagement_id"] == engagement_id
            and entry["deliverable_id"] == deliverable_id
            and entry["consultant_id"] == consultant_id
            and entry["week_ending_date"] == week_text
            and entry["status"] in BLOCKING_STATUSES
        ):
            fail("ERR_DUPLICATE_TIMESHEET_LINE", "A live line already covers that week.")

    start = parse_date(engagement["planned_start_date"])
    end = parse_date(engagement["planned_end_date"])
    if week_ending < start or week_ending > end:
        fail(
            "ERR_TIME_ENTRY_OUTSIDE_ENGAGEMENT_WINDOW",
            "week_ending_date falls outside the engagement's planned delivery window.",
        )
    if week_ending > clock_date():
        fail("ERR_FUTURE_TIMESHEET_LINE", "week_ending_date is later than the current clock date.")

    if hours <= Decimal("0.00") or hours > TIMESHEET_HOURS_MAX:
        fail(
            "ERR_TIMESHEET_HOURS_OUT_OF_RANGE",
            "hours must be greater than 0.00 and at most 60.00.",
        )

    cost_cents, billed_value_cents = time_entry_costing(
        hours, consultant, engagement["pinned_scope_discount_pct"], billable
    )

    row = new_row(
        {
            "engagement_id": engagement_id,
            "deliverable_id": deliverable_id,
            "consultant_id": consultant_id,
            "week_ending_date": week_text,
            "hours": hours,
            "billable": billable,
            "status": "SUBMITTED",
            "cost_cents": cost_cents,
            "billed_value_cents": billed_value_cents,
            "reversal_reason": None,
        }
    )
    db.time_entries[row["id"]] = row
    return ok(time_entry_out(row), 201)


# ------------------------------------------------------------------ read / list


@bp.get("/time-entries/<entry_id>")
def read_time_entry(entry_id):
    require_roles(*READ_ROLES)
    row = fetch("time_entries", entry_id)
    engagement = db.engagements.get(row["engagement_id"])
    if engagement is not None:
        client_scope(engagement["client_id"])
    return ok(time_entry_out(row))


@bp.get("/time-entries")
def list_time_entries():
    require_roles(*READ_ROLES)
    engagement_id = filter_arg("engagement_id")
    deliverable_id = filter_arg("deliverable_id")
    consultant_id = filter_arg("consultant_id")
    week = filter_arg("week_ending_date")
    status = filter_arg("status")
    own_client = g.user_id if g.role == ROLE_CLIENT else None

    def keep(row):
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            return False
        if deliverable_id is not None and row["deliverable_id"] != deliverable_id:
            return False
        if consultant_id is not None and row["consultant_id"] != consultant_id:
            return False
        if week is not None and row["week_ending_date"] != week:
            return False
        if status is not None and row["status"] != status:
            return False
        if own_client is not None:
            engagement = db.engagements.get(row["engagement_id"])
            if engagement is None or engagement["client_id"] != own_client:
                return False
        return True

    return paged(filtered("time_entries", keep), time_entry_out)


# ------------------------------------------------------------------ decision


@bp.post("/time-entries/<entry_id>/decision")
def decide_time_entry(entry_id):
    require_roles(ROLE_MANAGER)
    row = fetch("time_entries", entry_id)
    engagement = db.engagements.get(row["engagement_id"])
    manager_binding(engagement)
    if g.user_id == row["consultant_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "A consultant may not approve their own timesheet line.")

    body = json_body()
    decision = get_enum(body, "decision", ("APPROVE", "REJECT"))

    if row["status"] != "SUBMITTED":
        fail("ERR_TIME_ENTRY_STATE_INVALID", "Only a SUBMITTED line may be decided.")
    if engagement["delivery_state"] not in ("ACTIVE", "CLOSING"):
        fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement's delivery is neither ACTIVE nor CLOSING.")

    if decision == "REJECT":
        row["status"] = "REJECTED"
        touch(row)
        return ok(time_entry_out(row))

    if engagement["pricing_model"] == "TIME_AND_MATERIALS":
        ceiling = engagement["not_to_exceed_cents"]
        projected = approved_billed_total(engagement["id"]) + int(row["billed_value_cents"] or 0)
        if ceiling is not None and projected > int(ceiling):
            fail(
                "ERR_NOT_TO_EXCEED_BREACHED",
                "Approving the line would push billed value past the not-to-exceed ceiling.",
            )

    deliverable = db.deliverables.get(row["deliverable_id"])
    row["status"] = "APPROVED"
    touch(row)
    engagement["approved_hours_burned"] = D(engagement["approved_hours_burned"]) + D(row["hours"])
    engagement["burned_cost_cents"] = int(engagement["burned_cost_cents"]) + int(row["cost_cents"])
    touch(engagement)
    if deliverable is not None:
        deliverable["hours_consumed"] = D(deliverable["hours_consumed"]) + D(row["hours"])
        touch(deliverable)
    economics.recompute(engagement)
    return ok(time_entry_out(row))


# ------------------------------------------------------------------ reversal


@bp.post("/time-entries/<entry_id>/reverse")
def reverse_time_entry(entry_id):
    require_roles(ROLE_MANAGER)
    row = fetch("time_entries", entry_id)
    engagement = db.engagements.get(row["engagement_id"])
    manager_binding(engagement)

    body = json_body()
    reason = get_str(body, "reversal_reason", min_len=1, max_len=None)

    if row["status"] != "APPROVED":
        fail("ERR_TIME_ENTRY_STATE_INVALID", "Only an APPROVED line may be reversed.")
    if engagement["delivery_state"] == "CLOSED":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement is CLOSED.")

    deliverable = db.deliverables.get(row["deliverable_id"])
    row["status"] = "REVERSED"
    row["reversal_reason"] = reason
    touch(row)
    engagement["approved_hours_burned"] = D(engagement["approved_hours_burned"]) - D(row["hours"])
    engagement["burned_cost_cents"] = int(engagement["burned_cost_cents"]) - int(row["cost_cents"])
    touch(engagement)
    if deliverable is not None:
        deliverable["hours_consumed"] = D(deliverable["hours_consumed"]) - D(row["hours"])
        touch(deliverable)
    economics.recompute(engagement)
    return ok(time_entry_out(row))
