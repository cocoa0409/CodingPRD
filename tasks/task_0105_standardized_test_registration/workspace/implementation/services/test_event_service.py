"""TestEvent + TestCenter + TestCenterCapacity services."""

from datetime import timedelta
from typing import Optional

import db
from clock import now
from config import (
    TEST_SESSION_HOURS,
    TEST_TYPES,
)
from errors import (
    err_deadline_extension_exhausted,
    err_invalid_registration_state,
    err_invalid_request,
    err_test_center_not_found,
    err_test_center_time_conflict,
    err_test_event_not_found,
)
from response import iso_utc_ms, parse_iso_utc
from services.common import occ_check, parse_iso_or_400


def get_test_event_or_404(test_event_id: str) -> dict:
    e = db.test_events.get(test_event_id)
    if e is None:
        raise err_test_event_not_found()
    return e


def get_test_center_or_404(test_center_id: str) -> dict:
    c = db.test_centers.get(test_center_id)
    if c is None:
        raise err_test_center_not_found()
    return c


def create_test_event(body: dict) -> dict:
    test_type = body.get("test_type")
    if test_type not in TEST_TYPES:
        raise err_invalid_request("test_type must be one of SAT, ACT, AP, CLEP")
    form_code = body.get("form_code")
    if not isinstance(form_code, str) or not form_code:
        raise err_invalid_request("form_code is required")
    subject = body.get("subject")
    if test_type in ("AP", "CLEP"):
        if not isinstance(subject, str) or not subject:
            raise err_invalid_request("subject is required for AP/CLEP test events")
    else:
        # SAT/ACT: subject must be null/absent.
        if subject is not None:
            subject = None

    # Required datetime fields
    test_date = parse_iso_or_400(body.get("test_date"), "test_date")
    registration_deadline = parse_iso_or_400(body.get("registration_deadline"), "registration_deadline")
    late_registration_deadline = parse_iso_or_400(
        body.get("late_registration_deadline"), "late_registration_deadline"
    )
    score_release_date = parse_iso_or_400(body.get("score_release_date"), "score_release_date")

    base_fee_cents = body.get("base_fee_cents")
    late_fee_cents = body.get("late_fee_cents")
    if not isinstance(base_fee_cents, int) or base_fee_cents < 0:
        raise err_invalid_request("base_fee_cents must be a non-negative integer")
    if not isinstance(late_fee_cents, int) or late_fee_cents < 0:
        raise err_invalid_request("late_fee_cents must be a non-negative integer")

    e = db.common_create()
    e.update(
        {
            "test_type": test_type,
            "form_code": form_code,
            "subject": subject,
            "test_date": iso_utc_ms(test_date),
            "registration_deadline": iso_utc_ms(registration_deadline),
            "late_registration_deadline": iso_utc_ms(late_registration_deadline),
            "score_release_date": iso_utc_ms(score_release_date),
            "base_fee_cents": base_fee_cents,
            "late_fee_cents": late_fee_cents,
            "status": "REGISTRATION_OPEN",
        }
    )
    db.test_events.insert(e)
    db.deadline_extensions_used[e["id"]] = False
    # Run a fresh status check in case the clock is already past the deadlines.
    _apply_time_gated_transitions(e)
    return e


def list_test_events(test_type: Optional[str], status: Optional[str]):
    items = db.test_events.all()
    if test_type:
        items = [e for e in items if e["test_type"] == test_type]
    if status:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    return items


def _apply_time_gated_transitions(e: dict):
    """If the logical clock has crossed deadlines, advance the event status."""
    current_now = now()
    changed = False
    status = e["status"]
    test_date = parse_iso_utc(e["test_date"])
    late_reg_deadline = parse_iso_utc(e["late_registration_deadline"])
    score_release = parse_iso_utc(e["score_release_date"])
    session_end = test_date + timedelta(hours=TEST_SESSION_HOURS)

    # REGISTRATION_OPEN → REGISTRATION_CLOSED
    if status == "REGISTRATION_OPEN" and current_now >= late_reg_deadline:
        e["status"] = "REGISTRATION_CLOSED"
        status = e["status"]
        changed = True

    # REGISTRATION_CLOSED → SCORES_PENDING (requires a sweep)
    if status == "REGISTRATION_CLOSED" and current_now >= session_end and db.sweep_called_after_test_date.get(e["id"]):
        _move_closed_to_scores_pending(e)
        status = e["status"]
        changed = True

    # SCORES_PENDING → COMPLETED
    if status == "SCORES_PENDING" and current_now >= score_release:
        e["status"] = "COMPLETED"
        changed = True

    if changed:
        db.touch(e)


def advance_clock_for_all_events():
    for e in db.test_events.all():
        _apply_time_gated_transitions(e)


