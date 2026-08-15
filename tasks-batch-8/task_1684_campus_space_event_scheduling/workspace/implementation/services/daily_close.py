"""The daily-close checkpoint (PRD 2.4).  All clock-driven state transitions
are applied in one pinned order:

  1. Term statuses advance (DRAFT->SCHEDULING, SCHEDULING->GENERAL, any open
     term->CLOSED).
  2. Rooms whose outage window has ended auto-return to service.
  3. REQUESTED events past their decision deadline expire.
  4. APPROVED events past their confirmation deadline expire (invoice VOIDED).
  5. CONFIRMED events past their check-in deadline without a check-in are
     marked NO_SHOW (strike, standing recomputation, suspension cascade).
  6. IN_PROGRESS events whose end has passed complete (final invoice).
  7. ISSUED grants past their return deadline become OVERDUE.
  8. Organization balances are recomputed (derived on read; no stored work).
"""

from datetime import timedelta

import db
from clock import clock
from constants import CHECKIN_LATE_MINUTES, SUSPENDED_NO_SHOW_COUNT
from services import invoices as invoice_service
from services.cascade import cancel_nonterminal_orders, suspension_cascade
from services.derive import derive_standing


def _advance_terms(now, counters):
    for term in db.all_of(db.terms):
        changed = False
        while True:
            status = term["status"]
            if status in ("DRAFT", "SCHEDULING", "GENERAL") and now > term["_term_end"] + timedelta(days=1):
                term["status"] = "CLOSED"
                changed = True
            elif status == "DRAFT" and now >= term["_priority_open"]:
                term["status"] = "SCHEDULING"
                changed = True
            elif status == "SCHEDULING" and now >= term["_general_open"]:
                term["status"] = "GENERAL"
                changed = True
            else:
                break
        if changed:
            db.touch(term)
            counters["terms_advanced"] += 1


def _return_rooms(now, counters):
    for room in db.all_of(db.rooms):
        if room.get("status") != "OUT_OF_SERVICE":
            continue
        outage_end = room.get("_outage_end")
        if outage_end is not None and now >= outage_end:
            # History in outage_windows is retained; only the current-outage
            # fields are cleared.
            room["status"] = "ACTIVE"
            room["outage_start_at"] = None
            room["outage_end_at"] = None
            room["_outage_start"] = None
            room["_outage_end"] = None
            db.touch(room)
            counters["rooms_returned"] += 1


def _expire_requests(now, counters):
    for event in db.all_of(db.event_reservations):
        if event.get("status") == "REQUESTED" and now > event["_decision_deadline"]:
            db.set_fields(event, status="EXPIRED")
            counters["requests_expired"] += 1


def _expire_approvals(now, counters):
    for event in db.all_of(db.event_reservations):
        if event.get("status") == "APPROVED" and now > event["_confirm_deadline"]:
            event["status"] = "EXPIRED"
            db.touch(event)
            invoice_service.void_provisional(event)
            counters["approvals_expired"] += 1


def _mark_no_shows(now, counters):
    for event in db.all_of(db.event_reservations):
        if event.get("status") != "CONFIRMED":
            continue
        if event.get("checked_in_at") is not None:
            continue
        if now <= event["_start"] + timedelta(minutes=CHECKIN_LATE_MINUTES):
            continue
        event["status"] = "NO_SHOW"
        db.touch(event)
        # Invoice finalizes: room at 100% + fulfilled service + flat 5000
        # no-show fee + deposits; no insurance surcharge.  Fulfilled orders
        # move to INVOICED; every other non-terminal order is cancelled with
        # fee_waived false.
        invoice_service.finalize_invoice(event, "NO_SHOW")
        cancel_nonterminal_orders(event, fee_waived=False)
        org = db.organizations.get(event.get("requester_org_id"))
        if org is not None:
            count_before = org.get("no_show_count", 0)
            org["no_show_count"] = count_before + 1
            db.touch(org)
            # Standing is derived from the count; the suspension cascade fires
            # in the same run that pushes the count to 3 or more.
            if count_before < SUSPENDED_NO_SHOW_COUNT and derive_standing(org) == "SUSPENDED":
                suspension_cascade(org)
                counters["orgs_suspended"] += 1
        counters["no_shows_marked"] += 1


def _complete_events(now, counters):
    for event in db.all_of(db.event_reservations):
        if event.get("status") == "IN_PROGRESS" and now >= event["_end"]:
            event["status"] = "COMPLETED"
            db.touch(event)
            # Final variant: fulfilled/invoiced service only, surcharge
            # recomputed on the final base for EXTERNAL, deposits included.
            invoice_service.finalize_invoice(event, "COMPLETED")
            cancel_nonterminal_orders(event, fee_waived=True)
            counters["events_completed"] += 1


def _overdue_grants(now, counters):
    for grant in db.all_of(db.access_grants):
        if grant.get("status") == "ISSUED" and now > grant["_return_deadline"]:
            db.set_fields(grant, status="OVERDUE")
            counters["grants_overdue"] += 1


def run_daily_close():
    now = clock.now
    counters = {
        "terms_advanced": 0,
        "rooms_returned": 0,
        "requests_expired": 0,
        "approvals_expired": 0,
        "no_shows_marked": 0,
        "events_completed": 0,
        "grants_overdue": 0,
        "orgs_suspended": 0,
    }
    _advance_terms(now, counters)       # step 1
    _return_rooms(now, counters)        # step 2
    _expire_requests(now, counters)     # step 3
    _expire_approvals(now, counters)    # step 4
    _mark_no_shows(now, counters)       # step 5
    _complete_events(now, counters)     # step 6
    _overdue_grants(now, counters)      # step 7
    # step 8: org balances are computed on read; nothing stored to recompute.
    return counters
