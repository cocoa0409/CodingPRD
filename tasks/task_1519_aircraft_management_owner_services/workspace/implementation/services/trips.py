"""Trip domain services: charter credit calculation and completion cascade."""
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import db
from util import fmt_ts
from services.core import (
    make_record, touch, current_agreement_for_aircraft,
    recompute_draft_statements_for_date,
)


def compute_charter_credit(trip, agreement):
    """charter_owner_credit calculation (SCAFFOLD §1.3)."""
    direct_cost = sum(
        e["amount_cents"] for e in db.expenses.values()
        if e["trip_id"] == trip["id"] and e["category"] == "CHARTER_DIRECT"
        and e["status"] != "VOID"
    )
    net = (trip["charter_quote_cents"] or 0) - direct_cost
    if net > 0:
        credit = int(
            (Decimal(net) * Decimal(str(agreement["charter_owner_share_pct"])))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        return credit, 0
    if net == 0:
        return 0, 0
    return 0, -net


def complete_trip(trip, block_hours_actual):
    """SCHEDULED -> COMPLETED cascade (PRD §3.4)."""
    now = clock.now()
    now_str = fmt_ts(now)
    aircraft = db.aircraft[trip["aircraft_id"]]

    trip["block_hours_actual"] = block_hours_actual
    trip["status"] = "COMPLETED"
    trip["_completed_at"] = now
    touch(trip)

    aircraft["total_time_hours"] = float(
        Decimal(str(aircraft["total_time_hours"])) + Decimal(str(block_hours_actual))
    )
    touch(aircraft)

    agreement = current_agreement_for_aircraft(trip["aircraft_id"])

    if trip["trip_use"] == "CHARTER":
        if agreement is not None:
            credit, shortfall = compute_charter_credit(trip, agreement)
        else:
            credit, shortfall = 0, 0
        trip["owner_credit_cents"] = credit
        trip["charter_shortfall_cents"] = shortfall
    else:
        trip["owner_credit_cents"] = 0
        trip["charter_shortfall_cents"] = 0

    # ENROLLED maintenance program -> PROGRAM_ACCRUAL expense
    completion_date = now.date().isoformat()
    for prog in db.programs.values():
        if prog["aircraft_id"] == trip["aircraft_id"] and prog["status"] == "ENROLLED":
            amount = int(
                (Decimal(str(block_hours_actual)) * Decimal(prog["rate_per_hour_cents"]))
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            expense = make_record({
                "aircraft_id": trip["aircraft_id"],
                "statement_id": None,
                "trip_id": trip["id"],
                "category": "PROGRAM_ACCRUAL",
                "amount_cents": amount,
                "service_date": completion_date,
                "paid_date": None,
                "vendor_name": prog["program_name"],
                "tax_use": "MIXED",
                "status": "POSTED",
            })
            db.expenses[expense["id"]] = expense
            trip["_accrual_expense_id"] = expense["id"]
            break

    # ASSIGNED duty assignments -> COMPLETED; crew flight hours
    for a in db.assignments.values():
        if a["trip_id"] == trip["id"] and a["status"] == "ASSIGNED":
            a["status"] = "COMPLETED"
            touch(a)

    # Recompute any DRAFT statement covering the completion period
    recompute_draft_statements_for_date(trip["aircraft_id"], completion_date)


def void_trip(trip):
    """COMPLETED -> VOID cascade (PRD §3.4)."""
    aircraft = db.aircraft[trip["aircraft_id"]]

    completion_period_date = None
    if trip.get("_completed_at") is not None:
        completion_period_date = trip["_completed_at"].date().isoformat()

    if trip["block_hours_actual"] is not None:
        aircraft["total_time_hours"] = float(
            Decimal(str(aircraft["total_time_hours"])) - Decimal(str(trip["block_hours_actual"]))
        )
        touch(aircraft)

    accrual_id = trip.get("_accrual_expense_id")
    if accrual_id is not None:
        expense = db.expenses.get(accrual_id)
        if expense is not None and expense["status"] == "POSTED":
            expense["status"] = "VOID"
            touch(expense)

    trip["owner_credit_cents"] = None
    trip["charter_shortfall_cents"] = None
    trip["status"] = "VOID"
    touch(trip)

    if completion_period_date:
        recompute_draft_statements_for_date(trip["aircraft_id"], completion_period_date)


def release_trip_assignments(trip):
    """Every ASSIGNED DutyAssignment of the trip transitions to RELEASED."""
    for a in db.assignments.values():
        if a["trip_id"] == trip["id"] and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            touch(a)


def cancel_trip(trip):
    """REQUESTED/APPROVED/SCHEDULED -> CANCELLED with assignment release."""
    trip["status"] = "CANCELLED"
    touch(trip)
    release_trip_assignments(trip)
