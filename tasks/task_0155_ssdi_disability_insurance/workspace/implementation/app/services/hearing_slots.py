"""HearingSlot lifecycle: create, list, book, hold, no-show, reschedule."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app import clock, store
from app.errors import (
    application_already_scheduled,
    application_not_found,
    bad_request,
    hearing_not_reached,
    hearing_slot_conflict,
    invalid_state,
    resource_not_found,
)
from app.util import new_uuid, parse_iso_datetime


_VALID_STATUSES = {"OPEN", "BOOKED", "HELD", "NO_SHOW", "RESCHEDULED"}


def create_slot(body: dict) -> dict:
    for f in ("alj_id", "hearing_office", "start_at", "end_at"):
        if f not in body or body[f] is None:
            raise bad_request(f"Missing required field: {f}")
    alj_id = body["alj_id"]
    office = body["hearing_office"]
    if not isinstance(alj_id, str) or not alj_id.strip():
        raise bad_request("alj_id must be a non-empty string")
    if not isinstance(office, str) or not office.strip():
        raise bad_request("hearing_office must be a non-empty string")
    start_at = parse_iso_datetime(body["start_at"], "start_at")
    end_at = parse_iso_datetime(body["end_at"], "end_at")
    if end_at - start_at != timedelta(minutes=60):
        raise bad_request("end_at must equal start_at + 60 minutes")

    now = clock.now()
    new_id = new_uuid()
    record = {
        "id": new_id,
        "alj_id": alj_id,
        "hearing_office": office,
        "start_at": start_at,
        "end_at": end_at,
        "application_id": None,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock():
        store.hearing_slots[new_id] = record
    return record


def list_slots(
    alj_id: Optional[str],
    status: Optional[str],
    from_: Optional[str],
    to: Optional[str],
) -> list[dict]:
    rows = list(store.hearing_slots.values())
    if alj_id is not None:
        rows = [r for r in rows if r["alj_id"] == alj_id]
    if status is not None:
        if status not in _VALID_STATUSES:
            raise bad_request(f"status must be one of {sorted(_VALID_STATUSES)}")
        rows = [r for r in rows if r["status"] == status]
    if from_ is not None:
        fdt = parse_iso_datetime(from_, "from")
        rows = [r for r in rows if r["start_at"] >= fdt]
    if to is not None:
        tdt = parse_iso_datetime(to, "to")
        rows = [r for r in rows if r["start_at"] <= tdt]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows


def _fetch_slot(slot_id: str) -> dict:
    slot = store.hearing_slots.get(slot_id)
    if not slot:
        raise resource_not_found(f"HearingSlot {slot_id} not found")
    return slot


def book_slot(slot_id: str, body: dict) -> dict:
    app_id = body.get("application_id")
    if not isinstance(app_id, str) or not app_id:
        raise bad_request("application_id is required")

    with store.lock():
        slot = _fetch_slot(slot_id)
        if slot["status"] != "OPEN":
            # PRD §3.7: "When two ALJ operators race to book the same OPEN
            # slot, the system serialises first-writer-wins on the slot's
            # transition; the loser is rejected with ERR_HEARING_SLOT_CONFLICT
            # at 409." The race-loser observes the slot already in BOOKED
            # (or HELD if a hold races in too) — surface that specific
            # transition-loss as the conflict error. Other non-OPEN states
            # (RESCHEDULED, NO_SHOW) remain a plain invalid-state.
            if slot["status"] in ("BOOKED", "HELD"):
                raise hearing_slot_conflict(
                    f"HearingSlot {slot_id} is already {slot['status']}; "
                    "the booking race lost"
                )
            raise invalid_state(f"HearingSlot in status {slot['status']} cannot be booked")

        application = store.applications.get(app_id)
        if not application:
            raise application_not_found(f"Application {app_id} not found")
        if application["status"] != "ALJ_PENDING":
            raise invalid_state(
                f"Booking requires Application.status == ALJ_PENDING; current is {application['status']}"
            )

        # Overlap check on same ALJ — closed-open interval [start_at, end_at).
        for other in store.hearing_slots.values():
            if other["id"] == slot_id:
                continue
            if other["alj_id"] != slot["alj_id"]:
                continue
            if other["status"] not in ("BOOKED", "HELD"):
                continue
            if _intervals_overlap(slot["start_at"], slot["end_at"], other["start_at"], other["end_at"]):
                raise hearing_slot_conflict(
                    "Overlap with another BOOKED/HELD slot for the same ALJ"
                )

        # Application not already scheduled.
        for other in store.hearing_slots.values():
            if other["id"] == slot_id:
                continue
            if other.get("application_id") == app_id and other["status"] in ("BOOKED", "HELD"):
                raise application_already_scheduled(
                    f"Application {app_id} is already booked on slot {other['id']}"
                )

        slot["application_id"] = app_id
        slot["status"] = "BOOKED"
        slot["updated_at"] = clock.now()
        slot["version"] += 1
    return slot


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    # Closed-open intervals: [a_start, a_end) and [b_start, b_end).
    return a_start < b_end and b_start < a_end


def hold_slot(slot_id: str) -> dict:
    with store.lock():
        slot = _fetch_slot(slot_id)
        if slot["status"] != "BOOKED":
            raise invalid_state(f"HearingSlot in status {slot['status']} cannot be HELD")
        now = clock.now()
        if now < slot["start_at"]:
            raise hearing_not_reached("Cannot mark held before start_at")
        slot["status"] = "HELD"
        slot["updated_at"] = now
        slot["version"] += 1
    return slot


def no_show_slot(slot_id: str) -> dict:
    with store.lock():
        slot = _fetch_slot(slot_id)
        if slot["status"] != "BOOKED":
            raise invalid_state(f"HearingSlot in status {slot['status']} cannot be NO_SHOW")
        now = clock.now()
        if now < slot["end_at"]:
            raise hearing_not_reached("Cannot mark no-show before end_at")
        slot["status"] = "NO_SHOW"
        slot["updated_at"] = now
        slot["version"] += 1
    return slot


def reschedule_slot(slot_id: str, body: dict) -> dict:
    new_slot_id = body.get("new_slot_id")
    if not isinstance(new_slot_id, str) or not new_slot_id:
        raise bad_request("new_slot_id is required")
    if new_slot_id == slot_id:
        raise bad_request("new_slot_id must differ from the source slot")

    with store.lock():
        slot = _fetch_slot(slot_id)
        if slot["status"] != "BOOKED":
            raise invalid_state(f"HearingSlot in status {slot['status']} cannot be rescheduled")
        now = clock.now()
        if now >= slot["start_at"]:
            raise hearing_not_reached("Cannot reschedule on/after start_at")

        target = store.hearing_slots.get(new_slot_id)
        if not target:
            raise resource_not_found(f"HearingSlot {new_slot_id} not found")
        if target["status"] != "OPEN":
            raise invalid_state(f"Target HearingSlot must be OPEN; got {target['status']}")

        # Closed-open overlap check on the target slot for its ALJ.
        for other in store.hearing_slots.values():
            if other["id"] in (slot_id, new_slot_id):
                continue
            if other["alj_id"] != target["alj_id"]:
                continue
            if other["status"] not in ("BOOKED", "HELD"):
                continue
            if _intervals_overlap(target["start_at"], target["end_at"], other["start_at"], other["end_at"]):
                raise hearing_slot_conflict(
                    "Target slot overlaps with another BOOKED/HELD slot for the same ALJ"
                )

        app_id = slot["application_id"]
        target["application_id"] = app_id
        target["status"] = "BOOKED"
        target["updated_at"] = now
        target["version"] += 1

        slot["application_id"] = None
        slot["status"] = "RESCHEDULED"
        slot["updated_at"] = now
        slot["version"] += 1
    return slot
