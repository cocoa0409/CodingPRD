"""Cross-entity workflow logic: assignments, pay records, cascades."""
from db import db, mint, touch
from helpers import price_pay


def create_pay_record(assignment, period, basis, variant):
    straight, ot, gross = price_pay(
        period, assignment["operator_id"], assignment["service_date"], basis
    )
    pr = mint()
    pr.update(
        {
            "daily_assignment_id": assignment["id"],
            "straight_minutes": straight,
            "overtime_minutes": ot,
            "gross_cents": gross,
            "variant": variant,
        }
    )
    db.pay_records[pr["id"]] = pr
    return pr


def create_assignment(period, operator_id, run_id, service_date, source, scheduled_minutes):
    """Create a DailyAssignment (SCHEDULED / PROVISIONAL) and price its
    PROVISIONAL pay record from scheduled_minutes at the moment of creation."""
    a = mint()
    a.update(
        {
            "sign_up_period_id": period["id"],
            "operator_id": operator_id,
            "run_id": run_id,
            "service_date": service_date,
            "source": source,
            "scheduled_minutes": scheduled_minutes,
            "actual_platform_minutes": None,
            "status": "SCHEDULED",
            "pay_status": "PROVISIONAL",
        }
    )
    db.daily_assignments[a["id"]] = a
    create_pay_record(a, period, scheduled_minutes, "PROVISIONAL")
    return a


def withdraw_run_cascade(run):
    """Withdrawing a run withdraws the SUBMITTED bids that reference it and
    cancels any still-SCHEDULED assignments against it (deleting their
    PROVISIONAL pay records)."""
    for b in db.bid_entries.values():
        if b["run_id"] == run["id"] and b["status"] == "SUBMITTED":
            b["status"] = "WITHDRAWN"
            touch(b)
    for a in db.daily_assignments.values():
        if a["run_id"] == run["id"] and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            touch(a)
            doomed = [
                pr["id"]
                for pr in db.pay_records.values()
                if pr["daily_assignment_id"] == a["id"] and pr["variant"] == "PROVISIONAL"
            ]
            for prid in doomed:
                del db.pay_records[prid]
