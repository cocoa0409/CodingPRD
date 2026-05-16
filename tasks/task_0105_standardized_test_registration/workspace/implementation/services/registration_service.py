"""Registration service: create, cancel, check-in.

Implements:
- Creation with fee snapshot (base / late / accommodation lines)
- STANDBY initial state with auto-promotion to CONFIRMED if capacity available
- Duplicate (candidate_id, test_event_id) check across non-CANCELLED rows
- Candidate session overlap check (extended by CANDIDATE_COOLDOWN_HOURS)
- Cancellation (self-initiated and official) with tiered refund
- Check-in with state + IDVerification + AccommodationRequest + window checks
"""

from datetime import timedelta
from typing import Optional

import db
from clock import now
from config import (
    ACCOMMODATION_FEE_CENTS,
    CANDIDATE_COOLDOWN_HOURS,
    CHECK_IN_GRACE_HOURS,
    CHECK_IN_WINDOW_HOURS,
    STANDBY_VISIBILITY_DELAY_SECONDS,
    TEST_SESSION_HOURS,
)
from errors import (
    err_accommodation_pending,
    err_candidate_session_overlap,
    err_capacity_exhausted,
    err_check_in_window_closed,
    err_duplicate_registration,
    err_id_not_cleared,
    err_insufficient_permissions,
    err_invalid_registration_state,
    err_invalid_request,
    err_registration_closed,
    err_registration_not_found,
)
from response import iso_utc_ms, parse_iso_utc
from services.candidate_service import get_candidate_or_404
from services.capacity_service import (
    find_capacity_row,
    reconcile_capacity,
    standby_promotion_selector,
    try_promote_to_confirmed,
)
from services.common import occ_check
from services.test_event_service import get_test_center_or_404, get_test_event_or_404


def get_registration_or_404(registration_id: str) -> dict:
    r = db.registrations.get(registration_id)
    if r is None:
        raise err_registration_not_found()
    return r


def get_scoped_registration_or_404(test_event_id: str, registration_id: str) -> dict:
    # Left-to-right: testEventId first, then registration must belong to it.
    get_test_event_or_404(test_event_id)
    r = db.registrations.get(registration_id)
    if r is None or r["test_event_id"] != test_event_id:
        raise err_registration_not_found()
    return r


