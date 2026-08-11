"""Cross-entity domain helpers: derived aggregates, overlap scans, cascades."""
import db
from db import stores
from services import calc

ACTIVE_CHAIR_STATES = ("ASSIGNED", "EN_ROUTE", "ON_SITE")


def get_or_404(coll, entity_id, label="Resource"):
    entity = db.get(coll, entity_id)
    if entity is None:
        import errors
        raise errors.not_found(f"{label} '{entity_id}' does not exist")
    return entity


# ---------------------------------------------------------------------------
# Booking derived aggregates (eagerly maintained)
# ---------------------------------------------------------------------------
def recompute_booked_minutes(booking):
    total = 0
    for claim in stores["slot_claims"].values():
        if claim["booking_id"] == booking["id"] and claim["status"] in (
                "CLAIMED", "CHECKED_IN", "COMPLETED"):
            total += booking["slot_minutes"]
    booking["booked_chair_minutes"] = total


def recompute_delivered_minutes(booking):
    total = 0
    for claim in stores["slot_claims"].values():
        if claim["booking_id"] == booking["id"] and claim["status"] == "COMPLETED":
            total += booking["slot_minutes"]
    booking["delivered_chair_minutes"] = total


def claims_of_booking(booking_id):
    return [c for c in stores["slot_claims"].values() if c["booking_id"] == booking_id]


def chairs_of_booking(booking_id):
    return [c for c in db.all_sorted("chair_slots") if c["booking_id"] == booking_id]


def legs_of_booking(booking_id):
    return [l for l in db.all_sorted("travel_legs") if l["booking_id"] == booking_id]


# ---------------------------------------------------------------------------
# Therapist scheduling checks
# ---------------------------------------------------------------------------
def extended_window(booking):
    region = db.get("regions", booking["region_id"])
    setup = region["setup_buffer_minutes"] if region else 0
    teardown = region["teardown_buffer_minutes"] if region else 0
    start = booking["window_start_minutes"] - setup
    end = booking["window_start_minutes"] + booking["window_duration_minutes"] + teardown
    return start, end


def therapist_active_chairs_on(therapist_id, event_date):
    """All (chair, booking) pairs for therapist in ASSIGNED/EN_ROUTE/ON_SITE on date."""
    out = []
    for chair in stores["chair_slots"].values():
        if chair["therapist_id"] != therapist_id:
            continue
        if chair["status"] not in ACTIVE_CHAIR_STATES:
            continue
        booking = db.get("bookings", chair["booking_id"])
        if booking and booking["event_date"] == event_date:
            out.append((chair, booking))
    return out


def therapist_booked_minutes(therapist_id, event_date):
    return sum(b["slot_minutes"] for _, b in therapist_active_chairs_on(therapist_id, event_date))


def has_valid_license(therapist_id, region_id, event_date):
    for lic in stores["therapist_licenses"].values():
        if (lic["therapist_id"] == therapist_id and lic["region_id"] == region_id
                and lic["status"] == "ACTIVE" and lic["expires_on"] >= event_date):
            return True
    return False


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap; adjacency (end == start) is permitted."""
    return a_start < b_end and b_start < a_end


def therapist_double_booked(therapist_id, event_date, candidate_booking):
    cand_start, cand_end = extended_window(candidate_booking)
    for _, other in therapist_active_chairs_on(therapist_id, event_date):
        o_start, o_end = extended_window(other)
        if windows_overlap(cand_start, cand_end, o_start, o_end):
            return True
    return False


def confirm_double_booking_scan(booking):
    """Pairwise scan across every assigned therapist's chairs on the event date."""
    therapist_ids = {c["therapist_id"] for c in stores["chair_slots"].values()
                     if c["booking_id"] == booking["id"] and c["status"] == "ASSIGNED"}
    for tid in therapist_ids:
        active = therapist_active_chairs_on(tid, booking["event_date"])
        wins = [extended_window(b) for _, b in active]
        for i in range(len(wins)):
            for j in range(i + 1, len(wins)):
                if windows_overlap(*wins[i], *wins[j]):
                    return True
    return False


