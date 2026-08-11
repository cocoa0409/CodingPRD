from decimal import Decimal

from flask import Blueprint, request

from db import stamp_new, store, touch
from envelope import ok, ok_list
from errors import (
    ERR_ASSIGNMENT_NOT_ACTIVE,
    ERR_BUDGET_EXCEEDED,
    ERR_DUPLICATE_TIMESHEET_PERIOD,
    ERR_FORBIDDEN,
    ERR_HOURS_EXCEED_MAX,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PERIOD_OUTSIDE_ASSIGNMENT,
    raise_err,
)
from security import ALL_READ, require_roles
from services import (
    append_ledger,
    governing_card,
    parse_d,
    recompute_committed,
    recompute_invoice,
    round_cents,
    run_billable_event,
)
from validators import (
    apply_filters,
    get_body,
    hours_decimal,
    opt_hours,
    paginate,
    req_date,
    req_hours,
    req_str,
)
import serializers

bp = Blueprint("timesheets", __name__)

MAX_HOURS = Decimal("60")


def _get_timesheet(timesheet_id):
    t = store.timesheets.get(timesheet_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, f"Timesheet {timesheet_id} not found.")
    return t


@bp.post("/v1/timesheets")
def create_timesheet():
    uid, _ = require_roles("Worker")
    body = get_body()
    # -- request shape (400) --
    assignment_id = req_str(body, "assignment_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    submitted_hours = req_hours(body, "submitted_hours")

    # -- existence (404) --
    a = store.assignments.get(assignment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Assignment {assignment_id} not found.")

    # -- ownership (403) --
    if a["worker_id"] != uid:
        raise_err(ERR_FORBIDDEN, "A Worker may only create timesheets against its own assignments.")

    # -- state (409) --
    if a["status"] != "ACTIVE":
        raise_err(ERR_ASSIGNMENT_NOT_ACTIVE, "The assignment is not ACTIVE.")

    # -- business constraints: duplicate period, then hour ceiling --
    for t in store.timesheets.values():
        if t["assignment_id"] == assignment_id and t["period_start"] == period_start:
            raise_err(
                ERR_DUPLICATE_TIMESHEET_PERIOD,
                "A timesheet already exists for this assignment and period_start.",
            )
    if hours_decimal(submitted_hours) > MAX_HOURS:
        raise_err(ERR_HOURS_EXCEED_MAX, "submitted_hours exceeds 60.00.")

    # -- temporal containment (422) --
    if not (
        parse_d(a["start_date"]) <= parse_d(period_start)
        and parse_d(period_end) <= parse_d(a["end_date"])
    ):
        raise_err(
            ERR_PERIOD_OUTSIDE_ASSIGNMENT,
            "The timesheet period must lie inside the assignment's date span.",
        )

    rec = {
        "assignment_id": assignment_id,
        "period_start": period_start,
        "period_end": period_end,
        "submitted_hours": submitted_hours,
        "approved_hours": None,
        "status": "DRAFT",
        "provisional_amount_cents": None,
        "final_amount_cents": None,
        "rejection_reason": None,
        "void_reason": None,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
    }
    stamp_new(rec)
    store.timesheets[rec["id"]] = rec
    return ok(serializers.timesheet(rec), 201)


@bp.get("/v1/timesheets")
def list_timesheets():
    require_roles(*ALL_READ)
    filters = {
        "assignment_id": request.args.get("assignment_id"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.timesheets.values()), filters)
    page, total, limit, offset = paginate(records, serializers.timesheet)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/timesheets/<timesheet_id>")
def get_timesheet(timesheet_id):
    require_roles(*ALL_READ)
    return ok(serializers.timesheet(_get_timesheet(timesheet_id)))


@bp.post("/v1/timesheets/<timesheet_id>/submit")
def submit_timesheet(timesheet_id):
    uid, _ = require_roles("Worker")
    t = _get_timesheet(timesheet_id)
    a = store.assignments.get(t["assignment_id"])
    if a is not None and a["worker_id"] != uid:
        raise_err(ERR_FORBIDDEN, "A Worker may only submit its own timesheets.")
    if t["status"] not in ("DRAFT", "REJECTED"):
        raise_err(ERR_INVALID_STATE, "Only a DRAFT or REJECTED timesheet can be submitted.")
    if a is None or a["status"] != "ACTIVE":
        raise_err(ERR_ASSIGNMENT_NOT_ACTIVE, "The assignment is not ACTIVE.")
    t["status"] = "SUBMITTED"
    t["submitted_by_user_id"] = uid
    t["rejection_reason"] = None
    # PROVISIONAL variant: submitted hours at the unclamped booked bill rate.
    t["provisional_amount_cents"] = round_cents(
        hours_decimal(t["submitted_hours"]) * a["bill_rate_cents"]
    )
    touch(t)
    return ok(serializers.timesheet(t))


@bp.post("/v1/timesheets/<timesheet_id>/approve")
def approve_timesheet(timesheet_id):
    uid, _ = require_roles("HiringManager")
    body = get_body()
    approved_hours = opt_hours(body, "approved_hours")
    t = _get_timesheet(timesheet_id)
    if t["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED timesheet can be approved.")
    a = store.assignments.get(t["assignment_id"])
    eng = store.engagements.get(a["engagement_id"]) if a else None
    sup = store.suppliers.get(a["supplier_id"]) if a else None

    hours_value = approved_hours if approved_hours is not None else t["submitted_hours"]
    # FINAL variant: clamp to the ceiling of the card governing at approval time.
    card = governing_card(eng["role_code"], eng["skill_code"], eng["geo_code"]) if eng else None
    effective_rate = a["bill_rate_cents"]
    if card is not None:
        effective_rate = min(effective_rate, card["bill_rate_ceiling_cents"])
    final_amount = round_cents(hours_decimal(hours_value) * effective_rate)

    if eng is not None and eng["committed_spend_cents"] + final_amount > eng["budget_cents"]:
        raise_err(ERR_BUDGET_EXCEEDED, "Approval would exceed the engagement budget.")

    t["status"] = "APPROVED"
    t["approved_hours"] = hours_value
    t["final_amount_cents"] = final_amount
    t["approved_by_user_id"] = uid
    touch(t)
    run_billable_event(
        eng, sup, final_amount, "TIMESHEET_APPROVED", timesheet_id=t["id"]
    )
    return ok(serializers.timesheet(t))


@bp.post("/v1/timesheets/<timesheet_id>/reject")
def reject_timesheet(timesheet_id):
    require_roles("HiringManager")
    body = get_body()
    reason = req_str(body, "reason")
    t = _get_timesheet(timesheet_id)
    if t["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED timesheet can be rejected.")
    t["status"] = "REJECTED"
    t["rejection_reason"] = reason
    touch(t)
    return ok(serializers.timesheet(t))


@bp.post("/v1/timesheets/<timesheet_id>/void")
def void_timesheet(timesheet_id):
    require_roles("FinanceAnalyst")
    body = get_body()
    reason = req_str(body, "reason")
    t = _get_timesheet(timesheet_id)
    if t["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only an APPROVED timesheet can be voided.")
    line = None
    for l in store.invoice_lines.values():
        if l["timesheet_id"] == t["id"]:
            line = l
            break
    inv = store.invoices.get(line["invoice_id"]) if line else None
    if line is None or inv is None or inv["status"] != "OPEN":
        raise_err(
            ERR_INVALID_STATE,
            "The sourcing invoice line no longer sits on an OPEN invoice.",
        )
    a = store.assignments.get(t["assignment_id"])
    eng = store.engagements.get(a["engagement_id"]) if a else None
    sup = store.suppliers.get(a["supplier_id"]) if a else None

    t["status"] = "VOIDED"
    t["void_reason"] = reason
    touch(t)

    # compensation: negative ledger entry, drop the line, recompute spend
    if sup is not None:
        append_ledger(
            sup, eng["id"], "TIMESHEET_VOIDED", -t["final_amount_cents"],
            timesheet_id=t["id"],
        )
    del store.invoice_lines[line["id"]]
    recompute_invoice(inv)
    if eng is not None:
        recompute_committed(eng)
        touch(eng)
    return ok(serializers.timesheet(t))
