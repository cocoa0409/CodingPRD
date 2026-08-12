"""Booking endpoints: creation, lifecycle actions, reverse-FK lists, invoicing."""
from flask import Blueprint

import db
import errors
from auth import require_account_owner, require_roles
from clock import clock
from db import stores
from respond import success
from services import calc
from services.domain import (chairs_of_booking, claims_of_booking,
                             confirm_double_booking_scan, get_or_404,
                             has_valid_license, legs_of_booking,
                             recompute_draft_invoice, release_chair)
from validate import (apply_filters, json_body, opt_int_field, opt_str,
                      paginate, req_date, req_int, req_str)

bp = Blueprint("bookings", __name__)

ACTIVE_LEARN = ("DRAFT", "SCHEDULING", "CONFIRMED")


def _load_owned_booking(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    return booking


@bp.post("/chair-massage/bookings")
@require_roles("Organizer")
def create_booking():
    body = json_body()
    account_id = req_str(body, "corporate_account_id")
    get_or_404("corporate_accounts", account_id, "CorporateAccount")
    require_account_owner(account_id)
    region_id = req_str(body, "region_id")
    get_or_404("regions", region_id, "Region")
    site_address = req_str(body, "site_address", allow_empty=True)
    event_date = req_date(body, "event_date")
    window_start = req_int(body, "window_start_minutes", min_v=0, max_v=1439)
    duration = req_int(body, "window_duration_minutes", min_v=30)
    chair_count = req_int(body, "chair_count", min_v=1)
    slot_minutes = req_int(body, "slot_minutes", min_v=5)
    rate = req_int(body, "per_minute_rate_cents", min_v=1)
    if duration % slot_minutes != 0:
        raise errors.unprocessable(
            errors.ERR_WINDOW_NOT_DIVISIBLE,
            "window_duration_minutes must be an exact multiple of slot_minutes")
    booking = db.stamp_new({
        "id": db.new_id(),
        "corporate_account_id": account_id,
        "wellness_program_id": None,
        "booking_kind": "EVENT",
        "region_id": region_id,
        "site_address": site_address,
        "event_date": event_date,
        "window_start_minutes": window_start,
        "window_duration_minutes": duration,
        "chair_count": chair_count,
        "slot_minutes": slot_minutes,
        "per_minute_rate_cents": rate,
        "status": "DRAFT",
        "billing_status": "UNBILLED",
        "booked_chair_minutes": 0,
        "delivered_chair_minutes": 0,
        "cancellation_fee_cents": 0,
    })
    db.insert("bookings", booking)
    return success(db.public(booking), status=201)


@bp.get("/chair-massage/bookings")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_bookings():
    items = db.all_sorted("bookings")
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "billing_status": (lambda e: e["billing_status"], "str"),
        "corporate_account_id": (lambda e: e["corporate_account_id"], "str"),
        "region_id": (lambda e: e["region_id"], "str"),
        "event_date": (lambda e: e["event_date"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/bookings/<bid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_booking(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    return success(db.public(booking))


@bp.post("/chair-massage/bookings/<bid>/open-scheduling")
@require_roles("Organizer")
def open_scheduling(bid):
    booking = _load_owned_booking(bid)
    if booking["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT booking can open scheduling")
    account = get_or_404("corporate_accounts", booking["corporate_account_id"],
                         "CorporateAccount")
    if account["status"] != "ACTIVE":
        raise errors.unprocessable(errors.ERR_ACCOUNT_SUSPENDED,
                                   "Operation requires CorporateAccount.status == ACTIVE")
    region = get_or_404("regions", booking["region_id"], "Region")
    if not region["is_active"]:
        raise errors.unprocessable(errors.ERR_REGION_INACTIVE,
                                   "Operation requires Region.is_active == true")
    booking["status"] = "SCHEDULING"
    db.touch(booking)
    for index in range(booking["chair_count"]):
        chair = db.stamp_new({
            "id": db.new_id(),
            "booking_id": booking["id"],
            "therapist_id": None,
            "chair_index": index,
            "status": "UNASSIGNED",
            "assigned_at": None,
            "arrived_at": None,
        })
        db.insert("chair_slots", chair)
    return success(db.public(booking))


@bp.post("/chair-massage/bookings/<bid>/confirm")
@require_roles("Organizer")
def confirm_booking(bid):
    booking = _load_owned_booking(bid)
    if booking["status"] != "SCHEDULING":
        raise errors.invalid_state("Only a SCHEDULING booking can be confirmed")
    chairs = chairs_of_booking(bid)
    if any(c["status"] != "ASSIGNED" for c in chairs):
        raise errors.invalid_state("Every chair slot must be ASSIGNED before confirmation")
    body = json_body()
    expected = opt_int_field(body, "expected_booking_version")
    if expected is None:
        raise errors.invalid_request("Field 'expected_booking_version' is required")
    if expected != booking["version"]:
        raise errors.ApiError(errors.ERR_STALE_BOOKING_VERSION, 412,
                              "expected_booking_version does not match Booking.version")
    therapist_ids = []
    for chair in chairs:
        if chair["therapist_id"] not in therapist_ids:
            therapist_ids.append(chair["therapist_id"])
    for tid in therapist_ids:
        if not has_valid_license(tid, booking["region_id"], booking["event_date"]):
            raise errors.unprocessable(
                errors.ERR_LICENSE_INVALID,
                "Therapist lacks an ACTIVE license in the booking region covering the event date")
    if confirm_double_booking_scan(booking):
        raise errors.unprocessable(
            errors.ERR_THERAPIST_DOUBLE_BOOKED,
            "A therapist's buffer-extended windows overlap on the event date")
    # Optional per-therapist travel details supplied at confirmation time.
    travel_specs = {}
    raw_legs = body.get("travel_legs")
    if isinstance(raw_legs, list):
        for entry in raw_legs:
            if isinstance(entry, dict) and isinstance(entry.get("therapist_id"), str):
                travel_specs[entry["therapist_id"]] = entry
    default_origin = opt_str(body, "origin_address")
    default_distance = opt_int_field(body, "distance_miles")
    region = get_or_404("regions", booking["region_id"], "Region")
    for tid in therapist_ids:
        exists = any(l for l in stores["travel_legs"].values()
                     if l["booking_id"] == bid and l["therapist_id"] == tid)
        if exists:
            continue
        spec = travel_specs.get(tid, {})
        origin = spec.get("origin_address", default_origin)
        if not isinstance(origin, str):
            origin = ""
        distance = spec.get("distance_miles", default_distance)
        if not isinstance(distance, int) or isinstance(distance, bool) or distance < 0:
            distance = 0
        leg = db.stamp_new({
            "id": db.new_id(),
            "booking_id": bid,
            "therapist_id": tid,
            "origin_address": origin,
            "distance_miles": distance,
            "travel_fee_cents": calc.travel_fee_quoted(distance, region),
            "travel_fee_variant": "QUOTED",
            "status": "PLANNED",
        })
        db.insert("travel_legs", leg)
    booking["status"] = "CONFIRMED"
    db.touch(booking)
    recompute_draft_invoice(bid)
    return success(db.public(booking))


@bp.post("/chair-massage/bookings/<bid>/start-service")
@require_roles("Organizer")
def start_service(bid):
    booking = _load_owned_booking(bid)
    if booking["status"] != "CONFIRMED":
        raise errors.invalid_state("Only a CONFIRMED booking can start service")
    if clock.today() != booking["event_date"]:
        raise errors.invalid_state("Service can only start on the booking's event_date")
    if not any(c["status"] == "ON_SITE" for c in chairs_of_booking(bid)):
        raise errors.invalid_state("At least one chair slot must be ON_SITE")
    booking["status"] = "IN_PROGRESS"
    db.touch(booking)
    return success(db.public(booking))


@bp.post("/chair-massage/bookings/<bid>/complete")
@require_roles("Organizer")
def complete_booking(bid):
    booking = _load_owned_booking(bid)
    if booking["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Only an IN_PROGRESS booking can be completed")
    outstanding = [c for c in claims_of_booking(bid)
                   if c["status"] in ("CLAIMED", "CHECKED_IN")]
    if outstanding:
        raise errors.unprocessable(
            errors.ERR_CLAIMS_OUTSTANDING,
            "Every SlotClaim must be in COMPLETED, NO_SHOW or CANCELLED")
    region = get_or_404("regions", booking["region_id"], "Region")
    reimbursed_legs = []
    for leg in legs_of_booking(bid):
        if leg["status"] == "PLANNED":
            leg["travel_fee_cents"] = calc.travel_fee_settled(leg, booking, region)
            leg["travel_fee_variant"] = "SETTLED"
            leg["status"] = "REIMBURSED"
            db.touch(leg)
            reimbursed_legs.append(leg)
    # EARNING entries: one per therapist with at least one COMPLETED claim.
    therapist_ids = []
    for chair in chairs_of_booking(bid):
        tid = chair["therapist_id"]
        if tid and tid not in therapist_ids:
            therapist_ids.append(tid)
    for tid in therapist_ids:
        therapist = db.get("therapists", tid)
        if therapist is None:
            continue
        if calc.completed_claim_count_for(bid, tid) == 0:
            continue
        amount = calc.payout_earning_amount(booking, therapist)
        entry = db.stamp_new({
            "id": db.new_id(),
            "therapist_id": tid,
            "booking_id": bid,
            "entry_kind": "EARNING",
            "amount_cents": amount,
            "posted_at": clock.iso(),
            "memo": "",
        }, with_version=False)
        db.insert("payout_ledger_entries", entry)
    for leg in reimbursed_legs:
        entry = db.stamp_new({
            "id": db.new_id(),
            "therapist_id": leg["therapist_id"],
            "booking_id": bid,
            "entry_kind": "TRAVEL_REIMBURSEMENT",
            "amount_cents": leg["travel_fee_cents"],
            "posted_at": clock.iso(),
            "memo": "",
        }, with_version=False)
        db.insert("payout_ledger_entries", entry)
    booking["status"] = "COMPLETED"
    db.touch(booking)
    # Chairs auto-complete once the booking is COMPLETED and their claims terminal.
    for chair in chairs_of_booking(bid):
        if chair["status"] == "ON_SITE":
            chair_claims = [c for c in claims_of_booking(bid)
                            if c["chair_slot_id"] == chair["id"]]
            if all(c["status"] in ("COMPLETED", "NO_SHOW", "CANCELLED")
                   for c in chair_claims):
                chair["status"] = "COMPLETED"
                db.touch(chair)
    recompute_draft_invoice(bid)
    return success(db.public(booking))


@bp.post("/chair-massage/bookings/<bid>/cancel")
@require_roles("Organizer")
def cancel_booking(bid):
    booking = _load_owned_booking(bid)
    if booking["status"] not in ACTIVE_LEARN:
        raise errors.invalid_state("Booking cannot be cancelled from its current state")
    origin = booking["status"]
    if origin in ("SCHEDULING", "CONFIRMED"):
        for chair in chairs_of_booking(bid):
            if chair["status"] == "ASSIGNED":
                release_chair(chair, booking)
    if origin == "CONFIRMED":
        booking["cancellation_fee_cents"] = calc.cancellation_fee(booking)
        for leg in legs_of_booking(bid):
            if leg["status"] == "PLANNED":
                leg["status"] = "WAIVED"
                leg["travel_fee_cents"] = 0
                db.touch(leg)
    else:
        booking["cancellation_fee_cents"] = 0
    booking["status"] = "CANCELLED"
    db.touch(booking)
    recompute_draft_invoice(bid)
    return success(db.public(booking))


# ---------------------------------------------------------------------------
# Booking-scoped reverse-FK lists
# ---------------------------------------------------------------------------
@bp.get("/chair-massage/bookings/<bid>/chair-slots")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_booking_chairs(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    items = chairs_of_booking(bid)
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "therapist_id": (lambda e: e["therapist_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/bookings/<bid>/slot-claims")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_booking_claims(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    items = [c for c in db.all_sorted("slot_claims") if c["booking_id"] == bid]
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "chair_slot_id": (lambda e: e["chair_slot_id"], "str"),
        "recipient_email": (lambda e: e["recipient_email"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/bookings/<bid>/travel-legs")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_booking_legs(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    items = legs_of_booking(bid)
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "therapist_id": (lambda e: e["therapist_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/bookings/<bid>/payout-ledger-entries")
@require_roles("PlatformAdmin", "Organizer")
def list_booking_payouts(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    items = [p for p in db.all_sorted("payout_ledger_entries") if p["booking_id"] == bid]
    items = apply_filters(items, {
        "entry_kind": (lambda e: e["entry_kind"], "str"),
        "therapist_id": (lambda e: e["therapist_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/bookings/<bid>/invoices")
@require_roles("PlatformAdmin", "Organizer")
def list_booking_invoices(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    items = [i for i in db.all_sorted("invoices") if i["booking_id"] == bid]
    items = apply_filters(items, {"status": (lambda e: e["status"], "str")})
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/bookings/<bid>/waivers")
@require_roles("PlatformAdmin", "Organizer")
def list_booking_waivers(bid):
    booking = get_or_404("bookings", bid, "Booking")
    require_account_owner(booking["corporate_account_id"])
    items = [w for w in db.all_sorted("waivers") if w["booking_id"] == bid]
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.post("/chair-massage/bookings/<bid>/invoices")
@require_roles("PlatformAdmin")
def create_invoice(bid):
    booking = get_or_404("bookings", bid, "Booking")
    body = json_body()
    variant = body.get("pricing_variant")
    if variant not in ("PROVISIONAL", "FINAL"):
        raise errors.invalid_request(
            "Field 'pricing_variant' must be PROVISIONAL or FINAL")
    allowed = {"PROVISIONAL": ("CONFIRMED", "IN_PROGRESS"),
               "FINAL": ("COMPLETED", "CANCELLED")}
    if booking["status"] not in allowed[variant]:
        raise errors.invalid_state(
            f"pricing_variant {variant} is not available for a booking in status "
            f"{booking['status']}")
    for other in stores["invoices"].values():
        if (other["booking_id"] == bid
                and other["status"] in ("DRAFT", "ISSUED", "DISPUTED")):
            raise errors.unprocessable(
                errors.ERR_LIVE_INVOICE_EXISTS,
                "Another DRAFT/ISSUED/DISPUTED invoice already exists for this booking")
    invoice = db.stamp_new({
        "id": db.new_id(),
        "booking_id": bid,
        "corporate_account_id": booking["corporate_account_id"],
        "status": "DRAFT",
        "chair_minutes_billed": 0,
        "subtotal_cents": 0,
        "recurrence_discount_cents": 0,
        "travel_fees_cents": 0,
        "cancellation_fee_cents": 0,
        "satisfaction_credit_cents": 0,
        "total_cents": 0,
        "pricing_variant": variant,
        "issued_at": None,
        "dispute_reason": "",
    })
    db.insert("invoices", invoice)
    from services.domain import compute_invoice_fields
    invoice.update(compute_invoice_fields(invoice))
    return success(db.public(invoice), status=201)