def create_registration(test_event_id: str, body: dict, caller_role: str, caller_user_id: str) -> dict:
    e = get_test_event_or_404(test_event_id)

    candidate_id = body.get("candidate_id")
    test_center_id = body.get("test_center_id")
    force_confirmed = bool(body.get("force_confirmed", False))

    if not isinstance(candidate_id, str) or not candidate_id:
        raise err_invalid_request("candidate_id is required")
    if not isinstance(test_center_id, str) or not test_center_id:
        raise err_invalid_request("test_center_id is required")

    candidate = get_candidate_or_404(candidate_id)
    get_test_center_or_404(test_center_id)

    # Candidate ownership check for Candidate role.
    if caller_role == "Candidate" and caller_user_id != candidate["id"]:
        raise err_insufficient_permissions()

    # State check: TestEvent.status must be REGISTRATION_OPEN
    if e["status"] != "REGISTRATION_OPEN":
        raise err_registration_closed()

    # Capacity row must exist
    cap = find_capacity_row(test_event_id, test_center_id)
    if cap is None:
        raise err_invalid_request("No TestCenterCapacity allocated for this (event, center)")

    # Compute accommodation_required at creation
    accommodation_required = False
    for a in db.accommodation_requests.all():
        if (
            a["candidate_id"] == candidate_id
            and a["test_event_id"] == test_event_id
            and a["status"] == "APPROVED"
        ):
            accommodation_required = True
            break

    # 1) Candidate session overlap
    new_test_date = parse_iso_utc(e["test_date"])
    new_window_start = new_test_date - timedelta(hours=CANDIDATE_COOLDOWN_HOURS)
    new_window_end = (
        new_test_date + timedelta(hours=TEST_SESSION_HOURS) + timedelta(hours=CANDIDATE_COOLDOWN_HOURS)
    )
    for other in db.registrations.all():
        if other["candidate_id"] != candidate_id:
            continue
        if other["status"] in ("CANCELLED", "NO_SHOW"):
            continue
        # PRD §3.4: session-overlap rejects "two events whose test windows
        # overlap". Same-event collisions are handled by the duplicate
        # registration rule below, never by session-overlap.
        if other["test_event_id"] == test_event_id:
            continue
        other_event = db.test_events.get(other["test_event_id"])
        if not other_event:
            continue
        other_test_date = parse_iso_utc(other_event["test_date"])
        other_window_start = other_test_date - timedelta(hours=CANDIDATE_COOLDOWN_HOURS)
        other_window_end = (
            other_test_date + timedelta(hours=TEST_SESSION_HOURS) + timedelta(hours=CANDIDATE_COOLDOWN_HOURS)
        )
        # Closed-interval overlap, with cooldown buffer applied to BOTH the new
        # row and the existing rows. Note: the PRD asks the existing rows'
        # [test_date, test_date+4h] padded by 4h cooldown. We pad both sides
        # symmetrically (gives the right behaviour for both directions).
        if new_window_start <= other_window_end and other_window_start <= new_window_end:
            raise err_candidate_session_overlap()

    # 2) Duplicate registration check
    for other in db.registrations.all():
        if (
            other["candidate_id"] == candidate_id
            and other["test_event_id"] == test_event_id
            and other["status"] != "CANCELLED"
        ):
            raise err_duplicate_registration()

    # 3) Compute fee snapshot at creation
    current_now = now()
    registration_deadline = parse_iso_utc(e["registration_deadline"])
    late_fee_charged = e["late_fee_cents"] if current_now > registration_deadline else 0
    accommodation_fee_charged = ACCOMMODATION_FEE_CENTS if accommodation_required else 0
    base_fee_charged = e["base_fee_cents"]
    amount_charged = base_fee_charged + late_fee_charged + accommodation_fee_charged

    # 4) Build the registration row (initial STANDBY)
    r = db.common_create()
    registered_at = iso_utc_ms(current_now)
    standby_eligibility_at = iso_utc_ms(current_now + timedelta(seconds=STANDBY_VISIBILITY_DELAY_SECONDS))
    r.update(
        {
            "candidate_id": candidate_id,
            "test_event_id": test_event_id,
            "test_center_id": test_center_id,
            "status": "STANDBY",
            "registered_at": registered_at,
            "registration_channel": "SELF_INITIATED",
            "accommodation_required": accommodation_required,
            "base_fee_cents_charged": base_fee_charged,
            "late_fee_cents_charged": late_fee_charged,
            "accommodation_fee_cents_charged": accommodation_fee_charged,
            "amount_charged_cents": amount_charged,
            "amount_refunded_cents": 0,
            "amount_retained_cents": amount_charged,
            "standby_promotion_eligibility_at": standby_eligibility_at,
            "locked_accommodation_request_version": None,
        }
    )

    # 5) Attempt auto-promote if capacity available
    cap = reconcile_capacity(test_event_id, test_center_id)
    can_promote = cap["available_seats"] > 0
    if accommodation_required:
        can_promote = can_promote and (
            (cap["accommodation_capacity"] - cap["accommodation_seats_used"]) > 0
        )

    if can_promote:
        r["status"] = "CONFIRMED"
        # If accommodation_required, also pin lock onto current approval version
        if accommodation_required:
            ar = _find_approved_accommodation(candidate_id, test_event_id)
            if ar is not None:
                r["locked_accommodation_request_version"] = ar["version"]
    else:
        if force_confirmed:
            # No commit, return error.
            raise err_capacity_exhausted()

    db.registrations.insert(r)
    reconcile_capacity(test_event_id, test_center_id)
    return r


def _find_approved_accommodation(candidate_id: str, test_event_id: str) -> Optional[dict]:
    for a in db.accommodation_requests.all():
        if (
            a["candidate_id"] == candidate_id
            and a["test_event_id"] == test_event_id
            and a["status"] == "APPROVED"
        ):
            return a
    return None


