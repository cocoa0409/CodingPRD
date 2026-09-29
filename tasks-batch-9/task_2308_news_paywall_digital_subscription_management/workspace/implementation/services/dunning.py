"""The dunning ladder, the card updater and the final-decline cascade (PRD 3.6)."""
from datetime import timedelta

import config
from clock import clock, parse_date
from db import db, new_entity
from response import mark_created, touch
from services import engagement
from services.derive import (
    group_seats,
    invoice_attempts,
    max_payment_attempts,
)
from services.holds import release_terminal_holds
from services.pricing import recompute_next_price


def next_attempt_no(invoice):
    return len(invoice_attempts(invoice["id"])) + 1


def compute_is_final(outcome, attempt_no, max_attempts):
    if outcome == "HARD_DECLINE":
        return True
    return outcome == "SOFT_DECLINE" and attempt_no >= max_attempts


def retry_offset(attempt_no):
    offsets = config.DUNNING_RETRY_OFFSET_DAYS
    return offsets[min(attempt_no, len(offsets)) - 1]


def _advance_paid_through(sub, plan, from_cycle_start=False):
    if from_cycle_start or not sub.get("paid_through_on"):
        base = parse_date(sub["cycle_start_on"])
    else:
        base = parse_date(sub["paid_through_on"])
    sub["paid_through_on"] = (base + timedelta(days=plan["cycle_days"])).isoformat()


def record_attempt(invoice, sub, plan, reader, outcome, amount_cents, decline_code):
    attempt_no = next_attempt_no(invoice)
    max_attempts = max_payment_attempts(sub)
    is_final = compute_is_final(outcome, attempt_no, max_attempts)

    attempt = new_entity(common_fields=False)
    attempt.update(
        {
            "invoice_id": invoice["id"],
            "attempt_no": attempt_no,
            "outcome": outcome,
            "amount_cents": amount_cents,
            "decline_code": None if outcome == "SUCCEEDED" else decline_code,
            "is_final": is_final,
            "attempted_on": clock.date().isoformat(),
            "card_last4_snapshot": reader.get("card_last4") if reader else None,
        }
    )
    db.payment_attempts[attempt["id"]] = attempt
    mark_created(attempt)

    if outcome == "SUCCEEDED":
        _apply_success(invoice, sub, plan, reader)
    elif is_final:
        _apply_final_decline(invoice, sub, plan, reader)
    else:
        _apply_soft_decline(invoice, sub, plan, reader, attempt_no)
    return attempt


def _apply_success(invoice, sub, plan, reader):
    was_past_due = invoice["status"] == "PAST_DUE"
    activating = (
        invoice["status"] == "OPEN"
        and invoice["cycle_index"] == 1
        and sub["lifecycle_status"] == "PENDING_ACTIVATION"
    )
    invoice["status"] = "PAID"
    invoice["paid_on"] = clock.date().isoformat()
    touch(invoice)

    if activating:
        sub["lifecycle_status"] = "ACTIVE"
        _advance_paid_through(sub, plan, from_cycle_start=True)
        if plan["bundle_type"] == "PRINT_DIGITAL" and sub["print_fulfillment_status"] == "NOT_APPLICABLE":
            sub["print_fulfillment_status"] = "SCHEDULED"
    else:
        _advance_paid_through(sub, plan)

    if sub["dunning_status"] == "RETRYING" or was_past_due:
        sub["dunning_status"] = "RECOVERED"
        sub["next_retry_on"] = None

    recompute_next_price(sub, plan)
    touch(sub)

    if reader is not None:
        engagement.reband_churn(reader)
        touch(reader)


def _apply_soft_decline(invoice, sub, plan, reader, attempt_no):
    if invoice["status"] == "OPEN":
        invoice["status"] = "PAST_DUE"
        touch(invoice)

    first_failure = sub["dunning_status"] == "CURRENT"
    if sub.get("dunning_first_failed_on") is None:
        sub["dunning_first_failed_on"] = clock.date().isoformat()
    sub["dunning_status"] = "RETRYING"
    sub["next_retry_on"] = (
        parse_date(sub["dunning_first_failed_on"]) + timedelta(days=retry_offset(attempt_no))
    ).isoformat()
    recompute_next_price(sub, plan)
    touch(sub)

    if reader is not None:
        if first_failure and reader.get("card_updater_status") == "NOT_APPLICABLE":
            if reader.get("card_updater_registered") and engagement.card_status(reader) == "EXPIRED":
                reader["card_updater_status"] = "PENDING"
            else:
                reader["card_updater_status"] = "UNAVAILABLE"
        engagement.reband_churn(reader)
        touch(reader)


def _apply_final_decline(invoice, sub, plan, reader):
    """The five-hop chain of PRD 3.6."""
    # hop 2
    invoice["status"] = "WRITTEN_OFF"
    touch(invoice)

    # hop 3
    sub["dunning_status"] = "FAILED_FINAL"
    sub["next_retry_on"] = None
    if sub["lifecycle_status"] not in config.LIFECYCLE_TERMINAL:
        sub["lifecycle_status"] = "CANCELLED_NONPAY"
        sub["access_until"] = clock.date().isoformat()
    recompute_next_price(sub, plan)
    touch(sub)

    # hop 4
    release_terminal_holds(sub)
    group = None
    if sub.get("group_account_id"):
        group = db.group_accounts.get(sub["group_account_id"])
    if group is not None:
        group["status"] = "SUSPENDED"
        for seat in group_seats(group["id"]):
            if seat["status"] in config.SEAT_OCCUPYING_STATUSES:
                seat["status"] = "RECLAIMED"
                seat["ends_on"] = clock.date().isoformat()
                touch(seat)
                seat_reader = db.readers.get(seat["reader_id"])
                if seat_reader is not None and seat_reader["id"] != (reader or {}).get("id"):
                    touch(seat_reader)
        # hop 5: the reclaimed seats leave the occupancy measure
        touch(group)

    # hop 5
    if reader is not None:
        engagement.reband_churn(reader)
        touch(reader)


def card_updater_sweep(sub, reader):
    """DUNNING pass: refresh cards for RETRYING subscriptions with a PENDING updater."""
    if sub["dunning_status"] != "RETRYING":
        return False
    if reader is None or reader.get("card_updater_status") != "PENDING":
        return False
    if reader.get("card_updater_registered"):
        if reader.get("card_exp_year") is not None:
            reader["card_exp_year"] = reader["card_exp_year"] + config.CARD_UPDATER_EXTENSION_YEARS
        reader["card_updater_status"] = "UPDATED"
        touch(reader)
        return True
    reader["card_updater_status"] = "UNAVAILABLE"
    touch(reader)
    return False
