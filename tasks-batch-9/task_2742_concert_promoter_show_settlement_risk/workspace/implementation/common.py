"""Authentication, authorization, existence resolution and state guards.

The order in which a handler calls these helpers is the validation priority
order of PRD 2.9.
"""

from flask import request

from errors import ApiError
from store import db
import store
import validation

KNOWN_ROLES = ("TalentBuyer", "ArtistRep", "VenueOperator", "TourAccountant",
               "RiskOfficer")

ALL_ROLES = KNOWN_ROLES
READ_ROLES = KNOWN_ROLES
STAFF_ROLES = ("TalentBuyer", "TourAccountant", "RiskOfficer")


def auth(*allowed):
    """Priorities 1 and 2: authentication then role authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in KNOWN_ROLES or role not in allowed:
        raise ApiError("ERR_ROLE_FORBIDDEN",
                       "role %s may not call this endpoint" % role)
    return user_id, role


# ---------------------------------------------------------------------------
# existence (priorities 4-14)
# ---------------------------------------------------------------------------

def _fetch(table, entity_id, error_id):
    if entity_id is None:
        return None
    row = table.get(entity_id)
    if row is None:
        raise ApiError(error_id, "%s does not exist" % entity_id)
    return row


def get_market(market_id):
    return _fetch(db.markets, market_id, "ERR_MARKET_NOT_FOUND")


def get_artist(artist_id):
    return _fetch(db.artists, artist_id, "ERR_ARTIST_NOT_FOUND")


def get_venue(venue_id):
    return _fetch(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")


def get_show(show_id):
    return _fetch(db.shows, show_id, "ERR_SHOW_NOT_FOUND")


def get_offer(offer_id):
    return _fetch(db.offers, offer_id, "ERR_OFFER_NOT_FOUND")


def get_line(line_id):
    return _fetch(db.budget_lines, line_id, "ERR_BUDGET_LINE_NOT_FOUND")


def get_invoice(invoice_id):
    return _fetch(db.vendor_invoices, invoice_id, "ERR_VENDOR_INVOICE_NOT_FOUND")


def get_tier(tier_id):
    return _fetch(db.ticket_tiers, tier_id, "ERR_TICKET_TIER_NOT_FOUND")


def get_hold(hold_id):
    return _fetch(db.ticket_holds, hold_id, "ERR_TICKET_HOLD_NOT_FOUND")


def get_settlement(settlement_id):
    return _fetch(db.settlements, settlement_id, "ERR_SETTLEMENT_NOT_FOUND")


def get_event(event_id):
    return _fetch(db.cancellation_events, event_id,
                  "ERR_CANCELLATION_EVENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# related-row helpers
# ---------------------------------------------------------------------------

def venue_of(show):
    return db.venues.get(show["venue_id"])


def market_of(show):
    return db.markets.get(show["market_id"])


def artist_of(show):
    return db.artists.get(show["artist_id"])


def show_of_tier(tier):
    return db.shows.get(tier["show_id"])


def show_of_hold(hold):
    tier = db.ticket_tiers.get(hold["ticket_tier_id"])
    return db.shows.get(tier["show_id"]) if tier else None


# ---------------------------------------------------------------------------
# ownership (priority 15)
# ---------------------------------------------------------------------------

def require_show_owner(show, user_id, role, artist_ok=True, venue_ok=True):
    if role == "ArtistRep":
        if not artist_ok or show["artist_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "caller does not represent this act")
    elif role == "VenueOperator":
        if not venue_ok or show["venue_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "caller does not operate this venue")


def not_owner():
    raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own this resource")


# ---------------------------------------------------------------------------
# optimistic concurrency (priority 16)
# ---------------------------------------------------------------------------

def check_show_version(show, expected):
    if expected != show["version"]:
        raise ApiError("ERR_STALE_SHOW_VERSION",
                       "show version is %d" % show["version"])


# ---------------------------------------------------------------------------
# state guards (priorities 17 and 18)
# ---------------------------------------------------------------------------

TERMINAL_SHOW_STATUS = ("SETTLED", "CANCELLED", "RESCHEDULED")
TERMINAL_SALES_STATUS = ("CLOSED",)
TERMINAL_OFFER = ("ACCEPTED", "WITHDRAWN", "SUPERSEDED", "EXPIRED")
TERMINAL_INVOICE = ("APPROVED", "REJECTED")
TERMINAL_TIER = ("CLOSED",)
TERMINAL_HOLD = ("RELEASED", "CONVERTED", "EXPIRED")
TERMINAL_SETTLEMENT = ("PAID",)
TERMINAL_EVENT = ("CLAIM_SETTLED", "CLAIM_DENIED", "RESCHEDULED")


def invalid_state(message="resource is not in a state that allows this action"):
    raise ApiError("ERR_INVALID_STATE", message)


def already_terminal(state):
    raise ApiError("ERR_ALREADY_TERMINAL", "resource is already %s" % state)


def state_guard(current, allowed_from, terminal):
    """A target sitting in one of its own terminal states reports priority 18;
    any other undeclared transition reports priority 17."""
    if current in terminal:
        already_terminal(current)
    if current not in allowed_from:
        invalid_state("current state %s has no declared transition" % current)


def require(condition, message="precondition not met"):
    if not condition:
        invalid_state(message)


# ---------------------------------------------------------------------------
# segregation of duties (priority 19)
# ---------------------------------------------------------------------------

def require_different_actor(user_id, earlier_user_id, message):
    if earlier_user_id is not None and user_id == earlier_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", message)


# ---------------------------------------------------------------------------
# list helpers
# ---------------------------------------------------------------------------

def filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_fk(name, resolver):
    value = filter_arg(name)
    if value is None:
        return None
    resolver(value)
    return value


def listing(rows, serializer):
    limit, offset = validation.pagination()
    ordered = store.by_seq(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(row) for row in page], limit, offset, total