# ---------------------------------------------------------------------------
# Chair release cascade (shared by release endpoint, booking cancel, license revoke)
# ---------------------------------------------------------------------------
def maybe_waive_leg(booking_id, therapist_id):
    """Waive the therapist's PLANNED leg when no other ASSIGNED chair remains."""
    remaining = any(
        c for c in stores["chair_slots"].values()
        if c["booking_id"] == booking_id and c["therapist_id"] == therapist_id
        and c["status"] == "ASSIGNED")
    if remaining:
        return
    for leg in stores["travel_legs"].values():
        if (leg["booking_id"] == booking_id and leg["therapist_id"] == therapist_id
                and leg["status"] == "PLANNED"):
            leg["status"] = "WAIVED"
            leg["travel_fee_cents"] = 0
            db.touch(leg)


def release_chair(chair, booking):
    """ASSIGNED -> RELEASED with audit retention and leg waive cascade."""
    therapist_id = chair["therapist_id"]
    chair["status"] = "RELEASED"
    db.touch(chair)
    if therapist_id:
        maybe_waive_leg(booking["id"], therapist_id)


# ---------------------------------------------------------------------------
# Draft invoice recomputation (eager, on any source-field change)
# ---------------------------------------------------------------------------
def compute_invoice_fields(invoice):
    booking = db.get("bookings", invoice["booking_id"])
    if invoice["pricing_variant"] == "PROVISIONAL":
        chair_minutes = booking["booked_chair_minutes"]
    else:
        chair_minutes = booking["delivered_chair_minutes"]
    subtotal = chair_minutes * booking["per_minute_rate_cents"]
    discount = 0
    if booking["booking_kind"] == "RECURRING_OCCURRENCE" and booking["wellness_program_id"]:
        program = db.get("wellness_programs", booking["wellness_program_id"])
        if program and program["status"] != "TERMINATED":
            discount = calc.floor_pct(subtotal, program["recurrence_discount_pct"])
    travel = sum(l["travel_fee_cents"] for l in stores["travel_legs"].values()
                 if l["booking_id"] == booking["id"] and l["status"] in ("PLANNED", "REIMBURSED"))
    cancel_fee = booking["cancellation_fee_cents"] if booking["status"] == "CANCELLED" else 0
    credit = calc.satisfaction_credit(booking["id"], subtotal)
    total = max(0, subtotal - discount + travel + cancel_fee - credit)
    return {
        "chair_minutes_billed": chair_minutes,
        "subtotal_cents": subtotal,
        "recurrence_discount_cents": discount,
        "travel_fees_cents": travel,
        "cancellation_fee_cents": cancel_fee,
        "satisfaction_credit_cents": credit,
        "total_cents": total,
    }


def recompute_draft_invoice(booking_id):
    for invoice in stores["invoices"].values():
        if invoice["booking_id"] == booking_id and invoice["status"] == "DRAFT":
            fields = compute_invoice_fields(invoice)
            changed = any(invoice[k] != v for k, v in fields.items())
            invoice.update(fields)
            if changed:
                db.touch(invoice)


def recompute_draft_invoices_for_program(program_id):
    for booking in stores["bookings"].values():
        if booking["wellness_program_id"] == program_id:
            recompute_draft_invoice(booking["id"])


# ---------------------------------------------------------------------------
# Booking billing_status transitions (invoice-driven)
# ---------------------------------------------------------------------------
def set_billing_status(booking, new_status):
    if booking["billing_status"] != new_status:
        booking["billing_status"] = new_status
        db.touch(booking)


def adjust_account_balance(account, delta_outstanding, delta_lifetime=0):
    account["outstanding_balance_cents"] += delta_outstanding
    account["lifetime_billed_cents"] += delta_lifetime
    db.touch(account)
