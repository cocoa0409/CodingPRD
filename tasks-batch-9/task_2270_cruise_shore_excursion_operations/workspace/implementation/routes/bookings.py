"""Bookings: sale, ticketing, check-in, no-show, cancellation, incidents, ledger."""

from datetime import timedelta

from flask import Blueprint

from db import db
from errors import fail
from middleware import DESK, FINANCE, GUEST, MANAGER, RISK, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import booking_json, incident_json, ledger_json
from services.allocation import channel_available, recompute_seats
from services.cascades import (CHECKIN_GRACE_MINUTES, CHECKIN_OPEN_MINUTES,
                               SALES_CUTOFF_MINUTES, cancel_booking_by_guest,
                               commission_rate_for_departure, mark_no_show,
                               operator_for_departure)
from services.commission import provisional_line_cents
from services.eligibility import age_at_meeting, screen
from services.timing import recompute_projections
from util import minutes_between
from validation import (booking_or_404, departure_or_404, f, guest_or_404, ledger_or_404,
                        paginate, pagination, query_values, validate_body)

bp = Blueprint("bookings", __name__)

CHANNELS = ("PRE_CRUISE", "ONBOARD")
LANGUAGES = ("EN", "ES", "DE", "FR", "IT", "PT", "ZH")
FULFILLMENT_STATUSES = ("BOOKED", "TICKETED", "CHECKED_IN", "COMPLETED", "NO_SHOW",
                        "CANCELLED_BY_GUEST", "CANCELLED_BY_LINE")
FINANCIAL_STATUSES = ("AUTHORIZED", "CHARGED", "PARTIALLY_REFUNDED", "REFUNDED",
                      "RETAINED", "VOIDED")
FULFILLMENT_ACTIONS = ("TICKET", "CHECK_IN", "MARK_NO_SHOW")
ENTRY_KINDS = ("REFUND", "AUTH_VOID", "GOODWILL_CREDIT", "REPATRIATION_ALLOWANCE", "RETENTION")
BASES = ("GUEST_INITIATED", "LINE_CANCELLED_WEATHER", "LINE_CANCELLED_OPERATIONAL",
         "NO_SHOW", "RETURN_GUARANTEE_BREACH")
INCIDENT_CATEGORIES = ("INJURY", "MEDICAL", "PROPERTY_LOSS", "LEFT_BEHIND", "SERVICE_FAILURE")
INCIDENT_SEVERITIES = ("MINOR", "MODERATE", "SEVERE")

CANCELLED_DEPARTURE_STATES = ("OPERATING", "COMPLETED", "CANCELLED_WEATHER",
                              "CANCELLED_OPERATIONAL")
LIVE_DEPARTURE_STATES = ("SELLING", "CLOSED")

BOOKING_READ_ROLES = (GUEST, DESK, MANAGER, RISK, FINANCE)
LEDGER_READ_ROLES = (GUEST, DESK, FINANCE, RISK)
INCIDENT_READ_ROLES = (DESK, RISK, MANAGER)

BOOKING_CREATE = [
    f("departure_id", "string", required=True),
    f("guest_id", "string", required=True),
    f("party_size", "int", required=True, lo=1, hi=20),
    f("channel", "enum", required=True, enum=CHANNELS),
    f("language_choice", "enum", required=True, enum=LANGUAGES),
    f("expected_departure_version", "int", required=True, lo=0),
    f("medical_warning_acknowledged", "bool"),
]

FULFILLMENT_ACTION = [
    f("action", "enum", required=True, enum=FULFILLMENT_ACTIONS),
    f("note", "string"),
]

BOOKING_CANCEL = [
    f("reason_code", "string"),
]

INCIDENT_CREATE = [
    f("category", "enum", required=True, enum=INCIDENT_CATEGORIES),
    f("severity", "enum", required=True, enum=INCIDENT_SEVERITIES),
    f("occurred_utc", "instant", required=True),
    f("narrative", "string", required=True),
]


def _guard_booking_ownership(caller, booking_id):
    """Priority 3: a Guest caller may only reach their own bookings."""
    if caller.role != GUEST:
        return
    booking = db.bookings.get(booking_id)
    if booking is not None and booking["guest_id"] != caller.user_id:
        fail("ERR_BOOKING_NOT_OWNED", "a guest may only reach their own bookings")


def _guard_entry_ownership(caller, entry_id):
    if caller.role != GUEST:
        return
    entry = db.ledger.get(entry_id)
    if entry is None:
        return
    booking = db.bookings.get(entry["booking_id"])
    if booking is not None and booking["guest_id"] != caller.user_id:
        fail("ERR_BOOKING_NOT_OWNED", "a guest may only reach their own ledger entries")


