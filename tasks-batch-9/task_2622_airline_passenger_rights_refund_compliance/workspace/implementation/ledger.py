"""Conserved ledgers, the booking rollup and the single obligation-minting path (PRD 2.11, 3.6)."""

from errors import ApiError
from store import S, new_row, touch
import calc


# --------------------------------------------------------------------------
# Booking derived fields (PRD 2.11 / booking_ledger_recompute)
# --------------------------------------------------------------------------

def recompute_booking(booking):
    booking_id = booking["id"]
    segments = calc.segments_of(booking_id)

    booking["itinerary_scope"] = (
        "INTERNATIONAL" if any(s["is_international"] for s in segments) else "DOMESTIC"
    )
    booking["segment_count"] = len(segments)
    booking["unused_segment_count"] = sum(
        1 for s in segments if s["status"] in calc.UNUSED_SEGMENT_STATUSES
    )
    booking["travel_commenced"] = any(
        s["status"] in calc.FLOWN_SEGMENT_STATUSES for s in segments
    )
    booking["collected_total_cents"] = calc.collected_total(booking)

    obligations = calc.obligations_of(booking_id)
    live = [o for o in obligations if o["settlement_status"] != "VOIDED"]
    booking["total_refund_obligated_cents"] = sum(o["amount_cents"] for o in live)

    open_rows = [
        o for o in obligations if o["settlement_status"] not in ("SETTLED", "VOIDED")
    ]
    if open_rows:
        best = min(open_rows, key=lambda o: (o["deadline_utc"], o["_seq"]))
        booking["earliest_refund_deadline_utc"] = best["deadline_utc"]
    else:
        booking["earliest_refund_deadline_utc"] = None

    if booking["segment_count"] == 0:
        posture = "NORMAL"
    elif live:
        if all(o["settlement_status"] in ("SETTLED", "VOIDED") for o in obligations):
            posture = "CLOSED_OUT"
        else:
            posture = "REFUND_OBLIGATED"
    elif any(s["disruption_type"] != "NONE" for s in segments):
        posture = "DISRUPTED"
    else:
        posture = "NORMAL"
    booking["disruption_posture"] = posture
    return booking


def bump_booking(booking):
    """Recompute the derived fields and advance Booking.version exactly once."""
    recompute_booking(booking)
    touch(booking)
    return booking


# --------------------------------------------------------------------------
# Passenger derived fields
# --------------------------------------------------------------------------

def passenger_of(booking):
    return S.passengers.get(booking["passenger_id"])


def recompute_open_complaints(passenger):
    if passenger is None:
        return None
    booking_ids = set(
        b["id"] for b in S.bookings.values() if b["passenger_id"] == passenger["id"]
    )
    passenger["open_complaint_count"] = sum(
        1
        for c in S.consumer_complaints.values()
        if c["booking_id"] in booking_ids and c["status"] in calc.OPEN_COMPLAINT_STATUSES
    )
    return passenger


def recompute_credit_balance(passenger):
    """Conserved quantity Q2 (PRD 2.11)."""
    if passenger is None:
        return None
    booking_ids = set(
        b["id"] for b in S.bookings.values() if b["passenger_id"] == passenger["id"]
    )
    total = 0
    for row in sorted(S.refund_obligations.values(), key=lambda r: r["_seq"]):
        if row["booking_id"] not in booking_ids:
            continue
        if row["settlement_method"] != "TRAVEL_CREDIT":
            continue
        if row["settlement_status"] != "SETTLED":
            continue
        total += row["payable_total_cents"]
    passenger["travel_credit_balance_cents"] = total if total > 0 else 0
    return passenger


# --------------------------------------------------------------------------
# Obligation minting -- the one path every basis flows through (PRD 3.6)
# --------------------------------------------------------------------------

SOURCE_FIELDS = (
    "flight_segment_id",
    "checked_bag_id",
    "ancillary_purchase_id",
    "denied_boarding_record_id",
)


def live_obligation_for(booking_id, basis, source_field, source_id):
    for row in calc.obligations_of(booking_id):
        if row["settlement_status"] == "VOIDED":
            continue
        if row["basis"] != basis:
            continue
        if source_field is None or row.get(source_field) == source_id:
            return row
    return None


