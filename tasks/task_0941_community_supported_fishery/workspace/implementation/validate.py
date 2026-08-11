"""Screening-ladder rungs 4, 5 and 6 (PRD 2.5).

RUNG 5 IS A CLOSED IFF-LIST.  PRD 2.5 rung 5: "This rung owns exactly and only
the following fields, and no other field in the system routes an out-of-list
value here".  Every call site that raises ERR_INVALID_ENUM goes through
enum_field() below, and enum_field() is called from exactly the seventeen
places the rung names -- see ENUM_ROUTING_TABLE at the bottom of this module
for the full closed list, including the deliberate exclusions.
"""
from decimal import Decimal, InvalidOperation

import clock
from errors import ApiError


def body_of(request):
    """A request body, tolerant of an absent or non-object payload.

    Rung 4 only asks whether required fields are present; a body that is not a
    JSON object simply has none of them.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


# --------------------------------------------------------------------------
# Rung 4 -- required fields
# --------------------------------------------------------------------------

def require(body, *names):
    """Rung 4: every field the endpoint marks required is present and non-null.

    "Unknown fields in a request body are ignored rather than rejected."
    """
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError("ERR_VALIDATION", "Field '%s' is required." % name)


# --------------------------------------------------------------------------
# Rung 5 -- enum membership (the closed list)
# --------------------------------------------------------------------------

def enum_field(value, allowed, name):
    """Rung 5: ERR_INVALID_ENUM.  Only the rung-5 fields reach this function."""
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_ENUM",
                       "Field '%s' carries a value outside its declared member list." % name)
    return value


def enum_list_field(value, allowed, name):
    """Rung 5 for an array whose *members* are enum-typed (gear_types,
    permitted_gears).  A non-array or empty array is a rung-6 format failure,
    not a rung-5 one; only an out-of-list member routes to ERR_INVALID_ENUM."""
    if not isinstance(value, list) or len(value) == 0:
        raise ApiError("ERR_VALIDATION",
                       "Field '%s' must be a non-empty array." % name)
    for item in value:
        enum_field(item, allowed, name)
    return list(value)


# --------------------------------------------------------------------------
# Rung 6 -- numeric and format constraints
# --------------------------------------------------------------------------

def _bad(name, why):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (name, why))


def int_field(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def cents_field(value, name, minimum=0):
    """PRD 2.5 rung 6: "cents are non-negative integers"."""
    return int_field(value, name, minimum=minimum)


def bool_field(value, name):
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def string_field(value, name, min_len=1, max_len=None):
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def _decimal_of(value, name):
    if isinstance(value, bool):
        _bad(name, "must be a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            _bad(name, "must be a number")
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            _bad(name, "must be a number")
    _bad(name, "must be a number")


def _decimals_of(dec):
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int):
        return 99
    return max(0, -exponent)


def pounds_field(value, name, positive=True):
    """PRD 2.5 rung 6: "Pounds are strictly positive with at most two decimal
    places"."""
    dec = _decimal_of(value, name)
    if not dec.is_finite():
        _bad(name, "must be a finite number")
    if _decimals_of(dec) > 2:
        _bad(name, "must carry at most two decimal places")
    if positive and dec <= 0:
        _bad(name, "must be strictly positive")
    return dec.quantize(Decimal("0.01"))


def decimal_field(value, name, max_decimals=1):
    """A signed number carrying at most max_decimals decimal places."""
    dec = _decimal_of(value, name)
    if not dec.is_finite():
        _bad(name, "must be a finite number")
    if _decimals_of(dec) > max_decimals:
        _bad(name, "must carry at most %d decimal place(s)" % max_decimals)
    return dec


def datetime_field(value, name):
    """PRD 2.5 rung 6: "datetimes parse as ISO 8601 UTC"."""
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 UTC instant")
    parsed = clock.parse_instant(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC instant")
    return parsed


def string_array_field(value, name, allow_empty=True):
    """An array of opaque string codes.

    Deliberately NOT a rung-5 site: PRD 2.5 rung 5 does not name a member's
    allergy_exclusions or dislikes, nor a season's offered_species members, so
    an unrecognised code in one of those arrays cannot produce
    ERR_INVALID_ENUM.  Shape failures are rung-6 ERR_VALIDATION.
    """
    if not isinstance(value, list):
        _bad(name, "must be an array")
    if not allow_empty and len(value) == 0:
        _bad(name, "must be a non-empty array")
    for item in value:
        if not isinstance(item, str):
            _bad(name, "must be an array of strings")
    return list(value)


def id_field(value, name):
    """A body foreign key.  Shape only -- existence is rungs 7 to 21."""
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be a non-empty string identifier")
    return value


# --------------------------------------------------------------------------
# The closed rung-5 routing table, kept next to the code that enforces it.
# --------------------------------------------------------------------------

ENUM_ROUTING_TABLE = {
    # ---- routes to ERR_INVALID_ENUM (the complete rung-5 list) ------------
    "SharePlan.share_size": "ERR_INVALID_ENUM",
    "SharePlan.delivery_frequency": "ERR_INVALID_ENUM",
    "SharePlan.species_tier": "ERR_INVALID_ENUM",
    "Season.ambient_band": "ERR_INVALID_ENUM",
    "DeliveryZone.fee_tier": "ERR_INVALID_ENUM",
    "Subscription.fulfillment_mode": "ERR_INVALID_ENUM",
    "Subscription.payment_basis": "ERR_INVALID_ENUM",
    "Vessel.gear_types[]": "ERR_INVALID_ENUM",
    "QuotaLedger.species": "ERR_INVALID_ENUM",
    "QuotaLedger.permitted_gears[]": "ERR_INVALID_ENUM",
    "Trip.gear_type": "ERR_INVALID_ENUM",
    "LandingLot.species (POST /csf/trips/{id}/land)": "ERR_INVALID_ENUM",
    "SubLot.destination_type (destinations[])": "ERR_INVALID_ENUM",
    "ColdChainEvent.custody_leg": "ERR_INVALID_ENUM",
    "RecallNotice.reason": "ERR_INVALID_ENUM",
    "disposition (POST /csf/landing-lots/{id}/disposition)": "ERR_INVALID_ENUM",
    "target_status (POST /csf/vessels/{id}/compliance)": "ERR_INVALID_ENUM",
    # ---- deliberate exclusions: no other field routes to ERR_INVALID_ENUM --
    "Season.offered_species[]": "ERR_VALIDATION (shape only; membership unchecked)",
    "Member.allergy_exclusions[]": "ERR_VALIDATION (shape only; membership unchecked)",
    "Member.dislikes[]": "ERR_VALIDATION (shape only; membership unchecked)",
    "GET filters lifecycle_status / fulfillment_status / week_index":
        "no error at all -- a filter that matches nothing returns an empty page",
    "numeric range violations (total_weeks, week_index, grace_minutes, "
    "area_sensitivity_penalty, species_stock_adjustment, cooler_slots_*, "
    "landing_commit_lead_hours, transit_hours, pounds, cents, minutes)":
        "ERR_VALIDATION",
    "booleans (accepted, allow_partial_fill, waitlist_requested, "
    "never_substitute, is_serviceable, standing_reset, area_closed)":
        "ERR_VALIDATION",
    "body foreign keys (season_id, member_id, share_plan_id, ...)":
        "their own ERR_*_NOT_FOUND at rungs 7 to 21",
    "a resource addressed in the wrong state": "ERR_INVALID_STATE",
}
