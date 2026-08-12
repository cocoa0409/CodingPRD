"""Corporate action event routes: scrubbing, confirm, amendments, cancel,
capture, book, complete; bookings and booking lines."""

from flask import Blueprint

import db
import util
import errors as errmod
from errors import ApiError
from helpers import (respond, respond_list, require_roles, body, req_str,
                     opt_int, opt_bool, req_enum, req_date, opt_datetime,
                     paginate, apply_filters, stamp_new, stamp_immutable, touch)
from domain import (EVENT_TYPES, CLAIM_BASES, validate_terms,
                    get_event_or_404, event_terminal_guard,
                    generate_projected_entitlements, new_entitlement,
                    compute_entitlement_fields, recompute_account,
                    event_entitlements)
from booking import run_booking, reverse_booking

bp = Blueprint("events", __name__)

ALL = ("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
       "AccountHolder ClaimsExaminer CustodianFeed").split()


# ---------------------------------------------------------------------------
# event creation (scrubbing, PRD 3.3)
# ---------------------------------------------------------------------------

@bp.post("/api/events")
def create_event():
    user_id = require_roles("EventAnalyst")
    data = body()
    # --- priority 3: request shape + terms coherence ---
    security_id = req_str(data, "security_id")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    if "terms" not in data or data["terms"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400, "Required field missing: terms")
    terms = data["terms"]
    record_date_s, record_date = req_date(data, "record_date")
    payable_date_s, payable_date = req_date(data, "payable_date")
    if "source_notification_ids" not in data or data["source_notification_ids"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: source_notification_ids")
    notif_ids = data["source_notification_ids"]
    if not isinstance(notif_ids, list) or any(not isinstance(x, str) for x in notif_ids):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "source_notification_ids must be an array of strings")
    election_required = opt_bool(data, "election_required", False)
    election_deadline_s, election_deadline = opt_datetime(data, "election_deadline")
    compensation_pool = opt_int(data, "compensation_pool_cents", 0)
    if compensation_pool < 0:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "compensation_pool_cents must be non-negative")
    claim_basis = data.get("claim_compensation_basis", "EVENT_TERMS")
    if claim_basis not in CLAIM_BASES:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "claim_compensation_basis must be EVENT_TERMS or MARKET_VALUE")
    validate_terms(event_type, terms)
    if record_date > payable_date:
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "record_date must not fall after payable_date")
    if election_required and election_deadline is None:
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "election_deadline is required when election_required is true")
    if election_deadline is not None:
        # must fall no later than the end of the payable date's day
        if election_deadline >= util.midnight_utc(util.date_plus_days(payable_date, 1)):
            raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                           "election_deadline must be <= payable_date end-of-day")

    # --- priority 4: existence, body FKs in declared field order ---
    security = db.get("securities", security_id)
    if security is None:
        raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404, "Security not found")
    # terms-internal security references
    for key in ("new_security_id", "spinoff_security_id"):
        ref = terms.get(key)
        if ref is not None and db.get("securities", ref) is None:
            raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404,
                           "Security not found: terms.%s" % key)
    notifications = []
    for nid in notif_ids:
        n = db.get("source_notifications", nid)
        if n is None:
            raise ApiError(errmod.E_SOURCE_NOTIFICATION_NOT_FOUND, 404,
                           "Source notification not found")
        notifications.append(n)

    # --- priority 9: business constraints (scaffold order) ---
    if security["status"] != "ACTIVE":
        raise ApiError(errmod.E_SECURITY_SUSPENDED, 409,
                       "Security is SUSPENDED")
    if not election_required:
        for other in db.all_rows("events"):
            if other["security_id"] != security_id:
                continue
            if other["status"] == "CANCELLED" or other["election_required"]:
                continue
            o_rec = util.parse_date_iso(other["record_date"])
            o_pay = util.parse_date_iso(other["payable_date"])
            # half-open windows [record_date, payable_date); touching allowed
            if record_date < o_pay and o_rec < payable_date:
                raise ApiError(errmod.E_EVENT_WINDOW_OVERLAP, 409,
                               "Mandatory event window overlaps another event")
    # scrub-set integrity
    def scrub_fail(msg):
        raise ApiError(errmod.E_NOTIFICATION_SCRUB_MISMATCH, 409, msg)
    if len(notifications) < 2:
        scrub_fail("Scrub set must contain at least two notifications")
    if len({n["source_id"] for n in notifications}) != len(notifications):
        scrub_fail("Scrub set notifications must come from distinct sources")
    for n in notifications:
        if n["status"] != "RECEIVED":
            scrub_fail("Scrub set notifications must all be RECEIVED")
        if (n["security_id"] != security_id or n["event_type"] != event_type
                or n["record_date"] != record_date_s):
            scrub_fail("Notifications must match the request on security, "
                       "event type, and record date")
    # winner: highest source reliability_weight, tie -> earliest created_at
    def weight(n):
        src = db.get("event_sources", n["source_id"])
        return src["reliability_weight"] if src else 0
    winner = max(notifications, key=lambda n: (weight(n), -n["_seq"]))
    if terms != winner["announced_terms"]:
        scrub_fail("Submitted terms must equal the winning notification's "
                   "announced_terms")

    # --- create ---
    event = {
        "security_id": security_id,
        "event_type": event_type,
        "election_required": election_required,
        "terms": terms,
        "record_date": record_date_s,
        "payable_date": payable_date_s,
        "election_deadline": election_deadline_s,
        "compensation_pool_cents": compensation_pool,
        "compensation_pool_remaining_cents": compensation_pool,
        "claim_compensation_basis": claim_basis,
        "scrubbed_by_user_id": user_id,
        "confirmed_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(event)
    db.insert("events", event)
    for n in notifications:
        n["status"] = "MATCHED"  # immutable record: status flip only
    return respond(db.public(event), 201)


@bp.get("/api/events")
def list_events():
    require_roles(*ALL)
    rows = apply_filters(db.all_rows("events"), [
        ("security_id", "security_id"),
        ("status", "status"),
        ("event_type", "event_type"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/events/<rid>")
def get_event(rid):
    require_roles(*ALL)
    return respond(db.public(get_event_or_404(rid)), 200)


# ---------------------------------------------------------------------------
# confirm (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/api/events/<rid>/confirm")
def confirm_event(rid):
    user_id = require_roles("EventAnalyst")
    event = get_event_or_404(rid)
    # state: confirm requires DRAFT|AMENDED
    event_terminal_guard(event)
    if event["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Event is not in a confirmable state")
    # segregation of duties
    if user_id == event["scrubbed_by_user_id"]:
        raise ApiError(errmod.E_SEGREGATION_OF_DUTIES, 403,
                       "Confirmer must differ from the scrubbing analyst")
    from_draft = event["status"] == "DRAFT"
    event["confirmed_by_user_id"] = user_id
    event["status"] = "CONFIRMED"
    touch(event)
    if from_draft:
        # the first confirmation projects entitlements; a re-confirmation after
        # amendment does not duplicate them (amendment already re-projected)
        generate_projected_entitlements(event)
    return respond(db.public(event), 200)


# ---------------------------------------------------------------------------
# amendments (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/api/events/<rid>/amendments")
def apply_amendment(rid):
    user_id = require_roles("EventAnalyst")
    data = body()
    # shape
    if "amended_terms" not in data or data["amended_terms"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: amended_terms")
    amended_terms = data["amended_terms"]
    reason = req_str(data, "reason")
    if "expected_event_version" not in data or data["expected_event_version"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: expected_event_version")
    expected_version = data["expected_event_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "expected_event_version must be an integer")
    # existence
    event = get_event_or_404(rid)
    validate_terms(event["event_type"], amended_terms)
    for key in ("new_security_id", "spinoff_security_id"):
        ref = amended_terms.get(key)
        if ref is not None and db.get("securities", ref) is None:
            raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404,
                           "Security not found: terms.%s" % key)
    # state: amendment requires CONFIRMED
    event_terminal_guard(event)
    if event["status"] != "CONFIRMED":
        raise ApiError(errmod.E_EVENT_NOT_AMENDABLE, 409,
                       "Amendment requires a CONFIRMED event")
    # OCC
    if expected_version != event["version"]:
        raise ApiError(errmod.E_STALE_EVENT_VERSION, 412,
                       "expected_event_version does not match the event version")

    prior_count = sum(1 for a in db.all_rows("event_amendments")
                      if a["event_id"] == rid)
    amendment = {
        "event_id": rid,
        "amended_terms": amended_terms,
        "reason": reason,
        "amendment_seq": prior_count + 1,
        "applied_by_user_id": user_id,
    }
    stamp_immutable(amendment)
    db.insert("event_amendments", amendment)

    event["terms"] = amended_terms
    event["status"] = "AMENDED"
    touch(event)

    # re-project the world: PROJECTED/FIRM -> SUPERSEDED, replacement per
    # superseded entitlement linked via supersedes_entitlement_id
    affected_accounts = set()
    for ent in event_entitlements(rid, statuses=("PROJECTED", "FIRM")):
        ent["status"] = "SUPERSEDED"
        touch(ent)
        new_entitlement(event, ent["account_id"], supersedes_id=ent["id"])
        affected_accounts.add(ent["account_id"])
    for aid in affected_accounts:
        recompute_account(aid)
    return respond(db.public(amendment), 201)


@bp.get("/api/events/<rid>/amendments")
def list_amendments(rid):
    require_roles(*ALL)
    get_event_or_404(rid)
    rows = [a for a in db.all_rows("event_amendments") if a["event_id"] == rid]
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


# ---------------------------------------------------------------------------
# cancel (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/api/events/<rid>/cancel")
def cancel_event(rid):
    require_roles("EventAnalyst")
    event = get_event_or_404(rid)
    event_terminal_guard(event)
    affected_accounts = set()
    for ent in event_entitlements(rid, statuses=("PROJECTED", "FIRM")):
        ent["status"] = "SUPERSEDED"
        touch(ent)
        affected_accounts.add(ent["account_id"])
    for el in db.all_rows("elections"):
        if el["event_id"] == rid and el["status"] in ("SUBMITTED", "WITHDRAWN"):
            el["status"] = "VOID"
            touch(el)
    event["status"] = "CANCELLED"
    touch(event)
    for aid in affected_accounts:
        recompute_account(aid)
    return respond(db.public(event), 200)


# ---------------------------------------------------------------------------
# capture record position (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.post("/api/events/<rid>/capture-record-position")
def capture_record_position(rid):
    require_roles("OperationsManager")
    event = get_event_or_404(rid)
    event_terminal_guard(event)
    if event["status"] != "CONFIRMED":
        raise ApiError(errmod.E_EVENT_NOT_CONFIRMED, 409,
                       "Capture requires a CONFIRMED event")
    record_midnight = util.midnight_utc(util.parse_date_iso(event["record_date"]))
    if util.now_dt() < record_midnight:
        raise ApiError(errmod.E_RECORD_DATE_NOT_REACHED, 422,
                       "Record date has not been reached")
    for ent in event_entitlements(rid, statuses=("PROJECTED",)):
        fields = compute_entitlement_fields(event, ent["account_id"], "SETTLED_BASIS")
        ent["calculation_basis"] = "SETTLED_BASIS"
        ent["record_position_quantity"] = fields["record_position_quantity"]
        ent["entitled_shares"] = fields["entitled_shares"]
        ent["fractional_shares"] = fields["fractional_shares"]
        ent["cash_in_lieu_cents"] = fields["cash_in_lieu_cents"]
        ent["cash_amount_cents"] = fields["cash_amount_cents"]
        ent["status"] = "FIRM"
        touch(ent)
    return respond(db.public(event), 200)


# ---------------------------------------------------------------------------
# book (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.post("/api/events/<rid>/book")
def book_event(rid):
    user_id = require_roles("OperationsManager")
    event = get_event_or_404(rid)
    event_terminal_guard(event)
    if event["status"] != "CONFIRMED":
        raise ApiError(errmod.E_EVENT_NOT_CONFIRMED, 409,
                       "Booking requires a CONFIRMED event")
    for ent in event_entitlements(rid):
        if ent["status"] not in ("FIRM", "SUPERSEDED"):
            raise ApiError(errmod.E_ENTITLEMENTS_NOT_FIRM, 409,
                           "A non-SUPERSEDED entitlement is still PROJECTED")
    if event["election_required"]:
        deadline = util.parse_datetime_iso(event["election_deadline"])
        if util.now_dt() <= deadline:
            raise ApiError(errmod.E_ELECTION_WINDOW_OPEN, 422,
                           "Booking a voluntary event requires the clock to be "
                           "strictly after the election deadline")
    booking = run_booking(event, user_id)
    return respond(db.public(booking), 201)


@bp.get("/api/events/<rid>/bookings")
def list_event_bookings(rid):
    require_roles(*ALL)
    get_event_or_404(rid)
    rows = [b for b in db.all_rows("bookings") if b["event_id"] == rid]
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


# ---------------------------------------------------------------------------
# complete (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/api/events/<rid>/complete")
def complete_event(rid):
    require_roles("OperationsManager")
    event = get_event_or_404(rid)
    event_terminal_guard(event)
    if event["status"] != "BOOKED":
        raise ApiError(errmod.E_EVENT_NOT_BOOKED, 409,
                       "Completion requires a BOOKED event")
    for ent in event_entitlements(rid):
        if ent["status"] not in ("SETTLED", "COMPENSATED", "SUPERSEDED"):
            raise ApiError(errmod.E_UNSETTLED_ENTITLEMENTS_EXIST, 409,
                           "A non-SUPERSEDED entitlement is not settled or compensated")
    for brk in db.all_rows("recon_breaks"):
        if brk["event_id"] == rid and brk["status"] == "OPEN":
            raise ApiError(errmod.E_OPEN_RECON_BREAKS_EXIST, 409,
                           "An OPEN recon break references this event")
    event["status"] = "COMPLETED"
    touch(event)
    return respond(db.public(event), 200)


# ---------------------------------------------------------------------------
# bookings / booking lines
# ---------------------------------------------------------------------------

@bp.get("/api/bookings/<rid>")
def get_booking(rid):
    require_roles(*ALL)
    booking = db.get("bookings", rid)
    if booking is None:
        raise ApiError(errmod.E_BOOKING_NOT_FOUND, 404, "Booking not found")
    return respond(db.public(booking), 200)


@bp.post("/api/bookings/<rid>/reverse")
def reverse_booking_route(rid):
    require_roles("OperationsManager")
    booking = db.get("bookings", rid)
    if booking is None:
        raise ApiError(errmod.E_BOOKING_NOT_FOUND, 404, "Booking not found")
    if booking["status"] != "POSTED":
        raise ApiError(errmod.E_BOOKING_NOT_REVERSIBLE, 409,
                       "Only a POSTED booking can be reversed")
    settled_ent_ids = set()
    for line in db.all_rows("booking_lines"):
        if line["booking_id"] == rid:
            settled_ent_ids.add(line["entitlement_id"])
    for claim in db.all_rows("claims"):
        if (claim["entitlement_id"] in settled_ent_ids
                and claim["payment_status"] == "PAID"):
            raise ApiError(errmod.E_BOOKING_NOT_REVERSIBLE, 409,
                           "A PAID claim references an entitlement settled by "
                           "this booking")
    reverse_booking(booking)
    return respond(db.public(booking), 200)


@bp.get("/api/booking-lines")
def list_booking_lines():
    require_roles(*ALL)
    rows = apply_filters(db.all_rows("booking_lines"), [
        ("booking_id", "booking_id"),
        ("position_lot_id", "position_lot_id"),
        ("entitlement_id", "entitlement_id"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/booking-lines/<rid>")
def get_booking_line(rid):
    require_roles(*ALL)
    line = db.get("booking_lines", rid)
    if line is None:
        raise ApiError(errmod.E_BOOKING_LINE_NOT_FOUND, 404, "Booking line not found")
    return respond(db.public(line), 200)
