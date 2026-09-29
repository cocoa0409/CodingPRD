"""Fleet, dispatch, delivery outcomes and the two contagion cascades
(PRD 3.5, 3.7, 3.8).
"""

from decimal import Decimal

from core import (
    BAN_DAYS, RELIABILITY_NO_SHOW_PENALTY, RUN_HOURS, STRIKE_BAN_THRESHOLD,
    TRUCK_LOCKOUT_HOURS, clock, days, dec, hours, utc_date_string,
)
from db import (
    db, touch, sorted_by_creation, crew_of_run, lines_of_voucher,
    line_ids_of_voucher, stops_of_run, units_of_voucher, waitlist_of_client,
    referrals_of_client, agency_of_voucher, client_of_voucher,
    referral_of_voucher,
)
from services.calc import (
    compute_chargeback, recompute_agency_standing, write_final_fee,
)

AUTO_DENIAL_NOTE = "auto-denied: household placed ON_HOLD"


# --------------------------------------------------------------------------
# run_load_and_crew_feasibility  (PRD 3.7)
# --------------------------------------------------------------------------
def recompute_run(run, silent=False):
    scheduled_stops = stops_of_run(run["id"], ("SCHEDULED",))
    line_ids = set()
    for stop in scheduled_stops:
        line_ids |= line_ids_of_voucher(stop["voucher_id"])

    load = Decimal("0")
    for unit in db.inventory_items.values():
        if unit["status"] in ("RESERVED", "STAGED") and \
                unit["reserved_for_voucher_line_id"] in line_ids:
            load += dec(unit["cubic_feet"])

    confirmed = crew_of_run(run["id"], ("CONFIRMED",))
    confirmed_count = len(confirmed)
    has_driver = any(c["role_on_crew"] == "DRIVER" for c in confirmed)
    stop_count = len(scheduled_stops)

    changed = (run["load_cubic_feet"] != load
               or run["confirmed_crew_count"] != confirmed_count
               or run["has_confirmed_driver"] != has_driver
               or run["stop_count"] != stop_count)
    run["load_cubic_feet"] = load
    run["confirmed_crew_count"] = confirmed_count
    run["has_confirmed_driver"] = has_driver
    run["stop_count"] = stop_count
    if changed and not silent:
        touch(run)
    return changed


def apply_crew_auto_transition(run):
    """PLANNED -> CREWED after a confirmation, CREWED -> PLANNED after a
    withdrawal; crew churn may move the run any number of times."""
    truck = db.trucks.get(run["truck_id"])
    if truck is None:
        return
    if run["status"] == "PLANNED":
        if run["confirmed_crew_count"] >= truck["crew_minimum"] and run["has_confirmed_driver"]:
            run["status"] = "CREWED"
            touch(run)
    elif run["status"] == "CREWED":
        if run["confirmed_crew_count"] < truck["crew_minimum"] or not run["has_confirmed_driver"]:
            run["status"] = "PLANNED"
            touch(run)


# --------------------------------------------------------------------------
# Voucher returning off the road
# --------------------------------------------------------------------------
def voucher_off_road(voucher):
    """A voucher leaving SCHEDULED goes back to ALLOCATED when every line is
    still fully filled, otherwise to PARTIALLY_ALLOCATED."""
    lines = lines_of_voucher(voucher["id"])
    fully_filled = all(l["quantity_allocated"] >= l["quantity_requested"] for l in lines)
    voucher["status"] = "ALLOCATED" if fully_filled else "PARTIALLY_ALLOCATED"
    touch(voucher)


# --------------------------------------------------------------------------
# Dispatch  (PRD 3.7)
# --------------------------------------------------------------------------
def dispatch_run(run):
    run["status"] = "DISPATCHED"
    touch(run)

    for stop in stops_of_run(run["id"], ("SCHEDULED",)):
        for unit in units_of_voucher(stop["voucher_id"], ("RESERVED",)):
            unit["status"] = "STAGED"
            touch(unit)

    for assignment in crew_of_run(run["id"], ("INVITED",)):
        assignment["status"] = "NO_SHOW"
        touch(assignment)
        volunteer = db.volunteers.get(assignment["volunteer_id"])
        if volunteer is not None:
            volunteer["reliability_score"] = max(
                dec(volunteer["reliability_score"]) - RELIABILITY_NO_SHOW_PENALTY,
                Decimal("0.0"))
            touch(volunteer)

    recompute_run(run)


