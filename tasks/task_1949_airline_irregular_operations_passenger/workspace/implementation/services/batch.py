"""Process-due batch (calculation comms_cadence_batch, PRD §3.8)."""

from datetime import datetime, timedelta, timezone

from db import db, now

from services.core import (
    booking_segments,
    post_cost_entry,
    queue_comm,
    recompute_event_affected,
    stamp_new_ledger,
    touch,
)

REMINDER_CADENCE_MINUTES = 30


def run_process_due():
    current = now()
    counts = {
        "expired_options": 0,
        "expired_vouchers": 0,
        "defaulted_elections": 0,
        "sent_count": 0,
        "reminders_sent": 0,
    }

    # Step 1: expire PROPOSED options whose legs[0] departs <= now; an OFFERED
    # case left with no PROPOSED option becomes EXPIRED.
    for opt in list(db.reaccommodation_options.values()):
        if opt["option_status"] != "PROPOSED":
            continue
        first_dep = opt["est_first_dep_utc"]
        if first_dep is not None and first_dep <= current:
            opt["option_status"] = "EXPIRED"
            touch(opt)
            counts["expired_options"] += 1
    for case in list(db.reaccommodation_cases.values()):
        if case["case_status"] != "OFFERED":
            continue
        has_proposed = any(
            o["case_id"] == case["id"] and o["option_status"] == "PROPOSED"
            for o in db.reaccommodation_options.values()
        )
        if not has_proposed:
            case["case_status"] = "EXPIRED"
            touch(case)

    # Step 2: expire ISSUED vouchers whose valid_through is before the current date.
    current_date = current.date()
    for v in list(db.vouchers.values()):
        if v["voucher_status"] != "ISSUED":
            continue
        vt = v["valid_through"]
        if vt is None:
            continue
        vt_date = datetime.strptime(vt, "%Y-%m-%d").date()
        if vt_date < current_date:
            v["voucher_status"] = "EXPIRED"
            touch(v)
            post_cost_entry(v["disruption_event_id"], "VOUCHER", v["id"],
                            "REVERSAL", -v["face_value_cents"], note="voucher expired")
            counts["expired_vouchers"] += 1

    # Step 3: default overdue elections.
    defaulted_booking_ids = set()
    for b in list(db.bookings.values()):
        if b["compensation_status"] != "ELIGIBLE_PENDING":
            continue
        if b["election_deadline"] is None or not (b["election_deadline"] < current):
            continue
        # create PROCESSED system-default CREDIT election
        election = stamp_new_ledger({
            "booking_id": b["id"],
            "election": "CREDIT",
            "election_source": "SYSTEM_DEFAULT",
            "refund_amount_cents": b["refund_amount_cents"],
            "credit_amount_cents": b["credit_amount_cents"],
            "compensation_amount_cents": b["compensation_amount_cents"],
            "election_status": "PROCESSED",
        })
        # RefundElection is a primary resource — needs updated_at/version.
        election["updated_at"] = election["created_at"]
        election["version"] = 1
        db.refund_elections[election["id"]] = election
        # post CREDIT accrual + COMPENSATION accrual+settlement
        event_id = _event_id_for_booking(b)
        if event_id:
            post_cost_entry(event_id, "CREDIT", election["id"], "ACCRUAL",
                            election["credit_amount_cents"], note="system default credit")
            post_cost_entry(event_id, "COMPENSATION", election["id"], "ACCRUAL",
                            election["compensation_amount_cents"], note="system default compensation")
            post_cost_entry(event_id, "COMPENSATION", election["id"], "SETTLEMENT",
                            election["compensation_amount_cents"], note="system default compensation")
        b["compensation_status"] = "SETTLED"
        touch(b)
        queue_comm(b["id"], event_id, "ELECTION_DEFAULT")
        defaulted_booking_ids.add(b["id"])
        counts["defaulted_elections"] += 1

    # Step 4: send all QUEUED logs with due_at <= now.
    for log in list(db.communication_logs.values()):
        if log["log_status"] != "QUEUED":
            continue
        if log["due_at"] is not None and log["due_at"] <= current:
            log["log_status"] = "SENT"
            log["sent_at"] = current
            counts["sent_count"] += 1

    # Step 5: reminders for bookings still DISRUPTED whose latest SENT/QUEUED log
    # is older than 30 minutes; bookings defaulted in step 3 are excluded.
    for b in list(db.bookings.values()):
        if b["booking_status"] != "DISRUPTED":
            continue
        if b["id"] in defaulted_booking_ids:
            continue
        logs = [l for l in db.communication_logs.values() if l["booking_id"] == b["id"]]
        latest = None
        for l in logs:
            ts = l["sent_at"] if l["sent_at"] is not None else l["due_at"]
            if ts is None:
                continue
            if latest is None or ts > latest:
                latest = ts
        needs = False
        if latest is None:
            needs = True
        else:
            age_min = (current - latest).total_seconds() / 60.0
            if age_min > REMINDER_CADENCE_MINUTES:
                needs = True
        if needs:
            event_id = _event_id_for_booking(b)
            queue_comm(b["id"], event_id, "REMINDER", due_at=current)
            counts["reminders_sent"] += 1
    # send the reminders just queued in this same batch
    for log in list(db.communication_logs.values()):
        if log["log_status"] == "QUEUED" and log["template"] == "REMINDER" \
                and log["due_at"] is not None and log["due_at"] <= current:
            log["log_status"] = "SENT"
            log["sent_at"] = current
            counts["sent_count"] += 1

    return counts


def _event_id_for_booking(booking):
    """The disruption event the booking's reaccommodation case belongs to."""
    for case in db.reaccommodation_cases.values():
        if case["booking_id"] == booking["id"]:
            return case["disruption_event_id"]
    # fall back to a segment's flight event
    for seg in booking_segments(booking["id"]):
        f = db.flights.get(seg["flight_id"])
        if f is not None and f["disruption_event_id"]:
            return f["disruption_event_id"]
    return None
