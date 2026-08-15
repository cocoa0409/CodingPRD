"""Logical-clock sweep battery (PRD §2.4) — runs on every clock pin.

Order: lease EXPIRING sweep -> lease terminal transitions (RENEWED/TERMINATED/
EXPIRED/HOLDOVER) -> option window openings (+ reminder cascades) -> reminder
firing -> option lapse sweep -> assessment finalization -> arbitration freeze ->
holdover accrual recompute.
"""
from datetime import timedelta

from db import db
from services.core import (
    touch, refresh, lease_options, lease_amendments, parse_date_value, parse_dt,
    fmt_date_midnight, fmt_dt, spawn_reminder_cascade, lapse_option,
    supersede_nonterminal_options, transition_lease_renewed,
    transition_lease_terminated, try_complete_exercise,
    compute_holdover_accrual, TIER_RANK,
)


def run_clock_sweep(now):
    clock_date = now.date()
    fired_ids = []
    lapsed_ids = []
    holdover_ids = []

    # --- 1. Lease sweep: ACTIVE -> EXPIRING (expiration-180d <= clock < expiration)
    for lease in list(db["leases"].values()):
        if lease["status"] != "ACTIVE":
            continue
        exp = parse_date_value(lease["expiration_date"])
        if exp - timedelta(days=180) <= clock_date < exp:
            lease["status"] = "EXPIRING"
            touch(lease)

    # --- 2. Lease terminal transitions for ACTIVE/EXPIRING leases
    for lease in list(db["leases"].values()):
        if lease["status"] not in ("ACTIVE", "EXPIRING"):
            continue
        opts = lease_options(lease["id"])
        exp = parse_date_value(lease["expiration_date"])
        renewed = next(
            (o for o in opts
             if o["option_type"] == "RENEWAL" and o["status"] == "EXERCISED"
             and parse_date_value(o["target_commencement_date"]) <= clock_date),
            None,
        )
        terminated = next(
            (o for o in opts
             if o["option_type"] == "TERMINATION" and o["status"] == "EXERCISED"
             and parse_date_value(o["target_commencement_date"]) <= clock_date),
            None,
        )
        if renewed is not None:
            transition_lease_renewed(lease, renewed)
        elif terminated is not None:
            transition_lease_terminated(lease, terminated)
        elif clock_date > exp:
            if lease.get("_vacate_requested"):
                # Tenant vacated on time: EXPIRED, options SUPERSEDED, no penalties
                lease["status"] = "EXPIRED"
                touch(lease)
                supersede_nonterminal_options(lease["id"])
            else:
                has_exercised_renewal = any(
                    o["option_type"] == "RENEWAL" and o["status"] == "EXERCISED"
                    for o in opts
                )
                has_executed_renewal_amendment = any(
                    a["status"] == "EXECUTED"
                    and a["kind"] in ("RENEWAL_TERM", "EXPANSION_TERM")
                    for a in lease_amendments(lease["id"])
                )
                if not has_exercised_renewal and not has_executed_renewal_amendment:
                    # HOLDOVER entry — backdated legal start = expiration + 1 day
                    lease["status"] = "HOLDOVER"
                    lease["holdover_entered_at"] = fmt_date_midnight(exp + timedelta(days=1))
                    touch(lease)
                    holdover_ids.append(lease["id"])
                    for o in opts:
                        if o["status"] in ("AVAILABLE", "WINDOW_OPEN"):
                            lapse_option(o, now)
                            lapsed_ids.append(o["id"])

    # --- 3. Option window openings (parent lease ACTIVE or EXPIRING)
    for option in list(db["options"].values()):
        if option["status"] != "AVAILABLE":
            continue
        lease = db["leases"].get(option["lease_id"])
        if lease is None or lease["status"] not in ("ACTIVE", "EXPIRING"):
            continue
        open_d = parse_date_value(option["notice_window_open_date"])
        close_d = parse_date_value(option["notice_window_close_date"])
        if open_d <= clock_date <= close_d:
            option["status"] = "WINDOW_OPEN"
            refresh(option)
            spawn_reminder_cascade(option)

    # --- 4. Reminder firing (chronological; ties by tier severity then contact created_at)
    due = []
    for r in db["reminders"].values():
        if r["status"] != "PENDING":
            continue
        if parse_dt(r["scheduled_for"]) > now:
            continue
        option = db["options"].get(r["option_id"])
        if option is not None and option["status"] == "IN_ARBITRATION":
            continue  # reminder firing suspended while the option is in arbitration
        contact = db["contacts"].get(r["contact_id"])
        if contact is None or not contact.get("is_active", True):
            continue
        due.append((r, contact))
    due.sort(key=lambda rc: (
        parse_dt(rc[0]["scheduled_for"]),
        TIER_RANK[rc[0]["tier"]],
        rc[1]["created_at"],
        rc[1]["_seq"],
        rc[0]["_seq"],
    ))
    for r, _contact in due:
        r["status"] = "SENT"
        r["sent_at"] = fmt_dt(now)
        touch(r)
        fired_ids.append(r["id"])

    # --- 5. Lapse sweep: past close date, not EXERCISED/WITHDRAWN/IN_ARBITRATION/SUPERSEDED
    for option in list(db["options"].values()):
        if option["status"] not in ("AVAILABLE", "WINDOW_OPEN", "NOTICE_SENT"):
            continue
        close_d = parse_date_value(option["notice_window_close_date"])
        if clock_date > close_d:
            lapse_option(option, now)
            lapsed_ids.append(option["id"])

    # --- 6. Assessment finalization: PROVISIONAL undisputed, > 15 calendar days old
    for m in list(db["assessments"].values()):
        if m["status"] != "PROVISIONAL":
            continue
        if clock_date > m["_created_date"] + timedelta(days=15):
            m["status"] = "FINAL"
            m["determined_rent_cents"] = m["provisional_rent_cents"]
            touch(m)
            option = db["options"].get(m["option_id"])
            if option is not None:
                try_complete_exercise(option, now)

    # --- 7. Arbitration freeze: OPEN cases past their submission close date
    for case in list(db["arbitrations"].values()):
        if case["status"] == "OPEN" and clock_date > parse_date_value(case["submission_close_date"]):
            case["status"] = "SUBMISSIONS_FROZEN"
            touch(case)

    # --- 8. Holdover accrual recompute on every HOLDOVER lease
    for lease in list(db["leases"].values()):
        if lease["status"] != "HOLDOVER":
            continue
        acc = compute_holdover_accrual(lease, clock_date)
        if acc != lease["accrued_holdover_rent_cents"]:
            lease["accrued_holdover_rent_cents"] = acc
            touch(lease)

    return fired_ids, lapsed_ids, holdover_ids
