"""Shared route helpers: posture gates, listing and body foreign keys."""

import clock
import lookups
from db import db
from errors import err
from middleware import pagination
from response import array_response
from services import engine
from util import parse_date

SERVICE_CATEGORIES = ("UTILITIES", "RIGGING", "CLEANING", "SECURITY")
VENDOR_CATEGORIES = SERVICE_CATEGORIES + ("CATERING",)
VENDOR_TIERS = ("EXCLUSIVE", "PREFERRED", "OPEN")
ORGANIZATION_TYPES = ("NATIONAL_ASSOCIATION", "LOCAL_ORGANIZATION", "PROMOTER")
SPACE_CLASSES = ("HALL", "BALLROOM", "MEETING_ROOM")
EVENT_CLASSES = ("CITYWIDE_CONVENTION", "LOCAL_EVENT", "CONSUMER_SHOW")
USAGE_KINDS = ("MOVE_IN", "SHOW", "DARK", "MOVE_OUT", "HOLDOVER")
LINE_KINDS = ("RENTAL", "SERVICE", "LABOR", "CATERING", "ADJUSTMENT")
ARRANGEMENT_TYPES = ("IN_HOUSE", "OUTSIDE_EXCEPTION")
EXCEPTION_REASONS = ("ETHNIC_CUISINE", "SPONSOR_PRODUCT_SAMPLING", "RELIGIOUS_DIETARY")
PROJECT_KINDS = ("ROUTINE_MAINTENANCE", "CAPITAL_PROJECT")
SETTLEMENT_BASES = ("CONTRACTED", "ACTUAL_USAGE")


def listing(rows, order=None):
    """Paginate an already-filtered row list and build the array envelope."""
    limit, offset = pagination()
    if order is not None:
        rows = sorted(rows, key=order)
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response(page, total, limit, offset)


def body_fk(body, field, kind, required=True):
    """Resolve a foreign key carried in the request body (ladder step 5)."""
    value = body.get(field)
    if value is None:
        if not required:
            return None
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    if not isinstance(value, str) or value.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a string identifier." % field)
    return lookups.fetch(kind, value)


def posture_of(booking):
    """The derived order posture, computed without mutating the row."""
    return engine.derive_order_posture(booking, db.clients.get(booking["client_id"]))


def require_posture(booking, allowed=("OPEN",)):
    if posture_of(booking) not in allowed:
        raise err("ERR_ORDER_POSTURE_NOT_OPEN")


def require_standing(client):
    if client is not None and client.get("booking_standing") != "GOOD":
        raise err("ERR_CLIENT_HOLD_RESTRICTED")


def require_coi_current(vendor):
    expiry = parse_date(vendor["coi_expiry_date"])
    if expiry is None or expiry <= clock.today():
        raise err("ERR_VENDOR_COI_EXPIRED")


def policy_window_of_booking(booking):
    window = db.policy_windows.get(booking.get("policy_window_id") or "")
    if window is None:
        window = lookups.policy_window_for_class(booking["event_class"])
    return window
