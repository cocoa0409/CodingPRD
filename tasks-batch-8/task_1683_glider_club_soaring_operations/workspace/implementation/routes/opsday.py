"""Ops-day close: epoch advance sweeping dues, currency, no-shows, roster."""

from flask import Blueprint

import db
from middleware import auth, require_role
from response import success
from services import (
    ARREARS_THRESHOLD_CENTS,
    DUTY_NO_SHOW_FEE_CENTS,
    NO_SHOW_FEE_CENTS,
    currency_failure_reason,
    ground_aircraft,
    suspend_member,
    touch,
)
from util import sort_items

bp = Blueprint("opsday", __name__)


@bp.post("/soaring/ops-day/close")
def close_ops_day():
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    at = db.now()
    today = db.today_start()

    # --- 1. Monthly dues posting (first close of the UTC month only) -------
    dues_posted_count = 0
    month_key = "%04d-%02d" % (at.year, at.month)
    if month_key not in db.POSTED_MONTHS:
        db.POSTED_MONTHS.add(month_key)
        members = sort_items(db.STORE["members"].values())
        for member in members:
            if member["status"] not in ("ACTIVE", "SUSPENDED"):
                continue
            if member["pending_dues_cents"] != 0:
                # Prorated tier-change charge replaces the forward debit.
                member["account_balance_cents"] += member["pending_dues_cents"]
                member["pending_dues_cents"] = 0
            else:
                tier = db.STORE["tiers"].get(member["tier_id"])
                dues = tier["monthly_dues_cents"] if tier else 0
                member["account_balance_cents"] += dues
            touch(member)
            dues_posted_count += 1
        # Arrears rule bites immediately after posting.
        for member in members:
            if (
                member["status"] == "ACTIVE"
                and member["account_balance_cents"] >= ARREARS_THRESHOLD_CENTS
            ):
                suspend_member(member, "ARREARS")

    # --- 2. Fleet currency sweep -------------------------------------------
    aircraft_grounded_ids = []
    for aircraft in sort_items(db.STORE["aircraft"].values()):
        if aircraft["status"] != "AIRWORTHY":
            continue
        reason = currency_failure_reason(aircraft, at)
        if reason is not None:
            ground_aircraft(aircraft, reason)
            aircraft_grounded_ids.append(aircraft["id"])

    # --- 3. Reservation no-shows -------------------------------------------
    no_show_reservation_ids = []
    for reservation in sort_items(db.STORE["reservations"].values()):
        if reservation["status"] == "BOOKED" and reservation["end_at"] < at:
            reservation["status"] = "NO_SHOW"
            touch(reservation)
            member = db.STORE["members"].get(reservation["member_id"])
            if member is not None:
                member["account_balance_cents"] += NO_SHOW_FEE_CENTS
                touch(member)
            no_show_reservation_ids.append(reservation["id"])

    # --- 4. Duty roster finalization ---------------------------------------
    duty_finalized_ids = []
    for slot in sort_items(db.STORE["duty_slots"].values()):
        if slot["duty_date"] >= today:
            continue
        if slot["status"] == "CONFIRMED":
            slot["status"] = "COMPLETED"
            touch(slot)
            duty_finalized_ids.append(slot["id"])
        elif slot["status"] == "ASSIGNED":
            slot["status"] = "NO_SHOW"
            touch(slot)
            member = db.STORE["members"].get(slot["member_id"])
            if member is not None:
                member["account_balance_cents"] += DUTY_NO_SHOW_FEE_CENTS
                touch(member)
            duty_finalized_ids.append(slot["id"])

    return success(
        {
            "dues_posted_count": dues_posted_count,
            "aircraft_grounded_ids": aircraft_grounded_ids,
            "no_show_reservation_ids": no_show_reservation_ids,
            "duty_finalized_ids": duty_finalized_ids,
        },
        "object",
        200,
    )
