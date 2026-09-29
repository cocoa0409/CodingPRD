"""Core primitives: in-memory store, logical clock, errors, response envelope."""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import g, jsonify

# ---------------------------------------------------------------------------
# Logical clock default (PRD 2.5)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class ApiError(Exception):
    """Carries the scaffold error_id plus its catalogued HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


class Store(object):
    COLLECTIONS = (
        "parties",
        "sending_areas",
        "receiving_areas",
        "appraisal_schedules",
        "sending_parcels",
        "severance_applications",
        "conservation_easements",
        "certificates",
        "certificate_transfers",
        "market_transactions",
        "receiving_site_applications",
        "certificate_redemptions",
        "monitoring_inspections",
        "program_evaluations",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        # Store starts completely empty on every boot. No seeding, ever.
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Clock / id / timestamp helpers
# ---------------------------------------------------------------------------
def now():
    return db.clock


def set_clock(value):
    db.clock = value


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2)."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def add_days(value, days):
    return value + timedelta(days=days)


def day_of(value):
    return value.astimezone(timezone.utc).date()


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up, away from zero on an exact tie."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def q2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(value):
    """Serialize a Decimal as a JSON number."""
    if value is None:
        return None
    return float(dec(value))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
def new_record(fields, common=True):
    ts = now()
    rec = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Bump version once per request per entity and refresh updated_at (PRD 2.4/2.7)."""
    if rec is None:
        return
    marks = getattr(g, "_touched", None)
    if marks is None:
        marks = set()
        g._touched = marks
    key = id(rec)
    if key in marks:
        rec["updated_at"] = now()
        return
    marks.add(key)
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now()


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": fmt_dt(now())}


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, http_status, message=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), http_status
