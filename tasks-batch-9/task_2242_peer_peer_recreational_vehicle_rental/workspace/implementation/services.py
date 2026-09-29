"""Lookups, derived-field recomputation, ledger posting and the cascades."""

from datetime import timedelta

import calc
from errors import fail
from store import (creation_order, db, new_record, now, now_iso, parse_date,
                   parse_dt, touch)

# ------------------------------------------------------------------ lookups ---
_NOT_FOUND = {
    "owners": "ERR_OWNER_NOT_FOUND",
    "renters": "ERR_RENTER_NOT_FOUND",
    "listings": "ERR_LISTING_NOT_FOUND",
    "vehicle_documents": "ERR_DOCUMENT_NOT_FOUND",
    "renter_qualifications": "ERR_QUALIFICATION_NOT_FOUND",
    "protection_plans": "ERR_PLAN_NOT_FOUND",
    "cancellation_policies": "ERR_POLICY_NOT_FOUND",
    "campgrounds": "ERR_CAMPGROUND_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "delivery_assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "meter_readings": "ERR_READING_NOT_FOUND",
    "trip_photos": "ERR_PHOTO_NOT_FOUND",
    "damage_claims": "ERR_CLAIM_NOT_FOUND",
    "ledger_entries": "ERR_LEDGER_ENTRY_NOT_FOUND",
}


def lookup(collection, key):
    record = getattr(db, collection).get(key) if isinstance(key, str) else None
    if record is None:
        fail(_NOT_FOUND[collection])
    return record


def listing_of(booking):
    return db.listings[booking["listing_id"]]


def owner_of_listing(listing):
    return db.owners[listing["owner_id"]]


# ---------------------------------------------------------------- ownership ---
def require_listing_owner(role, user_id, listing):
    if role == "Owner" and listing["owner_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting owner does not own this listing.")


def require_booking_access(role, user_id, booking):
    if role == "Owner":
        require_listing_owner(role, user_id, listing_of(booking))
    elif role == "Renter" and booking["renter_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting renter is not this booking's renter.")


# ------------------------------------------------------- listing derivations ---
def listing_documents(listing_id):
    return [d for d in db.vehicle_documents.values() if d["listing_id"] == listing_id]


def verified_document(listing_id, doc_type, on_or_after):
    for doc in listing_documents(listing_id):
        if doc["doc_type"] != doc_type or doc["superseded"]:
            continue
        if doc["verification_status"] != "VERIFIED":
            continue
        if doc["expires_on"] and parse_date(doc["expires_on"]) >= on_or_after:
            return doc
    return None


def recompute_listing_derived(listing):
    """insurance_status and inspection_photo_zone_count (PRD 3.2)."""
    today = now().date()
    status = "PENDING"
    for doc in listing_documents(listing["id"]):
        if doc["doc_type"] != "INSURANCE_POLICY" or doc["superseded"]:
            continue
        if doc["verification_status"] != "VERIFIED":
            continue
        if parse_date(doc["expires_on"]) >= today:
            status = "VERIFIED"
            break
        status = "EXPIRED"
    zones = {d["zone"] for d in listing_documents(listing["id"])
             if d["doc_type"] == "INSPECTION_PHOTO" and not d["superseded"]}
    listing["insurance_status"] = status
    listing["inspection_photo_zone_count"] = len(zones)


# ------------------------------------------------------------------- ledger ---
def add_ledger(booking_id, party, entry_type, amount_cents, memo, reversal_of=None):
    entry = new_record(with_version=False, booking_id=booking_id, party=party,
                       entry_type=entry_type, amount_cents=amount_cents,
                       reversal_of_entry_id=reversal_of, memo=memo)
    db.ledger_entries[entry["id"]] = entry
    return entry


def owner_ledger_total(owner_id):
    listing_ids = {l["id"] for l in db.listings.values() if l["owner_id"] == owner_id}
    booking_ids = {b["id"] for b in db.bookings.values() if b["listing_id"] in listing_ids}
    return sum(e["amount_cents"] for e in db.ledger_entries.values()
               if e["party"] == "OWNER" and e["booking_id"] in booking_ids)