def _move_closed_to_scores_pending(e: dict):
    """Side effects per §3.1: cancel remaining STANDBY (full refund), CHECKED_IN → COMPLETED."""
    from services.refund_service import build_refund_transaction

    affected_pairs = set()
    for r in db.registrations.all():
        if r["test_event_id"] != e["id"]:
            continue
        if r["status"] == "STANDBY":
            # Cancel with SELF_INITIATED + full refund equal to original amount_charged_cents.
            r["status"] = "CANCELLED"
            r["registration_channel"] = "SELF_INITIATED"
            full_refund_amount = r["amount_charged_cents"]
            tx = build_refund_transaction(
                registration_id=r["id"],
                amount_cents=full_refund_amount,
                tier_label="FULL",
                refund_channel="SELF_INITIATED",
            )
            db.refund_transactions.insert(tx)
            r["amount_refunded_cents"] = sum(
                t["amount_cents"] for t in db.refund_transactions.all() if t["registration_id"] == r["id"]
            )
            r["amount_retained_cents"] = r["amount_charged_cents"] - r["amount_refunded_cents"]
            db.touch(r)
            affected_pairs.add((r["test_event_id"], r["test_center_id"]))
        elif r["status"] == "CHECKED_IN":
            r["status"] = "COMPLETED"
            db.touch(r)
            affected_pairs.add((r["test_event_id"], r["test_center_id"]))

    e["status"] = "SCORES_PENDING"
    db.touch(e)

    from services.capacity_service import reconcile_capacity

    for ev_id, c_id in affected_pairs:
        reconcile_capacity(ev_id, c_id)


def extend_deadline(test_event_id: str, body: dict) -> dict:
    e = get_test_event_or_404(test_event_id)
    occ_check(e, body.get("version"))
    if db.deadline_extensions_used.get(e["id"]):
        raise err_deadline_extension_exhausted()
    if e["status"] != "REGISTRATION_CLOSED":
        raise err_invalid_registration_state("Event is not in REGISTRATION_CLOSED")

    new_deadline_raw = body.get("new_late_registration_deadline")
    new_deadline = parse_iso_or_400(new_deadline_raw, "new_late_registration_deadline")
    if new_deadline <= now():
        raise err_invalid_request("new_late_registration_deadline must be in the future")

    e["status"] = "REGISTRATION_OPEN"
    e["late_registration_deadline"] = iso_utc_ms(new_deadline)
    db.deadline_extensions_used[e["id"]] = True
    db.touch(e)
    return e


# ------------------------- TestCenter -------------------------


def create_test_center(body: dict) -> dict:
    name = body.get("name")
    address = body.get("address")
    state_code = body.get("state_code")
    timezone_val = body.get("timezone")
    for field, label in (
        (name, "name"),
        (address, "address"),
        (state_code, "state_code"),
        (timezone_val, "timezone"),
    ):
        if not isinstance(field, str) or not field:
            raise err_invalid_request(f"{label} is required")
    if len(state_code) != 2:
        raise err_invalid_request("state_code must be a two-letter US state code")

    c = db.common_create()
    c.update(
        {
            "name": name,
            "address": address,
            "state_code": state_code,
            "timezone": timezone_val,
            "status": "ACTIVE",
        }
    )
    db.test_centers.insert(c)
    return c


def list_test_centers():
    items = db.test_centers.all()
    items.sort(key=lambda x: x["created_at"])
    return items


# ------------------------- Capacity -------------------------


def allocate_capacity(test_event_id: str, body: dict) -> dict:
    e = get_test_event_or_404(test_event_id)
    test_center_id = body.get("test_center_id")
    if not isinstance(test_center_id, str) or not test_center_id:
        raise err_invalid_request("test_center_id is required")
    get_test_center_or_404(test_center_id)

    total_capacity = body.get("total_capacity")
    accommodation_capacity = body.get("accommodation_capacity")
    if not isinstance(total_capacity, int) or total_capacity < 0:
        raise err_invalid_request("total_capacity must be a non-negative integer")
    if not isinstance(accommodation_capacity, int) or accommodation_capacity < 0:
        raise err_invalid_request("accommodation_capacity must be a non-negative integer")
    if accommodation_capacity > total_capacity:
        raise err_invalid_request("accommodation_capacity cannot exceed total_capacity")

    # (test_event_id, test_center_id) is unique
    from services.capacity_service import find_capacity_row

    if find_capacity_row(test_event_id, test_center_id):
        raise err_invalid_request("Capacity already allocated for this (event, center)")

    # Time conflict check: no two TestEvents on the same TestCenter whose
    # [test_date, test_date + TEST_SESSION_HOURS] intervals overlap.
    new_start = parse_iso_utc(e["test_date"])
    new_end = new_start + timedelta(hours=TEST_SESSION_HOURS)
    for cap in db.test_center_capacities.all():
        if cap["test_center_id"] != test_center_id:
            continue
        other_event = db.test_events.get(cap["test_event_id"])
        if not other_event:
            continue
        other_start = parse_iso_utc(other_event["test_date"])
        other_end = other_start + timedelta(hours=TEST_SESSION_HOURS)
        # Closed-interval overlap: a <= other_end AND other_start <= b
        if new_start <= other_end and other_start <= new_end:
            raise err_test_center_time_conflict()

    cap = db.common_create()
    cap.update(
        {
            "test_event_id": test_event_id,
            "test_center_id": test_center_id,
            "total_capacity": total_capacity,
            "accommodation_capacity": accommodation_capacity,
            "confirmed_seats_used": 0,
            "accommodation_seats_used": 0,
            "standby_seats_pending": 0,
            "available_seats": total_capacity,
        }
    )
    db.test_center_capacities.insert(cap)
    return cap


def list_capacities_for_event(test_event_id: str):
    get_test_event_or_404(test_event_id)
    items = [c for c in db.test_center_capacities.all() if c["test_event_id"] == test_event_id]
    items.sort(key=lambda x: x["created_at"])
    return items