# --------------------------------------------------------------------------
# Bed-bug contagion chain fired by a live pest at warehouse intake (PRD 3.5)
# --------------------------------------------------------------------------
def bed_bug_intake_cascade(truck):
    if truck is None:
        return
    now = clock.now()
    # Step 1 - lock the collecting truck out.
    truck["bed_bug_lockout_until"] = now + hours(TRUCK_LOCKOUT_HOURS)
    touch(truck)

    # Step 2 - cancel that truck's PLANNED/CREWED runs on today's service date.
    today = utc_date_string(now)
    runs = [r for r in db.delivery_runs.values()
            if r["truck_id"] == truck["id"]
            and r["status"] in ("PLANNED", "CREWED")
            and r["service_date"] == today]
    for run in sorted_by_creation(runs):
        run["status"] = "CANCELLED"
        touch(run)

        # Step 3 - cancel that run's SCHEDULED stops, chargeback stays 0.
        for stop in stops_of_run(run["id"], ("SCHEDULED",)):
            stop["status"] = "CANCELLED"
            touch(stop)
            # Step 4 - the served voucher comes back off the road with its
            # reserved stock retained (nothing was ever staged).
            voucher = db.vouchers.get(stop["voucher_id"])
            if voucher is not None and voucher["status"] == "SCHEDULED":
                voucher_off_road(voucher)

        # Step 5 - release the crew.
        for assignment in crew_of_run(run["id"]):
            if assignment["status"] == "INVITED":
                assignment["status"] = "RELEASED"
                touch(assignment)
            elif assignment["status"] == "CONFIRMED":
                assignment["status"] = "RELEASED"
                touch(assignment)
                volunteer = db.volunteers.get(assignment["volunteer_id"])
                if volunteer is not None:
                    volunteer["assigned_hours_month"] = max(
                        dec(volunteer["assigned_hours_month"]) - RUN_HOURS, Decimal("0.0"))
                    touch(volunteer)

        recompute_run(run)


# --------------------------------------------------------------------------
# Household contagion chains (PRD 3.8)
# --------------------------------------------------------------------------
def _cancel_waiting_entries(client):
    for entry in waitlist_of_client(client["id"], ("WAITING",)):
        entry["status"] = "CANCELLED"
        touch(entry)


def no_show_contagion(client):
    now = clock.now()
    # Step 1
    client["no_show_strikes"] += 1
    touch(client)
    # Step 2 - only when the raised strike count reaches the ban threshold.
    if client["no_show_strikes"] >= STRIKE_BAN_THRESHOLD:
        client["status"] = "ON_HOLD"
        client["delivery_ban_until"] = now + days(BAN_DAYS)
        # Step 3 - only because the household has just gone ON_HOLD.
        for referral in referrals_of_client(client["id"], ("SUBMITTED", "RETURNED")):
            referral["status"] = "DENIED"
            referral["review_note"] = AUTO_DENIAL_NOTE
            touch(referral)
        _cancel_waiting_entries(client)


def pest_at_residence(client, truck):
    now = clock.now()
    client["bed_bug_status"] = "CONFIRMED"
    client["bed_bug_confirmed_at"] = now
    client["status"] = "ON_HOLD"
    touch(client)
    _cancel_waiting_entries(client)
    if truck is not None:
        truck["bed_bug_lockout_until"] = now + hours(TRUCK_LOCKOUT_HOURS)
        touch(truck)


# --------------------------------------------------------------------------
# Delivery outcome  (PRD 3.8)
# --------------------------------------------------------------------------
def record_outcome(stop, outcome, pest_observed):
    run = db.delivery_runs[stop["run_id"]]
    voucher = db.vouchers[stop["voucher_id"]]
    client = client_of_voucher(voucher)
    agency = agency_of_voucher(voucher)
    referral = referral_of_voucher(voucher)
    truck = db.trucks.get(run["truck_id"])

    stop["pest_observed_at_residence"] = bool(pest_observed)
    stop["outcome_recorded_at"] = clock.now()

    if outcome == "DELIVERED":
        stop["status"] = "DELIVERED"
        for unit in units_of_voucher(voucher["id"], ("STAGED",)):
            unit["status"] = "DELIVERED"
            touch(unit)
        voucher["status"] = "DELIVERED"
        write_final_fee(voucher, run)
        touch(voucher)
        client["lifetime_vouchers_delivered"] += 1
        touch(client)
        if referral is not None and referral["status"] == "APPROVED":
            referral["status"] = "FULFILLED"
            touch(referral)
    else:
        # The charge reads quantity_allocated as it stood before this request
        # touched any stock.
        chargeback = compute_chargeback(voucher, outcome)
        stop["status"] = outcome
        stop["chargeback_cents"] = chargeback
        if chargeback and agency is not None:
            agency["no_show_credits_owed_cents"] += chargeback
            touch(agency)
        for unit in units_of_voucher(voucher["id"], ("STAGED",)):
            unit["status"] = "RESERVED"
            touch(unit)
        voucher_off_road(voucher)
        if outcome == "NO_SHOW":
            no_show_contagion(client)

    touch(stop)

    if bool(pest_observed) and outcome in ("DELIVERED", "REFUSED"):
        pest_at_residence(client, truck)

    if outcome in ("NO_SHOW", "REFUSED") and agency is not None:
        recompute_agency_standing(agency)

    recompute_run(run)
    if run["status"] == "DISPATCHED" and not stops_of_run(run["id"], ("SCHEDULED",)):
        run["status"] = "COMPLETED"
        touch(run)