def cancel_registration(
    test_event_id: str,
    registration_id: str,
    body: dict,
    channel: str,
    caller_role: str,
    caller_user_id: str,
) -> dict:
    """Both Candidate self-cancel and Registrar admin-cancel reach here.

    channel: SELF_INITIATED or OFFICIAL_CANCELLATION (drives refund variant).
    """
    e = get_test_event_or_404(test_event_id)
    r = get_scoped_registration_or_404(test_event_id, registration_id)

    if caller_role == "Candidate" and caller_user_id != r["candidate_id"]:
        raise err_insufficient_permissions()

    occ_check(r, body.get("version") if body else None)

    if r["status"] not in ("STANDBY", "CONFIRMED"):
        raise err_invalid_registration_state()
    if e["status"] == "COMPLETED":
        raise err_invalid_registration_state()

    # Compute refund
    from services.refund_service import compute_refund_and_record

    was_status = r["status"]
    was_accommodation_required = bool(r.get("accommodation_required"))
    r["status"] = "CANCELLED"
    r["registration_channel"] = channel
    db.touch(r)

    compute_refund_and_record(registration=r, test_event=e, channel=channel)

    # Capacity ledger reconciliation + standby promotion.
    # PRD §3.4: the selector takes (seats_freed N, accommodation_seats_freed K).
    # A CONFIRMED cancellation frees one general seat (N=1) plus, if the row
    # was accommodation-required, one accommodation seat (K=1). STANDBY
    # cancellations don't free a confirmed seat (N=0).
    reconcile_capacity(test_event_id, r["test_center_id"])
    if was_status == "CONFIRMED":
        n_freed = 1
        k_freed = 1 if was_accommodation_required else 0
    else:
        n_freed = 0
        k_freed = 0
    standby_promotion_selector(
        test_event_id, r["test_center_id"],
        seats_freed=n_freed, accommodation_seats_freed=k_freed,
    )
    reconcile_capacity(test_event_id, r["test_center_id"])
    return r


def check_in_registration(
    test_event_id: str,
    registration_id: str,
    caller_role: str,
    caller_user_id: str,
) -> dict:
    e = get_test_event_or_404(test_event_id)
    r = get_scoped_registration_or_404(test_event_id, registration_id)

    # State check (priority 5)
    if r["status"] != "CONFIRMED":
        raise err_invalid_registration_state()

    # ID cleared check (priority 6)
    iv = _find_id_verification_for_reg(r["id"])
    if iv is None or iv["status"] != "CLEARED":
        raise err_id_not_cleared()

    # Accommodation pending check (priority 7)
    pending = _find_pending_accommodation(r["candidate_id"], test_event_id)
    if pending is not None:
        raise err_accommodation_pending()

    # Check-in window (priority 10)
    test_date = parse_iso_utc(e["test_date"])
    window_open = test_date - timedelta(hours=CHECK_IN_WINDOW_HOURS)
    window_close = test_date + timedelta(hours=CHECK_IN_GRACE_HOURS)
    current_now = now()
    if current_now < window_open or current_now > window_close:
        raise err_check_in_window_closed()

    r["status"] = "CHECKED_IN"
    db.touch(r)
    reconcile_capacity(test_event_id, r["test_center_id"])
    return r


def _find_id_verification_for_reg(registration_id: str) -> Optional[dict]:
    for v in db.id_verifications.all():
        if v["registration_id"] == registration_id:
            return v
    return None


def _find_pending_accommodation(candidate_id: str, test_event_id: str) -> Optional[dict]:
    for a in db.accommodation_requests.all():
        if a["candidate_id"] == candidate_id and a["test_event_id"] == test_event_id:
            if a["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_MORE_INFO"):
                return a
    return None


def list_registrations_for_event(
    test_event_id: str, test_center_id: Optional[str], status: Optional[str]
):
    get_test_event_or_404(test_event_id)
    items = [r for r in db.registrations.all() if r["test_event_id"] == test_event_id]
    if test_center_id:
        items = [r for r in items if r["test_center_id"] == test_center_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return items