def any_live_obligation_for_source(basis, source_field, source_id):
    for row in sorted(S.refund_obligations.values(), key=lambda r: r["_seq"]):
        if row["settlement_status"] == "VOIDED":
            continue
        if row["basis"] != basis:
            continue
        if row.get(source_field) == source_id:
            return row
    return None


def live_grant_for_complaint(complaint_id):
    for row in sorted(S.refund_obligations.values(), key=lambda r: r["_seq"]):
        if row["settlement_status"] == "VOIDED":
            continue
        if row["basis"] != "GOODWILL_GRANT":
            continue
        if row.get("_complaint_id") == complaint_id:
            return row
    return None


def mint_obligation(
    booking,
    basis,
    issuance_mode,
    variant,
    gross_entitlement_cents,
    obligation_start_utc,
    source_field=None,
    source_id=None,
    created_by_user_id=None,
    complaint_id=None,
    cascade=False,
):
    """Steps 1-4 of the pinned headroom sequence. Returns the row, or None when a
    cascade had to suppress it. Step 5 (the booking rollup) is the caller's job."""
    policy = calc.policy_of(booking)
    headroom_at_creation = calc.headroom(booking)

    if basis == "DENIED_BOARDING":
        amount = gross_entitlement_cents
        if cascade and amount <= 0:
            return None
    elif issuance_mode == "PROACTIVE":
        amount = min(gross_entitlement_cents, headroom_at_creation)
        if cascade:
            if amount <= 0:
                return None
        elif headroom_at_creation <= 0:
            raise ApiError("ERR_NO_REFUND_HEADROOM")
    else:
        if gross_entitlement_cents > headroom_at_creation:
            raise ApiError("ERR_REFUND_EXCEEDS_HEADROOM")
        amount = gross_entitlement_cents

    if obligation_start_utc is None:
        obligation_start_utc = S.now()
    deadline_utc, election_deadline_utc = calc.refund_deadlines(
        booking, policy, obligation_start_utc
    )

    fields = {
        "booking_id": booking["id"],
        "flight_segment_id": None,
        "checked_bag_id": None,
        "ancillary_purchase_id": None,
        "denied_boarding_record_id": None,
        "basis": basis,
        "issuance_mode": issuance_mode,
        "variant_applied": variant,
        "gross_entitlement_cents": gross_entitlement_cents,
        "headroom_at_creation_cents": headroom_at_creation,
        "amount_cents": amount,
        "credit_bonus_cents": 0,
        "payable_total_cents": amount,
        "election_status": "PENDING_ELECTION",
        "election_source": None,
        "credit_consent_reference": None,
        "settlement_status": "UNSETTLED",
        "settlement_method": None,
        "obligation_start_utc": obligation_start_utc,
        "deadline_utc": deadline_utc,
        "election_deadline_utc": election_deadline_utc,
        "deadline_breached": False,
        "settlement_attempt_count": 0,
        "settlement_initiated_at_utc": None,
        "settled_at_utc": None,
        "last_failure_reason": None,
        "void_reason": None,
        "created_by_user_id": created_by_user_id,
        "settlement_initiated_by_user_id": None,
        "_complaint_id": complaint_id,
    }
    if source_field is not None:
        fields[source_field] = source_id

    row = new_row(fields)
    S.refund_obligations[row["id"]] = row
    return row


def suppress(booking):
    booking["suppressed_obligation_count"] += 1


# --------------------------------------------------------------------------
# Complaint activity trail (PRD 3.8) -- append only, no version, no updated_at
# --------------------------------------------------------------------------

def append_activity(complaint_id, activity_type, occurred_at_utc, actor_role, actor_user_id, detail):
    row = new_row(
        {
            "complaint_id": complaint_id,
            "activity_type": activity_type,
            "occurred_at_utc": occurred_at_utc,
            "actor_role": actor_role,
            "actor_user_id": actor_user_id,
            "detail": detail,
        },
        versioned=False,
    )
    S.complaint_activities[row["id"]] = row
    return row
