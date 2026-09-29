"""Abatement orders and cost recovery (PRD section 3.7)."""

import datetime
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import domain
from auth import auth, own, owner_must_match
from db import db, insert, sort_created
from errors import fail
from response import created, jsonable, ok, ok_list, touch
from validate import (
    body, check_window, get_decimal, get_dt, get_enum, get_half_hours, get_int, get_str,
    lookup, page, pagination, resolve_fks,
)

bp = Blueprint("abatement", __name__, url_prefix="/fire-district")

PAYMENT_METHODS = ("CHECK", "CARD", "ACH", "WRITE_OFF")


def _order(order_id):
    return lookup("orders", order_id, "ERR_ABATEMENT_ORDER_NOT_FOUND")


def _order_notice(order):
    return db.notices.get(order["violation_notice_id"])


def _order_parcel(order):
    notice = _order_notice(order)
    return db.parcels.get(notice["parcel_id"]) if notice else None


def _covered_dates(start, end):
    dates = []
    cursor = start.date()
    last = end.date()
    while cursor <= last:
        dates.append(cursor)
        cursor += datetime.timedelta(days=1)
    return dates


@bp.get("/abatement-orders/<order_id>")
def read_order(order_id):
    auth("ProgramAdmin", "FireMarshal", "Contractor", "PropertyOwner")
    return ok(jsonable(_order(order_id)))


@bp.get("/abatement-orders")
def list_orders():
    auth("ProgramAdmin", "FireMarshal", "Contractor")
    limit, offset = pagination()
    records = sort_created(list(db.orders.values()))
    for field in ("violation_notice_id", "contractor_id", "verified_by_inspector_id",
                  "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.post("/abatement-orders/<order_id>/award")
def award_order(order_id):
    auth("FireMarshal")
    order = _order(order_id)
    b = body()
    resolved = resolve_fks(b, ["contractor_id"])
    contractor = resolved.get("contractor_id")
    if contractor is None:
        fail("ERR_INVALID_REQUEST", "Field 'contractor_id' is required.")
    crew_hours = get_half_hours(b, "crew_hours")
    start = get_dt(b, "work_start_utc")
    end = get_dt(b, "work_end_utc")
    check_window(start, end)
    if order["status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE", "Only an AUTHORIZED order can be awarded.")

    # Rung 21 — closed work windows: touching endpoints DO conflict.
    live = [
        o for o in sort_created(list(db.orders.values()))
        if o["contractor_id"] == contractor["id"]
        and o["id"] != order["id"]
        and o["status"] in domain.LIVE_ORDER_STATUSES
    ]
    for other in live:
        if start <= other["work_end_utc"] and other["work_start_utc"] <= end:
            fail(
                "ERR_CONTRACTOR_WINDOW_CONFLICT",
                "The contractor already holds an intersecting work window.",
            )
    # Rung 22 — licensing and insurance.
    if contractor["license_status"] != "ACTIVE":
        fail("ERR_CONTRACTOR_NOT_LICENSED", "The contractor's licence is not ACTIVE.")
    if not start < contractor["insurance_expiry_utc"]:
        fail("ERR_CONTRACTOR_INSURANCE_LAPSED", "The contractor's insurance has lapsed.")
    # Rung 24 — aggregate per-UTC-date capacity.
    for day in _covered_dates(start, end):
        held = sum(
            1 for o in live
            if o["work_start_utc"].date() <= day <= o["work_end_utc"].date()
        )
        if held + 1 > contractor["max_daily_orders"]:
            fail(
                "ERR_CONTRACTOR_CAPACITY_EXCEEDED",
                "The contractor is at capacity on %s." % day.isoformat(),
            )

    order["contractor_id"] = contractor["id"]
    order["crew_hours"] = crew_hours
    order["work_start_utc"] = start
    order["work_end_utc"] = end
    order["status"] = "AWARDED"
    touch(order)
    domain.recount_contractor_commitment(contractor)
    touch(contractor)
    return ok(jsonable(order))


@bp.post("/abatement-orders/<order_id>/cancel")
def cancel_order(order_id):
    auth("FireMarshal")
    order = _order(order_id)
    b = body()
    reason = get_str(b, "reason")
    if order["status"] not in ("AUTHORIZED", "AWARDED"):
        fail("ERR_INVALID_STATE", "Only an AUTHORIZED or AWARDED order can be cancelled.")
    was_awarded = order["status"] == "AWARDED"
    contractor = db.contractors.get(order["contractor_id"])
    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason
    touch(order)

    notice = _order_notice(order)
    if notice is not None and notice["status"] == "ABATEMENT_AUTHORIZED":
        notice["status"] = "OVERDUE"
        touch(notice)
    parcel = _order_parcel(order)
    if parcel is not None:
        domain.recount_open_violations(parcel)
        parcel["compliance_status"] = "NON_COMPLIANT"
        touch(parcel)
    if was_awarded and contractor is not None:
        domain.recount_contractor_commitment(contractor)
        touch(contractor)
    if parcel is not None:
        domain.cascade_parcel_posture(parcel)
    return ok(jsonable(order))


@bp.post("/abatement-orders/<order_id>/complete-work")
def complete_work(order_id):
    auth("Contractor")
    order = _order(order_id)
    own(g.user_id == order["contractor_id"])
    b = body()
    actual = get_half_hours(b, "actual_crew_hours")
    tons = get_decimal(b, "green_waste_tons", minimum=0, max_places=2)
    if order["status"] != "AWARDED":
        fail("ERR_INVALID_STATE", "Only an AWARDED order can report completed work.")
    if db.clock < order["work_start_utc"]:
        fail("ERR_INVALID_STATE", "The work window has not opened yet.")
    order["actual_crew_hours"] = actual
    order["green_waste_tons"] = tons
    order["status"] = "WORK_COMPLETE"
    touch(order)
    return ok(jsonable(order))


@bp.post("/abatement-orders/<order_id>/verify-completion")
def verify_completion(order_id):
    auth("Inspector")
    order = _order(order_id)
    b = body()
    get_str(b, "verified_note", required=False)
    if order["status"] != "WORK_COMPLETE":
        fail("ERR_INVALID_STATE", "Only a WORK_COMPLETE order can be verified.")
    acting = db.inspectors.get(g.user_id)
    if acting is not None and acting["status"] != "ACTIVE":
        fail("ERR_INSPECTOR_SUSPENDED", "The acting inspector is not ACTIVE.")

    notice = _order_notice(order)
    substantiating = db.inspections.get(notice["inspection_id"]) if notice else None
    if substantiating is not None and substantiating["inspector_id"] == g.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The inspector who found the violation may not verify the remedy.",
        )

    parcel = db.parcels.get(notice["parcel_id"])
    contractor = db.contractors.get(order["contractor_id"])
    voluntary = any(
        e["parcel_id"] == parcel["id"]
        and e["status"] in domain.RESERVING_ENROLLMENT_STATUSES
        and e["created_at"] < notice["issued_at_utc"]
        for e in db.enrollments.values()
    )
    computed = calc.cost_recovery(
        order["actual_crew_hours"],
        order["green_waste_tons"],
        contractor["hourly_rate_cents"],
        contractor["mobilization_fee_cents"],
        voluntary,
    )
    order.update(computed)
    order["verified_by_inspector_id"] = g.user_id
    cycle = db.cycles.get(substantiating["cycle_id"]) if substantiating else None
    due_days = cycle["invoice_due_days"] if cycle else 45
    order["invoice_due_utc"] = calc.end_of_day(db.clock, due_days)
    order["status"] = "INVOICED"
    touch(order)

    # Link 2 — the reservation finally unwinds.
    domain.recount_contractor_commitment(contractor)
    contractor["completed_crew_hours"] = calc.rhu(
        Decimal(contractor["completed_crew_hours"]) + Decimal(order["actual_crew_hours"]), 1
    )
    touch(contractor)

    # Link 3 — the citation clears; the work has been done.
    notice["status"] = "CLEARED"
    notice["cleared_at_utc"] = db.clock
    touch(notice)

    # Links 4 and 5 — parcel posture, then the community rate that reads it.
    domain.recompute_parcel_posture(parcel, verified_clear=True)
    touch(parcel)
    domain.cascade_parcel_posture(parcel)
    return ok(jsonable(order))