def recompute_owner_payout(owner, defer_touch=False):
    total = owner_ledger_total(owner["id"])
    if total != owner["payout_balance_cents"]:
        owner["payout_balance_cents"] = total
        if not defer_touch:
            touch(owner)
        return True
    return False


# -------------------------------------------------------------------- quote ---
def mirrored_delivery_fee(booking):
    for assignment in db.delivery_assignments.values():
        if assignment["booking_id"] == booking["id"] and assignment["status"] in (
                "SCHEDULED", "COMPLETED"):
            return assignment["delivery_fee_cents"]
    return 0


def recompute_quote_steps(booking):
    """Steps 1-6 only; base_subtotal_cents and premium_cents are left alone."""
    calc.quote_total(booking, listing_of(booking))


def recompute_quote_full(booking):
    listing = listing_of(booking)
    plan = db.protection_plans[booking["protection_plan_id"]]
    booking["base_subtotal_cents"] = calc.booking_nightly_subtotal(
        listing, parse_date(booking["start_date"]), booking["nights"])
    booking["premium_cents"] = calc.protection_premium(
        listing, plan, booking["nights"], booking["base_subtotal_cents"],
        booking["towing_verified_tier"])
    booking["delivery_fee_cents"] = mirrored_delivery_fee(booking)
    calc.quote_total(booking, listing)


# ------------------------------------------------------- campground capacity ---
def scheduled_on(campground_id, dropoff_date=None):
    rows = [a for a in db.delivery_assignments.values()
            if a["campground_id"] == campground_id and a["status"] == "SCHEDULED"]
    if dropoff_date is not None:
        rows = [a for a in rows if a["dropoff_date"] == dropoff_date]
    return rows


def window_conflict(campground, window_start, window_end, dropoff_date=None,
                    exclude_ids=()):
    """Closed intervals with dropoff_buffer_minutes applied to BOTH ends."""
    buffer = timedelta(minutes=campground["dropoff_buffer_minutes"])
    for other in scheduled_on(campground["id"], dropoff_date):
        if other["id"] in exclude_ids:
            continue
        if (window_start <= other["_window_end"] + buffer
                and window_end >= other["_window_start"] - buffer):
            return True
    return False


def sync_campground_count(campground, delta):
    campground["scheduled_assignment_count"] = max(
        0, campground["scheduled_assignment_count"] + delta)
    touch(campground)


# ------------------------------------------------------- waitlist promotion ---
def promote_waitlist(campground, dropoff_date):
    candidates = []
    for assignment in db.delivery_assignments.values():
        if assignment["campground_id"] != campground["id"]:
            continue
        if assignment["dropoff_date"] != dropoff_date or assignment["status"] != "WAITLISTED":
            continue
        booking = db.bookings.get(assignment["booking_id"])
        if booking is None or booking["trip_status"] not in (
                "CONFIRMED", "OWNER_APPROVED", "REQUESTED"):
            continue
        candidates.append(assignment)
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["created_at"], a["_window_start"],
                                   a["distance_miles"], a["_seq"]))
    for candidate in candidates:
        if window_conflict(campground, candidate["_window_start"],
                           candidate["_window_end"], dropoff_date,
                           exclude_ids=(candidate["id"],)):
            continue
        candidate["status"] = "SCHEDULED"
        candidate["promoted_from_waitlist"] = True
        touch(candidate)
        sync_campground_count(campground, +1)
        booking = db.bookings[candidate["booking_id"]]
        booking["delivery_fee_cents"] = candidate["delivery_fee_cents"]
        recompute_quote_steps(booking)
        if booking["settlement_status"] == "HELD":
            renter = db.renters[booking["renter_id"]]
            difference = booking["quoted_total_cents"] - booking["hold_amount_cents"]
            renter["wallet_credit_cents"] -= difference
            touch(renter)
            booking["hold_amount_cents"] = booking["quoted_total_cents"]
        touch(booking)
        return candidate
    return None