@bp.post(API_PREFIX + "/bookings")
@endpoint(GUEST, DESK)
def create_booking(caller):
    body = validate_body(BOOKING_CREATE)
    departure = departure_or_404(body["departure_id"])
    guest = guest_or_404(body["guest_id"])

    if body["expected_departure_version"] != departure["version"]:
        fail("ERR_STALE_DEPARTURE_VERSION", "the departure has been modified since it was read")

    # a booking attempt never materialises the clock-driven closure
    recompute_projections(departure)
    if departure["status"] != "SELLING":
        fail("ERR_DEPARTURE_NOT_SELLING", "the departure is not selling seats")

    excursion = db.excursions.get(departure["excursion_id"])
    call = db.port_calls.get(departure["port_call_id"])
    party_size = body["party_size"]
    channel = body["channel"]
    acknowledged = body.get("medical_warning_acknowledged", False)
    age = age_at_meeting(guest, departure["meeting_time_utc"])

    screen(guest, excursion, age, body["language_choice"], acknowledged)

    if call is None or guest["voyage_code"] != call["voyage_code"]:
        fail("ERR_VOYAGE_MISMATCH", "the guest is not sailing the voyage this call belongs to")

    if minutes_between(db.now(), departure["meeting_time_utc"]) <= SALES_CUTOFF_MINUTES:
        fail("ERR_SALES_CUTOFF_PASSED", "sales closed 60 minutes before the meeting time")

    if party_size > channel_available(departure, channel):
        fail("ERR_CHANNEL_ALLOCATION_EXHAUSTED",
             "the %s channel has no room for %s seats" % (channel, party_size))

    from services.pricing import quote
    money = quote(excursion, guest, departure, channel, party_size)

    row = db.insert("bookings", {
        "departure_id": departure["id"],
        "guest_id": guest["id"],
        "alternative_departure_id": None,
        "party_size": party_size,
        "channel": channel,
        "language_choice": body["language_choice"],
        "medical_warning_acknowledged": bool(acknowledged),
        "age_at_meeting": age,
        "per_guest_price_cents": money["per_guest_price_cents"],
        "quoted_total_cents": money["quoted_total_cents"],
        "service_fee_cents": money["service_fee_cents"],
        "charge_total_cents": money["charge_total_cents"],
        "refunded_cents": 0,
        "retained_cents": 0,
        "goodwill_credit_cents": 0,
        "commission_accrued_cents": 0,
        "fulfillment_status": "BOOKED",
        "financial_status": "AUTHORIZED",
        "alternative_offer_status": "NONE",
        "return_guarantee_honored": True,
    })

    recompute_seats(departure)
    db.touch(departure)
    return object_response(booking_json(row), 201)


@bp.get(API_PREFIX + "/bookings/<booking_id>")
@endpoint(*BOOKING_READ_ROLES)
def read_booking(caller, booking_id):
    _guard_booking_ownership(caller, booking_id)
    return object_response(booking_json(booking_or_404(booking_id)))


