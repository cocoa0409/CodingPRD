"""Request-shape validation helpers (validation priority 5) plus lookups."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError, invalid
from response import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_LIMIT_MIN,
    PAGINATION_OFFSET_DEFAULT,
    list_response,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ----------------------------------------------------------------- primitives
def parse_datetime(value, field):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % field)
    text = value.strip()
    if not text:
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % field)
    normalised = text
    if normalised.endswith("Z") or normalised.endswith("z"):
        normalised = normalised[:-1] + "+00:00"
    if "T" not in normalised and "t" not in normalised:
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % field)
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        raise invalid("Field '%s' is not a valid ISO 8601 timestamp." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise invalid("The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise invalid("The request body must be a JSON object.")
    return parsed


class Body(object):
    def __init__(self, data=None):
        self.data = body() if data is None else data

    # ---- presence
    def present(self, name):
        return name in self.data and self.data[name] is not None

    def _require_present(self, name):
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        return self.data[name]

    # ---- strings
    def string(self, name, min_len=None, max_len=None, required=True, default=None):
        if not self.present(name):
            if required:
                self._require_present(name)
            return default
        value = self.data[name]
        if not isinstance(value, str):
            raise invalid("Field '%s' must be a string." % name)
        if min_len is not None and len(value) < min_len:
            raise invalid("Field '%s' must be at least %d characters." % (name, min_len))
        if max_len is not None and len(value) > max_len:
            raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
        return value

    def enum(self, name, allowed, required=True, default=None):
        if not self.present(name):
            if required:
                self._require_present(name)
            return default
        value = self.data[name]
        if not isinstance(value, str) or value not in allowed:
            raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
        return value

    def boolean(self, name, required=False, default=None):
        if not self.present(name):
            if required:
                self._require_present(name)
            return default
        value = self.data[name]
        if not isinstance(value, bool):
            raise invalid("Field '%s' must be a boolean." % name)
        return value

    def integer(self, name, minimum=None, maximum=None, required=True, default=None):
        if not self.present(name):
            if required:
                self._require_present(name)
            return default
        value = self.data[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            raise invalid("Field '%s' must be at least %s." % (name, minimum))
        if maximum is not None and value > maximum:
            raise invalid("Field '%s' must be at most %s." % (name, maximum))
        return value

    def number(
        self,
        name,
        minimum=None,
        maximum=None,
        exclusive_minimum=None,
        max_decimals=None,
        required=True,
        default=None,
    ):
        if not self.present(name):
            if required:
                self._require_present(name)
            return default
        value = self.data[name]
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise invalid("Field '%s' must be a number." % name)
        try:
            dec = Decimal(value) if not isinstance(value, Decimal) else value
        except (InvalidOperation, ValueError):
            raise invalid("Field '%s' must be a number." % name)
        if not dec.is_finite():
            raise invalid("Field '%s' must be a finite number." % name)
        if minimum is not None and dec < Decimal(str(minimum)):
            raise invalid("Field '%s' must be at least %s." % (name, minimum))
        if maximum is not None and dec > Decimal(str(maximum)):
            raise invalid("Field '%s' must be at most %s." % (name, maximum))
        if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
            raise invalid("Field '%s' must be greater than %s." % (name, exclusive_minimum))
        if max_decimals is not None:
            exponent = dec.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -max_decimals:
                raise invalid(
                    "Field '%s' must carry at most %d decimal place(s)." % (name, max_decimals)
                )
        return dec

    def timestamp(self, name, required=True):
        if not self.present(name):
            if required:
                self._require_present(name)
            return None, None
        raw_value = self.data[name]
        return parse_datetime(raw_value, name), raw_value

    def date(self, name, required=True):
        if not self.present(name):
            if required:
                self._require_present(name)
            return None
        value = self.data[name]
        if not isinstance(value, str) or not DATE_RE.match(value):
            raise invalid("Field '%s' must be a YYYY-MM-DD date." % name)
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise invalid("Field '%s' must be a real calendar date." % name)
        return value

    def string_set(self, name, allowed, required=True, non_empty=True, default=None):
        if not self.present(name):
            if required:
                self._require_present(name)
            return list(default) if default is not None else default
        value = self.data[name]
        if not isinstance(value, list):
            raise invalid("Field '%s' must be an array." % name)
        if non_empty and len(value) == 0:
            raise invalid("Field '%s' must not be empty." % name)
        seen = set()
        for member in value:
            if not isinstance(member, str) or member not in allowed:
                raise invalid("Field '%s' members must be one of %s." % (name, ", ".join(allowed)))
            if member in seen:
                raise invalid("Field '%s' must not contain duplicates." % name)
            seen.add(member)
        return list(value)

    def string_list(self, name, required=False):
        if not self.present(name):
            if required:
                self._require_present(name)
            return None
        value = self.data[name]
        if not isinstance(value, list):
            raise invalid("Field '%s' must be an array." % name)
        for member in value:
            if not isinstance(member, str) or member == "":
                raise invalid("Field '%s' members must be non-empty strings." % name)
        return list(value)


# ---------------------------------------------------------------- query string
def pagination():
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise invalid(
                "Query parameter 'limit' must be between %d and %d."
                % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
            )
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            raise invalid("Query parameter 'offset' must be zero or greater.")
    return limit, offset


def paged(rows, serializer):
    """Apply the §2.3 page window to an already ordered row list."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset : offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)


def _query_int(name, raw_value):
    text = raw_value.strip()
    if text == "" or not re.match(r"^[+-]?\d+$", text):
        raise invalid("Query parameter '%s' must be an integer." % name)
    return int(text)


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("Query parameter '%s' must be a boolean." % name)


def query_string(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


# -------------------------------------------------------------------- lookups
def find(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def circuit(row_id):
    return find(db.circuits, row_id, "ERR_CIRCUIT_NOT_FOUND")


def weather_station(row_id):
    return find(db.weather_stations, row_id, "ERR_WEATHER_STATION_NOT_FOUND")


def fire_potential_index(row_id):
    return find(db.fire_potential_indices, row_id, "ERR_FIRE_POTENTIAL_INDEX_NOT_FOUND")


def psps_event(row_id):
    return find(db.psps_events, row_id, "ERR_PSPS_EVENT_NOT_FOUND")


def event_scope(row_id):
    return find(db.event_scopes, row_id, "ERR_EVENT_SCOPE_NOT_FOUND")


def customer(row_id):
    return find(db.customers, row_id, "ERR_CUSTOMER_NOT_FOUND")


def notification_batch(row_id):
    return find(db.notification_batches, row_id, "ERR_NOTIFICATION_BATCH_NOT_FOUND")


def notification_record(row_id):
    return find(db.notification_records, row_id, "ERR_NOTIFICATION_RECORD_NOT_FOUND")


def mitigation_project(row_id):
    return find(db.mitigation_projects, row_id, "ERR_MITIGATION_PROJECT_NOT_FOUND")


def patrol_assignment(row_id):
    return find(db.patrol_assignments, row_id, "ERR_PATROL_ASSIGNMENT_NOT_FOUND")


def resource_center(row_id):
    return find(db.resource_centers, row_id, "ERR_RESOURCE_CENTER_NOT_FOUND")


def plan_filing(row_id):
    return find(db.plan_filings, row_id, "ERR_PLAN_FILING_NOT_FOUND")


def unique_code(collection, field, value):
    for row in collection.values():
        if row.get(field) == value:
            raise ApiError("ERR_DUPLICATE_CODE", "%s '%s' is already taken." % (field, value))
