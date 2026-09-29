"""Foundation: in-memory store, logical clock, response envelope, errors, money."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify

# ---------------------------------------------------------------- error catalog

ERROR_STATUS = {
    # auth
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_RESTAURANT_NOT_FOUND": 404,
    "ERR_GUEST_NOT_FOUND": 404,
    "ERR_TABLE_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_ADDON_NOT_FOUND": 404,
    "ERR_SERVICE_NOT_FOUND": 404,
    "ERR_TICKET_CLASS_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_RESERVATION_ADDON_NOT_FOUND": 404,
    "ERR_DIETARY_NOTE_NOT_FOUND": 404,
    "ERR_WAITLIST_ENTRY_NOT_FOUND": 404,
    "ERR_PAYMENT_TRANSACTION_NOT_FOUND": 404,
    "ERR_REFUND_EXCEPTION_NOT_FOUND": 404,
    "ERR_GOODWILL_CREDIT_NOT_FOUND": 404,
    # shape
    "ERR_VALIDATION": 400,
    "ERR_INVALID_PAGINATION": 400,
    # concurrency
    "ERR_STALE_TICKET_CLASS_VERSION": 412,
    "ERR_STALE_RESERVATION_VERSION": 412,
    "ERR_STALE_GOODWILL_CREDIT_VERSION": 412,
    # state
    "ERR_SERVICE_NOT_PUBLISHED": 409,
    "ERR_SERVICE_INVALID_STATE": 409,
    "ERR_TICKET_CLASS_NOT_SELLABLE": 409,
    "ERR_TICKET_CLASS_INVALID_STATE": 409,
    "ERR_RESERVATION_INVALID_STATE": 409,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_DEPOSIT_NOT_SETTLED": 409,
    "ERR_BALANCE_OUTSTANDING": 409,
    "ERR_TRANSFER_REQUIRES_FULL_PAYMENT": 409,
    "ERR_WAITLIST_ENTRY_INVALID_STATE": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_DIETARY_NOTE_INVALID_STATE": 409,
    "ERR_REFUND_EXCEPTION_ALREADY_DECIDED": 409,
    "ERR_REFUND_EXCEPTION_NOT_APPROVED": 409,
    "ERR_GOODWILL_CREDIT_INVALID_STATE": 409,
    "ERR_GOODWILL_CREDIT_EXHAUSTED": 409,
    "ERR_GOODWILL_CREDIT_EXPIRED": 409,
    "ERR_INSUFFICIENT_SEATS": 409,
    "ERR_TABLE_TURN_CONFLICT": 409,
    # business rules
    "ERR_DIETARY_ACK_REQUIRED": 422,
    "ERR_DIETARY_NOTE_PREP_REJECTED": 422,
    "ERR_DIETARY_AMEND_LIMIT": 422,
    "ERR_TABLE_RESTAURANT_MISMATCH": 422,
    "ERR_TABLE_PARTY_SIZE_MISMATCH": 422,
    "ERR_PACKAGE_RESTAURANT_MISMATCH": 422,
    "ERR_ADDON_RESTAURANT_MISMATCH": 422,
    "ERR_GOODWILL_TARGET_MISMATCH": 422,
    "ERR_NO_SHOW_TOO_EARLY": 422,
    "ERR_SEATING_TOO_EARLY": 422,
    "ERR_NAME_CHANGE_CUTOFF_PASSED": 422,
    "ERR_TRANSFER_CUTOFF_PASSED": 422,
    "ERR_ADDON_ORDER_CUTOFF_PASSED": 422,
    "ERR_RELEASE_WINDOW_NOT_OPEN": 422,
    "ERR_CANCEL_WINDOW_CLOSED": 422,
    "ERR_NAME_CHANGE_LIMIT_REACHED": 422,
    "ERR_RESALE_SUSPECTED": 422,
    "ERR_ONWARD_TRANSFER_FORBIDDEN": 422,
    "ERR_TRANSFER_LIMIT_REACHED": 422,
    "ERR_TRANSFER_TO_SELF": 422,
    "ERR_PARTY_SIZE_OUT_OF_BAND": 422,
    "ERR_GUEST_INDEX_OUT_OF_RANGE": 422,
    "ERR_ADDON_QTY_INVALID": 422,
    "ERR_SERVICE_CAPACITY_EXCEEDED": 422,
    "ERR_DUPLICATE_ACTIVE_RESERVATION": 422,
    "ERR_DUPLICATE_WAITLIST_ENTRY": 422,
    "ERR_OFFER_ROUNDS_EXHAUSTED": 422,
    "ERR_KITCHEN_PREP_OVERSUBSCRIBED": 422,
    # fiscal
    "ERR_PAYMENT_EXCEEDS_BALANCE": 402,
    "ERR_PAYMENT_BELOW_DEPOSIT": 402,
    "ERR_REFUND_REQUEST_EXCEEDS_PAID": 402,
    "ERR_APPROVED_EXCEEDS_REQUESTED": 402,
    "ERR_APPROVED_EXCEEDS_FORFEITED": 402,
    "ERR_GOODWILL_EXCEEDS_CAP": 402,
    "ERR_GOODWILL_REDEMPTION_EXCEEDS_REMAINING": 402,
    "ERR_GOODWILL_EXCEEDS_BALANCE_DUE": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower()


# ------------------------------------------------------------------ time / ids

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def wall_now():
    return datetime.now(timezone.utc)


def to_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 UTC timestamp. Raises ValueError when malformed."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("not a date")
    return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)


DOW_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


# ------------------------------------------------------------------- the store

TABLES = (
    "restaurants",
    "guests",
    "tables",
    "packages",
    "add_ons",
    "services",
    "ticket_classes",
    "reservations",
    "reservation_add_ons",
    "dietary_notes",
    "waitlist_entries",
    "payment_transactions",
    "refund_exceptions",
    "goodwill_credits",
)

DB = {name: {} for name in TABLES}
STATE = {"seq": 0, "clock": parse_iso(CLOCK_DEFAULT)}

NOT_FOUND = {
    "restaurants": "ERR_RESTAURANT_NOT_FOUND",
    "guests": "ERR_GUEST_NOT_FOUND",
    "tables": "ERR_TABLE_NOT_FOUND",
    "packages": "ERR_PACKAGE_NOT_FOUND",
    "add_ons": "ERR_ADDON_NOT_FOUND",
    "services": "ERR_SERVICE_NOT_FOUND",
    "ticket_classes": "ERR_TICKET_CLASS_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "reservation_add_ons": "ERR_RESERVATION_ADDON_NOT_FOUND",
    "dietary_notes": "ERR_DIETARY_NOTE_NOT_FOUND",
    "waitlist_entries": "ERR_WAITLIST_ENTRY_NOT_FOUND",
    "payment_transactions": "ERR_PAYMENT_TRANSACTION_NOT_FOUND",
    "refund_exceptions": "ERR_REFUND_EXCEPTION_NOT_FOUND",
    "goodwill_credits": "ERR_GOODWILL_CREDIT_NOT_FOUND",
}


def clock():
    return STATE["clock"]


def set_clock(dt):
    STATE["clock"] = dt


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def new_record(table, fields, versioned=True):
    """Create and store a record. Never called at import time."""
    stamp = to_iso(wall_now())
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = stamp
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = next_seq()
    DB[table][rec["id"]] = rec
    return rec


def get(table, rec_id):
    if not isinstance(rec_id, str):
        return None
    return DB[table].get(rec_id)


def must_get(table, rec_id):
    rec = get(table, rec_id)
    if rec is None:
        raise ApiError(NOT_FOUND[table])
    return rec


def rows(table):
    return sorted(DB[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --------------------------------------------------------- mutation bookkeeping


class Watch:
    """Tracks pre-existing records touched by a request; bumps version once."""

    def __init__(self):
        self.items = []

    @staticmethod
    def _snap(rec):
        return {k: v for k, v in rec.items()
                if not k.startswith("_") and k not in ("updated_at", "version")}

    def add(self, *recs):
        for rec in recs:
            if rec is None:
                continue
            for held, _snap in self.items:
                if held is rec:
                    break
            else:
                self.items.append((rec, self._snap(rec)))
        return recs[0] if recs else None

    def commit(self):
        stamp = to_iso(wall_now())
        for rec, snap in self.items:
            if self._snap(rec) != snap:
                rec["version"] = rec.get("version", 1) + 1
                rec["updated_at"] = stamp
        self.items = []


# ---------------------------------------------------------------------- money


def rhu(numerator, denominator):
    """round_half_up(numerator / denominator) -> int"""
    return int((Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def bp_of(amount, basis_points):
    return rhu(int(amount) * int(basis_points), 10000)


def floor_div(numerator, denominator):
    return int(Decimal(int(numerator)) // Decimal(int(denominator)))


# ------------------------------------------------------------------- envelope


def _meta():
    return {"api_request_id": request_id(),
            "api_request_timestamp": to_iso(wall_now())}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status
