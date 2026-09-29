"""Billing run (PRD 3.5)."""

from db import db, parse_day, parse_instant
from services import domain


def run_billing(program, as_of_date_text):
    as_of = parse_day(as_of_date_text)

    plans = []
    for plan in db.rows("payment_plans"):
        if plan["plan_status"] != "ACTIVE":
            continue
        season_pass = db.season_passes.get(plan["season_pass_id"])
        if season_pass is None or season_pass["program_id"] != program["id"]:
            continue
        plans.append(plan)

    due = []
    for plan in plans:
        for installment in domain.plan_installments(plan["id"]):
            if installment["status"] == "SCHEDULED" and parse_day(installment["due_date"]) < as_of:
                due.append((plan, installment))
    due.sort(key=lambda pair: (pair[1]["due_date"], pair[1]["sequence_no"], pair[1]["created_at"]))

    missed_installment_count = 0
    delinquent = set()
    defaulted = set()
    suspended = set()

    for plan, installment in due:
        installment["status"] = "MISSED"
        missed_installment_count += 1
        season_pass = db.season_passes.get(plan["season_pass_id"])
        if season_pass is None:
            continue
        missed = domain.plan_counts(plan)["missed_count"]
        if missed >= 1 and season_pass["billing_status"] not in ("DELINQUENT", "DEFAULTED"):
            season_pass["billing_status"] = "DELINQUENT"
            delinquent.add(season_pass["id"])
        if (
            missed >= program["delinquency_suspension_threshold"]
            and season_pass["pass_status"] == "ACTIVE"
        ):
            season_pass["pass_status"] = "SUSPENDED"
            season_pass["suspension_count"] += 1
            suspended.add(season_pass["id"])
        if missed >= program["default_threshold"] and season_pass["billing_status"] != "DEFAULTED":
            season_pass["billing_status"] = "DEFAULTED"
            defaulted.add(season_pass["id"])

    # Reservation sweep - past-dated confirmations become no-shows.
    no_show_reservation_count = 0
    for reservation in db.rows("reservations"):
        if reservation["status"] != "CONFIRMED":
            continue
        park_day = db.park_days.get(reservation["park_day_id"])
        if park_day is None or park_day["program_id"] != program["id"]:
            continue
        if parse_day(park_day["calendar_date"]) < as_of:
            reservation["status"] = "NO_SHOW"
            no_show_reservation_count += 1

    # Reservations on or after as_of belonging to passes this run suspended.
    released_reservation_count = 0
    for pass_id in suspended:
        for reservation in domain.pass_reservations(pass_id):
            if reservation["status"] != "CONFIRMED":
                continue
            park_day = db.park_days.get(reservation["park_day_id"])
            if park_day is None:
                continue
            if parse_day(park_day["calendar_date"]) >= as_of:
                reservation["status"] = "CANCELLED_BY_SUSPENSION"
                released_reservation_count += 1

    # Stale upgrade quotes.
    expired_upgrade_order_count = 0
    for order in db.rows("upgrade_orders"):
        if order["status"] != "QUOTED":
            continue
        season_pass = db.season_passes.get(order["season_pass_id"])
        if season_pass is None or season_pass["program_id"] != program["id"]:
            continue
        if as_of >= parse_instant(order["quote_expires_at"]).date():
            order["status"] = "EXPIRED"
            expired_upgrade_order_count += 1

    return {
        "missed_installment_count": missed_installment_count,
        "delinquent_pass_count": len(delinquent),
        "defaulted_pass_count": len(defaulted),
        "suspended_pass_count": len(suspended),
        "released_reservation_count": released_reservation_count,
        "no_show_reservation_count": no_show_reservation_count,
        "expired_upgrade_order_count": expired_upgrade_order_count,
    }