@bp.post("/abatement-orders/<order_id>/payments")
def record_payment(order_id):
    auth("ProgramAdmin", "PropertyOwner")
    order = _order(order_id)
    parcel = _order_parcel(order)
    owner_must_match(parcel["id"] if parcel else None)
    b = body()
    amount = get_int(b, "amount_cents", minimum=1)
    method = get_enum(b, "method", PAYMENT_METHODS)
    if order["status"] not in ("INVOICED", "LIEN_FILED"):
        fail("ERR_INVALID_STATE", "Only an INVOICED or LIEN_FILED order takes payment.")
    outstanding = order["total_recoverable_cents"] - order["paid_cents"]
    if amount > outstanding:
        fail(
            "ERR_PAYMENT_EXCEEDS_OUTSTANDING",
            "The payment exceeds the outstanding balance of %d cents." % outstanding,
        )
    prior = domain.order_payments(order["id"])
    allocation = calc.allocate_payment(order, prior, amount)
    order["paid_cents"] += amount
    payment = insert(db.payments, {
        "abatement_order_id": order["id"],
        "amount_cents": amount,
        "method": method,
        "allocation": allocation,
        "outstanding_after_cents": order["total_recoverable_cents"] - order["paid_cents"],
    }, audit=False)
    if order["status"] == "INVOICED" and order["paid_cents"] == order["total_recoverable_cents"]:
        order["status"] = "PAID"
    touch(order)
    return created(jsonable(payment))


@bp.get("/cost-recovery-payments/<payment_id>")
def read_payment(payment_id):
    auth("ProgramAdmin", "FireMarshal", "PropertyOwner")
    return ok(jsonable(lookup("payments", payment_id, "ERR_PAYMENT_NOT_FOUND")))


@bp.get("/cost-recovery-payments")
def list_payments():
    auth("ProgramAdmin", "FireMarshal", "PropertyOwner")
    limit, offset = pagination()
    records = sort_created(list(db.payments.values()))
    for field in ("abatement_order_id", "method"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )
