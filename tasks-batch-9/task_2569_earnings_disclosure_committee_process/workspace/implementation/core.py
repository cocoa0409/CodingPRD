"""Core primitives: logical clock, in-memory store, errors, envelope, calendar."""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- errors

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_MEMBER_FUNCTION_MISMATCH": 403,
    "ERR_ROLE_ACTION_MISMATCH": 403,
    "ERR_CHARTER_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_SUBCERT_NOT_FOUND": 404,
    "ERR_OFFICER_CERT_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_TIE_OUT_ITEM_NOT_FOUND": 404,
    "ERR_MEASURE_NOT_FOUND": 404,
    "ERR_QA_ITEM_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_CORRECTION_NOT_FOUND": 404,
    "ERR_DEFICIENCY_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_MILESTONE_PAST_DEADLINE": 422,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_STALE_DOCUMENT_VERSION": 412,
    "ERR_ENTITY_TERMINAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_CERTIFICATION": 409,
    "ERR_DUPLICATE_SUBCERT": 409,
    "ERR_CHARTER_NOT_ADOPTED": 409,
    "ERR_MEMBER_CHARTER_MISMATCH": 409,
    "ERR_MEMBER_SEAT_INVALID": 409,
    "ERR_SOD_SELF_REVIEW": 409,
    "ERR_SOD_SELF_APPROVAL": 409,
    "ERR_SOD_OFFICER_SUBCERT": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_FUNCTION_COVERAGE_GAP": 409,
    "ERR_SAFE_HARBOR_MISSING": 409,
    "ERR_QA_ITEM_UNCLEARED": 409,
    "ERR_MEASURE_NOT_RECONCILED": 409,
    "ERR_MEASURE_PROMINENCE": 409,
    "ERR_TIE_OUT_NOT_PASSED": 409,
    "ERR_OPEN_MATERIAL_EVENT": 409,
    "ERR_EVENT_DETERMINATION_CONFLICT": 409,
    "ERR_DEFICIENCY_OPEN": 409,
    "ERR_MILESTONE_WINDOW_OVERLAP": 409,
    "ERR_MILESTONE_BUFFER_VIOLATION": 409,
    "ERR_MILESTONE_MISSING": 409,
    "ERR_MILESTONE_INCOMPLETE": 409,
    "ERR_SUCCESSOR_CHARTER_INVALID": 409,
    "ERR_FILING_DOCUMENT_INVALID": 409,
    "ERR_AMENDMENT_TARGET_INVALID": 409,
    "ERR_DEFICIENCY_ALREADY_MITIGATED": 409,
    "ERR_SUBCERT_DUE_OUT_OF_WINDOW": 409,
    "ERR_MEMBER_PREP_WINDOW_CAPACITY": 409,
    "ERR_CERT_SCOPE_EMPTY": 409,
    "ERR_CERT_COVERAGE_INSUFFICIENT": 409,
    "ERR_CERTIFICATIONS_INCOMPLETE": 409,
    "ERR_MILESTONE_SLACK_EXHAUSTED": 409,
    "ERR_NOT_FOUND": 404,
}

# Ladder priority of each error id (PRD 2.11). Used to order readiness blockers.
LADDER_PRIORITY = {
    "ERR_UNAUTHENTICATED": 1,
    "ERR_ROLE_NOT_PERMITTED": 2,
    "ERR_MEMBER_FUNCTION_MISMATCH": 4,
    "ERR_ROLE_ACTION_MISMATCH": 5,
    "ERR_INVALID_REQUEST": 8,
    "ERR_INVALID_PAGINATION": 9,
    "ERR_STALE_CYCLE_VERSION": 10,
    "ERR_STALE_DOCUMENT_VERSION": 11,
    "ERR_ENTITY_TERMINAL": 12,
    "ERR_INVALID_STATE": 13,
    "ERR_DUPLICATE_CERTIFICATION": 14,
    "ERR_DUPLICATE_SUBCERT": 14,
    "ERR_CHARTER_NOT_ADOPTED": 15,
    "ERR_MEMBER_CHARTER_MISMATCH": 16,
    "ERR_MEMBER_SEAT_INVALID": 17,
    "ERR_SOD_SELF_REVIEW": 18,
    "ERR_SOD_SELF_APPROVAL": 19,
    "ERR_SOD_OFFICER_SUBCERT": 20,
    "ERR_QUORUM_NOT_MET": 21,
    "ERR_FUNCTION_COVERAGE_GAP": 22,
    "ERR_SAFE_HARBOR_MISSING": 23,
    "ERR_QA_ITEM_UNCLEARED": 24,
    "ERR_MEASURE_NOT_RECONCILED": 25,
    "ERR_MEASURE_PROMINENCE": 26,
    "ERR_TIE_OUT_NOT_PASSED": 27,
    "ERR_OPEN_MATERIAL_EVENT": 28,
    "ERR_EVENT_DETERMINATION_CONFLICT": 29,
    "ERR_DEFICIENCY_OPEN": 30,
    "ERR_MILESTONE_WINDOW_OVERLAP": 31,
    "ERR_MILESTONE_BUFFER_VIOLATION": 32,
    "ERR_MILESTONE_MISSING": 33,
    "ERR_MILESTONE_INCOMPLETE": 34,
    "ERR_SUCCESSOR_CHARTER_INVALID": 35,
    "ERR_FILING_DOCUMENT_INVALID": 36,
    "ERR_AMENDMENT_TARGET_INVALID": 37,
    "ERR_DEFICIENCY_ALREADY_MITIGATED": 38,
    "ERR_MILESTONE_PAST_DEADLINE": 39,
    "ERR_SUBCERT_DUE_OUT_OF_WINDOW": 40,
    "ERR_MEMBER_PREP_WINDOW_CAPACITY": 41,
    "ERR_CERT_SCOPE_EMPTY": 42,
    "ERR_CERT_COVERAGE_INSUFFICIENT": 43,
    "ERR_CERTIFICATIONS_INCOMPLETE": 44,
    "ERR_MILESTONE_SLACK_EXHAUSTED": 45,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower()


def bad(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------- time

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def parse_instant(raw):
    """Parse an ISO-8601 UTC instant. Raises ValueError on malformed input."""
    if not isinstance(raw, str) or isinstance(raw, bool):
        raise ValueError("not a string")
    text = raw.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_instant(value):
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def parse_day(raw):
    if not isinstance(raw, str) or isinstance(raw, bool):
        raise ValueError("not a string")
    text = raw.strip()
    if len(text) != 10:
        raise ValueError("bad length")
    return date.fromisoformat(text)


class Clock:
    def __init__(self):
        self.current = parse_instant(CLOCK_DEFAULT_ISO)

    def now(self):
        return self.current

    def now_iso(self):
        return fmt_instant(self.current)

    def set(self, value):
        self.current = value


# ---------------------------------------------------------------- decimal helpers

def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not numeric")
    return Decimal(str(value))


def rhu(value, places=2):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def money(value, places=2):
    """Round half-up and expose as a JSON number."""
    return float(rhu(value, places))


def whole(value):
    """Round half-up to an integer."""
    return int(rhu(value, 0))


# ---------------------------------------------------------------- business calendar

HOLIDAYS_2026_2027 = frozenset(
    [
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 5, 25),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2027, 1, 1),
    ]
)


def is_business_day(day):
    return day.weekday() < 5 and day not in HOLIDAYS_2026_2027


def roll_forward(day):
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def add_business_days(day, count):
    result = day
    for _ in range(count):
        result += timedelta(days=1)
        while not is_business_day(result):
            result += timedelta(days=1)
    return result


def count_business_days_after_through(start_day, end_day):
    if end_day <= start_day:
        return 0
    total = 0
    cursor = start_day + timedelta(days=1)
    while cursor <= end_day:
        if is_business_day(cursor):
            total += 1
        cursor += timedelta(days=1)
    return total


def whole_days_truncated(later, earlier):
    """Whole days in [earlier, later], truncated toward zero (may be negative)."""
    seconds = (later - earlier).total_seconds()
    return int(seconds / 86400.0)


# ---------------------------------------------------------------- store

ENTITY_KINDS = (
    "charter",
    "member",
    "cycle",
    "milestone",
    "subcert",
    "officer_cert",
    "document",
    "tie_out_item",
    "measure",
    "qa_item",
    "event",
    "filing",
    "correction",
    "deficiency",
)

NOT_FOUND_FOR_KIND = {
    "charter": "ERR_CHARTER_NOT_FOUND",
    "member": "ERR_MEMBER_NOT_FOUND",
    "cycle": "ERR_CYCLE_NOT_FOUND",
    "milestone": "ERR_MILESTONE_NOT_FOUND",
    "subcert": "ERR_SUBCERT_NOT_FOUND",
    "officer_cert": "ERR_OFFICER_CERT_NOT_FOUND",
    "document": "ERR_DOCUMENT_NOT_FOUND",
    "tie_out_item": "ERR_TIE_OUT_ITEM_NOT_FOUND",
    "measure": "ERR_MEASURE_NOT_FOUND",
    "qa_item": "ERR_QA_ITEM_NOT_FOUND",
    "event": "ERR_EVENT_NOT_FOUND",
    "filing": "ERR_FILING_NOT_FOUND",
    "correction": "ERR_CORRECTION_NOT_FOUND",
    "deficiency": "ERR_DEFICIENCY_NOT_FOUND",
}


class Store:
    """Pure in-memory store. Starts completely empty on every boot."""

    def __init__(self):
        self.tables = {kind: {} for kind in ENTITY_KINDS}
        self.clock = Clock()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def table(self, kind):
        return self.tables[kind]

    def get(self, kind, row_id):
        if not isinstance(row_id, str):
            return None
        return self.tables[kind].get(row_id)

    def must_get(self, kind, row_id):
        row = self.get(kind, row_id)
        if row is None:
            bad(NOT_FOUND_FOR_KIND[kind])
        return row

    def all_rows(self, kind):
        return list(self.tables[kind].values())

    def where(self, kind, **filters):
        out = []
        for row in self.tables[kind].values():
            if all(row.get(key) == value for key, value in filters.items()):
                out.append(row)
        return out

    def insert(self, kind, row):
        row["_kind"] = kind
        row["_seq"] = self.next_seq()
        self.tables[kind][row["id"]] = row
        return row

    def new_row(self, kind, fields):
        stamp = self.clock.now_iso()
        row = {"id": str(uuid.uuid4())}
        row.update(fields)
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row["version"] = 1
        return self.insert(kind, row)


store = Store()


# ---------------------------------------------------------------- mutation bookkeeping

class TouchLog:
    """Per-request dedup so a row's version rises by exactly 1 per request."""

    def __init__(self):
        self.seen = set()

    def touch(self, row):
        key = (row.get("_kind"), row["id"])
        row["updated_at"] = store.clock.now_iso()
        if key not in self.seen:
            self.seen.add(key)
            row["version"] = row.get("version", 1) + 1
        return row


# ---------------------------------------------------------------- envelope

REQUEST_ID_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(REQUEST_ID_ALPHABET) for _ in range(20))


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": store.clock.now_iso(),
    }


def success_object(data, status=200):
    return {"meta": base_meta(), "response_type": "object", "data": data}, status


def success_array(items, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, status


def error_envelope(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------- serialization

def public(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


def public_list(rows):
    return [public(row) for row in rows]