def void_assignment(assignment, reason=None, zero_fee=True, touch_booking=True,
                    promote=True):
    was_scheduled = assignment["status"] == "SCHEDULED"
    assignment["status"] = "VOIDED"
    if reason is not None:
        assignment["void_reason"] = reason
    touch(assignment)
    booking = db.bookings.get(assignment["booking_id"])
    if zero_fee and booking is not None:
        booking["delivery_fee_cents"] = 0
        recompute_quote_steps(booking)
        if touch_booking:
            touch(booking)
    campground = db.campgrounds.get(assignment["campground_id"])
    if was_scheduled and campground is not None:
        sync_campground_count(campground, -1)
        if promote:
            promote_waitlist(campground, assignment["dropoff_date"])


def void_live_assignments(booking, zero_fee=False, touch_booking=False):
    rows = [a for a in db.delivery_assignments.values()
            if a["booking_id"] == booking["id"]
            and a["status"] in ("REQUESTED", "SCHEDULED", "WAITLISTED")]
    for assignment in creation_order(rows):
        void_assignment(assignment, zero_fee=zero_fee, touch_booking=touch_booking)


# ---------------------------------------------------------------- cascades ----
def platform_cancel_booking(booking):
    """A listing suspension cancelling one of its live bookings (PRD 3.3)."""
    renter = db.renters[booking["renter_id"]]
    booking["trip_status"] = "CANCELLED_BY_PLATFORM"
    booking["settlement_status"] = "REFUNDED"
    booking["refund_cents"] = booking["hold_amount_cents"]
    if booking["refund_cents"]:
        renter["wallet_credit_cents"] += booking["refund_cents"]
        touch(renter)
    booking["hold_amount_cents"] = 0
    void_live_assignments(booking)
    touch(booking)


def suspend_listing(listing, reason=None):
    listing["listing_status"] = "SUSPENDED"
    if reason is not None:
        listing["suspend_reason"] = reason
    touch(listing)
    owner = owner_of_listing(listing)
    owner["listed_listing_count"] = max(0, owner["listed_listing_count"] - 1)
    touch(owner)
    live = [b for b in db.bookings.values()
            if b["listing_id"] == listing["id"]
            and b["trip_status"] in ("REQUESTED", "OWNER_APPROVED", "CONFIRMED")]
    for booking in creation_order(live):
        platform_cancel_booking(booking)


def apply_owner_points(owner, delta):
    """Adds points, re-evaluates the suspension threshold. Caller touches owner."""
    owner["owner_penalty_points"] = max(0, owner["owner_penalty_points"] + delta)
    if owner["owner_penalty_points"] >= calc.OWNER_SUSPENSION_POINT_THRESHOLD:
        owner["status"] = "SUSPENDED"
        listed = [l for l in db.listings.values()
                  if l["owner_id"] == owner["id"] and l["listing_status"] == "LISTED"]
        for listing in creation_order(listed):
            suspend_listing(listing)
    else:
        owner["status"] = "ACTIVE"


# ------------------------------------------------------------ cancellation ----
def cancel_booking(booking, role, reason):
    policy = db.cancellation_policies[booking["cancellation_policy_id"]]
    renter = db.renters[booking["renter_id"]]
    listing = listing_of(booking)

    if role == "Renter":
        hours = calc.hours_before_pickup(booking)
        if hours >= policy["full_refund_hours_before"]:
            refund_bp = 10000
        else:
            refund_bp = policy["partial_refund_pct_bp"]
        refund = calc.bp_of(booking["hold_amount_cents"], refund_bp)
        booking["trip_status"] = "CANCELLED_BY_RENTER"
        if refund_bp < 10000:
            renter["renter_penalty_points"] = max(
                0, renter["renter_penalty_points"] + policy["renter_cancel_penalty_points"])
    else:
        refund = booking["hold_amount_cents"]
        booking["trip_status"] = ("CANCELLED_BY_OWNER" if role == "Owner"
                                 else "CANCELLED_BY_PLATFORM")

    booking["refund_cents"] = refund
    renter["wallet_credit_cents"] += refund
    booking["hold_amount_cents"] = 0
    booking["settlement_status"] = "REFUNDED"
    booking["cancel_reason"] = reason
    touch(renter)

    void_live_assignments(booking)
    touch(booking)

    if role == "Owner":
        owner = owner_of_listing(listing)
        fee = calc.bp_of(booking["base_subtotal_cents"], policy["owner_cancel_fee_bp"])
        add_ledger(booking["id"], "OWNER", "OWNER_CANCEL_FEE", -fee,
                   "Owner cancellation fee")
        add_ledger(booking["id"], "PLATFORM", "OWNER_CANCEL_FEE", fee,
                   "Owner cancellation fee")
        apply_owner_points(owner, policy["owner_cancel_penalty_points"])
        recompute_owner_payout(owner, defer_touch=True)
        touch(owner)