@bp.get(API_PREFIX + "/bookings")
@endpoint(*BOOKING_READ_ROLES)
def list_bookings(caller):
    limit, offset = pagination()
    filters = query_values([
        f("departure_id", "string"),
        f("guest_id", "string"),
        f("alternative_departure_id", "string"),
        f("fulfillment_status", "enum", enum=FULFILLMENT_STATUSES),
        f("financial_status", "enum", enum=FINANCIAL_STATUSES),
        f("channel", "enum", enum=CHANNELS),
    ])
    rows = db.ordered("bookings")
    for key in ("departure_id", "guest_id", "alternative_departure_id",
                "fulfillment_status", "financial_status", "channel"):
        if key in filters:
            rows = [r for r in rows if r.get(key) == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([booking_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/bookings/<booking_id>/fulfillment-actions")
@endpoint(DESK)
def fulfillment_action(caller, booking_id):
    body = validate_body(FULFILLMENT_ACTION)
    booking = booking_or_404(booking_id)
    action = body["action"]
    departure = db.departures.get(booking["departure_id"])
    call = db.port_calls.get(departure["port_call_id"]) if departure else None

    if action == "TICKET":
        if departure is None or departure["status"] not in LIVE_DEPARTURE_STATES:
            fail("ERR_DEPARTURE_NOT_SELLING", "the departure is no longer open for ticketing")
        if booking["fulfillment_status"] != "BOOKED":
            fail("ERR_INVALID_BOOKING_ACTION",
                 "TICKET is not declared for a %s booking" % booking["fulfillment_status"])
        if booking["financial_status"] != "AUTHORIZED":
            fail("ERR_INVALID_BOOKING_ACTION", "the booking authorisation has already resolved")
        operator = operator_for_departure(departure)
        if operator is None or operator["vetting_status"] != "APPROVED":
            fail("ERR_OPERATOR_NOT_APPROVED", "the delivering operator is not APPROVED")

        booking["fulfillment_status"] = "TICKETED"
        booking["financial_status"] = "CHARGED"
        booking["commission_accrued_cents"] = provisional_line_cents(
            booking, commission_rate_for_departure(departure))
        db.touch(booking)

    elif action == "CHECK_IN":
        if departure is None or departure["status"] not in LIVE_DEPARTURE_STATES:
            fail("ERR_INVALID_DEPARTURE_STATE", "the departure is no longer live")
        if booking["fulfillment_status"] != "TICKETED":
            fail("ERR_INVALID_BOOKING_ACTION",
                 "CHECK_IN is not declared for a %s booking" % booking["fulfillment_status"])
        if call is None or call["status"] != "IN_PORT":
            fail("ERR_INVALID_BOOKING_ACTION", "the owning port call is not IN_PORT")
        meeting = departure["meeting_time_utc"]
        now = db.now()
        if now < meeting - timedelta(minutes=CHECKIN_OPEN_MINUTES) or now > meeting + timedelta(
                minutes=CHECKIN_GRACE_MINUTES):
            fail("ERR_CHECKIN_WINDOW_CLOSED", "the check-in window is not open")

        booking["fulfillment_status"] = "CHECKED_IN"
        db.touch(booking)

    else:  # MARK_NO_SHOW
        if booking["fulfillment_status"] != "TICKETED":
            fail("ERR_INVALID_BOOKING_ACTION",
                 "MARK_NO_SHOW is not declared for a %s booking" % booking["fulfillment_status"])
        mark_no_show(booking, departure)
        db.touch(booking)

    return object_response(booking_json(booking))


@bp.post(API_PREFIX + "/bookings/<booking_id>/cancel")
@endpoint(GUEST, DESK)
def cancel_booking(caller, booking_id):
    _guard_booking_ownership(caller, booking_id)
    body = validate_body(BOOKING_CANCEL)
    booking = booking_or_404(booking_id)
    departure = db.departures.get(booking["departure_id"])

    if departure is None or departure["status"] in CANCELLED_DEPARTURE_STATES:
        fail("ERR_INVALID_DEPARTURE_STATE", "the departure has moved past cancellation")
    if booking["fulfillment_status"] not in ("BOOKED", "TICKETED"):
        fail("ERR_INVALID_BOOKING_ACTION",
             "a %s booking may not be cancelled" % booking["fulfillment_status"])

    cancel_booking_by_guest(booking, departure, body.get("reason_code"))
    return object_response(booking_json(booking))


@bp.post(API_PREFIX + "/bookings/<booking_id>/incidents")
@endpoint(DESK)
def file_incident(caller, booking_id):
    body = validate_body(INCIDENT_CREATE)
    booking = booking_or_404(booking_id)
    if body["occurred_utc"] > db.now():
        fail("ERR_INVALID_TIME_WINDOW", "occurred_utc may not be later than the logical clock")
    if booking["fulfillment_status"] not in ("CHECKED_IN", "COMPLETED", "NO_SHOW"):
        fail("ERR_INVALID_BOOKING_ACTION",
             "an incident needs a booking that reached the shore")

    row = db.insert("incidents", {
        "booking_id": booking["id"],
        "category": body["category"],
        "severity": body["severity"],
        "occurred_utc": body["occurred_utc"],
        "narrative": body["narrative"],
        "filed_by_user_id": caller.user_id,
        "status": "FILED",
    })
    return object_response(incident_json(row), 201)


@bp.get(API_PREFIX + "/refund-ledger-entries/<entry_id>")
@endpoint(*LEDGER_READ_ROLES)
def read_entry(caller, entry_id):
    _guard_entry_ownership(caller, entry_id)
    return object_response(ledger_json(ledger_or_404(entry_id)))


@bp.get(API_PREFIX + "/refund-ledger-entries")
@endpoint(*LEDGER_READ_ROLES)
def list_entries(caller):
    limit, offset = pagination()
    filters = query_values([
        f("booking_id", "string"),
        f("entry_kind", "enum", enum=ENTRY_KINDS),
        f("basis", "enum", enum=BASES),
    ])
    rows = db.ordered("ledger")
    for key in ("booking_id", "entry_kind", "basis"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([ledger_json(r) for r in page], limit, offset, total)