# ------------------------------------------------------------- settlement -----
def settle_booking(booking):
    listing = listing_of(booking)
    owner = owner_of_listing(listing)
    renter = db.renters[booking["renter_id"]]

    owner_payout = (booking["final_total_cents"] - booking["service_fee_cents"]
                    - booking["premium_cents"])
    add_ledger(booking["id"], "RENTER", "TRIP_CHARGE", -booking["final_total_cents"],
               "Trip charge")
    add_ledger(booking["id"], "OWNER", "OWNER_PAYOUT", owner_payout, "Owner payout")
    add_ledger(booking["id"], "PLATFORM", "SERVICE_FEE", booking["service_fee_cents"],
               "Platform service fee")
    add_ledger(booking["id"], "PLATFORM", "PROTECTION_PREMIUM", booking["premium_cents"],
               "Protection premium")

    balance = booking["balance_due_cents"]
    if balance > 0:
        renter["wallet_credit_cents"] -= balance
        touch(renter)
    elif balance < 0:
        renter["wallet_credit_cents"] += -balance
        touch(renter)

    recompute_owner_payout(owner)

    listing["completed_night_count"] += booking["nights"]
    listing["last_reconciled_at"] = now_iso()
    touch(listing)

    booking["_settled_at"] = now_iso()
    booking["settlement_status"] = "SETTLED"
    booking["trip_status"] = "CLOSED"
    touch(booking)


def reverse_settlement(booking, reason):
    listing = listing_of(booking)
    owner = owner_of_listing(listing)
    renter = db.renters[booking["renter_id"]]

    forward = [e for e in db.ledger_entries.values()
               if e["booking_id"] == booking["id"]
               and e["reversal_of_entry_id"] is None
               and e["entry_type"] in ("TRIP_CHARGE", "OWNER_PAYOUT", "SERVICE_FEE",
                                       "PROTECTION_PREMIUM")]
    for entry in creation_order(forward):
        add_ledger(booking["id"], entry["party"], entry["entry_type"] + "_REVERSAL",
                   -entry["amount_cents"], "Settlement reversal", reversal_of=entry["id"])

    balance = booking["balance_due_cents"]
    if balance > 0:
        renter["wallet_credit_cents"] += balance
        touch(renter)
    elif balance < 0:
        renter["wallet_credit_cents"] -= -balance
        touch(renter)

    recompute_owner_payout(owner)

    listing["completed_night_count"] = max(0, listing["completed_night_count"] - booking["nights"])
    booking["_settled_at"] = None
    stamps = [b["_settled_at"] for b in db.bookings.values()
              if b["listing_id"] == listing["id"] and b["settlement_status"] == "SETTLED"
              and b.get("_settled_at")]
    listing["last_reconciled_at"] = max(stamps) if stamps else None
    touch(listing)

    booking["settlement_status"] = "RECONCILING"
    booking["reversal_reason"] = reason
    touch(booking)


# ----------------------------------------------------------- damage claims ----
def claims_of(booking_id):
    return [c for c in db.damage_claims.values() if c["booking_id"] == booking_id]


def open_claims(booking_id):
    return [c for c in claims_of(booking_id)
            if c["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")]


def close_claim_window(booking):
    """Every terminal claim outcome re-evaluates the booking (PRD 3.8)."""
    if open_claims(booking["id"]):
        return
    if booking["settlement_status"] == "DISPUTED":
        booking["settlement_status"] = "RECONCILING"
    calc.final_trip_total(booking)
