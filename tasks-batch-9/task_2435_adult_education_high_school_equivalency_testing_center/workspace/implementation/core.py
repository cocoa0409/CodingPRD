"""In-memory store, logical clock, envelope helpers, auth and validators."""

import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import g, jsonify, request

from errors import ApiError

ROLES = (
    "StateAuthority",
    "ProgramCoordinator",
    "Registrar",
    "Instructor",
    "CenterAdministrator",
    "Proctor",
    "Student",
)

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTION_NAMES = (
    "students",
    "centers",
    "rooms",
    "proctors",
    "sections",
    "enrollments",
    "attendance",
    "test_events",
    "sessions",
    "registrations",
    "accommodations",
    "outcomes",
    "credentials",
    "transcripts",
    "periods",
)


class Store(object):
    """Everything lives in plain dicts; nothing is persisted or preloaded."""

    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTION_NAMES:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0


store = Store()


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------

def clock():
    return store.clock


def set_clock(dt):
    store.clock = dt


# --------------------------------------------------------------------------
# time formatting / parsing
# --------------------------------------------------------------------------

def now_wall():
    return datetime.now(timezone.utc)


def fmt_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Clock-derived stamps: drop the fractional part when it is exactly zero."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt_ms(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def date_at_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def whole_days_between(earlier, later):
    return int((later - earlier).total_seconds() // 86400)


# --------------------------------------------------------------------------
# money / hours
# --------------------------------------------------------------------------

CENT = Decimal("1")
HUNDREDTH = Decimal("0.01")


def round_half_up(value):
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def floor_pct(amount_cents, pct):
    return (int(amount_cents) * int(pct)) // 100


def q2(value):
    return Decimal(value).quantize(HUNDREDTH, rounding=ROUND_HALF_UP)


def hours_out(value):
    return float(q2(value))


# --------------------------------------------------------------------------
# record lifecycle
# --------------------------------------------------------------------------

def _touched():
    marks = getattr(g, "touched_ids", None)
    if marks is None:
        marks = set()
        g.touched_ids = marks
    return marks


def next_seq():
    store.seq += 1
    return store.seq


def new_record(collection, fields):
    stamp = fmt_ms(now_wall())
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = stamp
    rec["updated_at"] = stamp
    rec["version"] = 1
    rec["_seq"] = next_seq()
    collection[rec["id"]] = rec
    _touched().add(rec["id"])
    return rec


def touch(rec):
    """Refresh updated_at and bump version at most once per record per request."""
    marks = _touched()
    if rec["id"] in marks:
        return
    marks.add(rec["id"])
    rec["version"] += 1
    rec["updated_at"] = fmt_ms(now_wall())


def pub(rec):
    return dict((k, v) for k, v in rec.items() if not k.startswith("_"))


def by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# envelope
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_ms(now_wall()),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------

def auth(*roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return role, user_id


def deny_scope():
    raise ApiError("ERR_FORBIDDEN_SCOPE")


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(records, limit, offset, serializer=pub):
    total = len(records)
    window = records[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# body / field validation (all failures are ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------

def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return parsed


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def req_str(data, key, max_len=None, allow_empty=False):
    value = data.get(key)
    if not isinstance(value, str):
        bad()
    if not allow_empty and not value.strip():
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    return value


def opt_str(data, key, default=None, max_len=None, allow_empty=False):
    if key not in data or data.get(key) is None:
        return default
    return req_str(data, key, max_len=max_len, allow_empty=allow_empty)


def req_enum(data, key, choices):
    value = data.get(key)
    if not isinstance(value, str) or value not in choices:
        bad()
    return value


def opt_enum(data, key, choices, default=None):
    if key not in data or data.get(key) is None:
        return default
    return req_enum(data, key, choices)


def _as_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        bad()
    return value


def req_int(data, key, minimum=None, maximum=None):
    value = _as_int(data.get(key))
    if minimum is not None and value < minimum:
        bad()
    if maximum is not None and value > maximum:
        bad()
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data.get(key) is None:
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_dec(data, key, minimum=None, maximum=None, exclusive_min=None,
            places=2, multiple_of=None):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad()
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad()
    if dec != dec.quantize(HUNDREDTH):
        # more precision than the two decimal places the field carries
        bad()
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        bad()
    if minimum is not None and dec < Decimal(str(minimum)):
        bad()
    if maximum is not None and dec > Decimal(str(maximum)):
        bad()
    if multiple_of is not None:
        step = Decimal(str(multiple_of))
        if (dec % step) != 0:
            bad()
    return dec


def opt_dec(data, key, default=None, **kwargs):
    if key not in data or data.get(key) is None:
        return default
    return req_dec(data, key, **kwargs)


def req_bool(data, key):
    value = data.get(key)
    if not isinstance(value, bool):
        bad()
    return value


def opt_bool(data, key, default=False):
    if key not in data or data.get(key) is None:
        return default
    return req_bool(data, key)


def req_dt(data, key):
    value = data.get(key)
    parsed = parse_dt(value)
    if parsed is None:
        bad()
    return value, parsed


def opt_dt(data, key):
    if key not in data or data.get(key) is None:
        return None, None
    return req_dt(data, key)


def req_date(data, key):
    value = data.get(key)
    parsed = parse_date(value)
    if parsed is None:
        bad()
    return value, parsed


def req_str_array(data, key, choices, default=None):
    if key not in data or data.get(key) is None:
        return list(default) if default is not None else None
    value = data.get(key)
    if not isinstance(value, list):
        bad()
    out = []
    for item in value:
        if not isinstance(item, str) or item not in choices:
            bad()
        if item not in out:
            out.append(item)
    return out


def req_fk(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        bad()
    return value


def opt_fk(data, key):
    if key not in data or data.get(key) is None:
        return None
    return req_fk(data, key)


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def find(collection, record_id, error_id):
    if not isinstance(record_id, str) or record_id not in collection:
        raise ApiError(error_id)
    return collection[record_id]


def find_student(student_id):
    return find(store.students, student_id, "ERR_STUDENT_NOT_FOUND")


def find_center(center_id):
    return find(store.centers, center_id, "ERR_TESTING_CENTER_NOT_FOUND")


def find_room(room_id):
    return find(store.rooms, room_id, "ERR_TESTING_ROOM_NOT_FOUND")


def find_proctor(proctor_id):
    return find(store.proctors, proctor_id, "ERR_PROCTOR_NOT_FOUND")


def find_section(section_id):
    return find(store.sections, section_id, "ERR_CLASS_SECTION_NOT_FOUND")


def find_enrollment(enrollment_id):
    return find(store.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


def find_entry(entry_id):
    return find(store.attendance, entry_id, "ERR_ATTENDANCE_ENTRY_NOT_FOUND")


def find_test_event(event_id):
    return find(store.test_events, event_id, "ERR_TEST_EVENT_NOT_FOUND")


def find_session(session_id):
    return find(store.sessions, session_id, "ERR_EXAM_SESSION_NOT_FOUND")


def find_registration(registration_id):
    return find(store.registrations, registration_id, "ERR_EXAM_REGISTRATION_NOT_FOUND")


def find_accommodation(request_id):
    return find(store.accommodations, request_id, "ERR_ACCOMMODATION_REQUEST_NOT_FOUND")


def find_outcome(outcome_id):
    return find(store.outcomes, outcome_id, "ERR_OUTCOME_RECORD_NOT_FOUND")


def find_credential(credential_id):
    return find(store.credentials, credential_id, "ERR_CREDENTIAL_NOT_FOUND")


def find_transcript(order_id):
    return find(store.transcripts, order_id, "ERR_TRANSCRIPT_ORDER_NOT_FOUND")


def find_period(period_id):
    return find(store.periods, period_id, "ERR_FUNDING_PERIOD_NOT_FOUND")


def session_center_id(session):
    room = store.rooms.get(session.get("testing_room_id"))
    return room.get("testing_center_id") if room else None


def session_center(session):
    center_id = session_center_id(session)
    return store.centers.get(center_id) if center_id else None


# --------------------------------------------------------------------------
# lazy state evaluation
# --------------------------------------------------------------------------

def effective_proctor_status(proctor):
    if proctor["certification_status"] == "CERTIFIED":
        expires = proctor.get("_certification_expires_at")
        if expires is not None and clock() >= expires:
            return "LAPSED"
    return proctor["certification_status"]


def proctor_pub(proctor):
    data = pub(proctor)
    data["certification_status"] = effective_proctor_status(proctor)
    return data


def guard_proctor_certified(proctor, persist=False):
    status = effective_proctor_status(proctor)
    if status == "LAPSED":
        if persist and proctor["certification_status"] == "CERTIFIED":
            proctor["certification_status"] = "LAPSED"
            touch(proctor)
        raise ApiError("ERR_PROCTOR_CERTIFICATION_LAPSED")
    if status != "CERTIFIED":
        raise ApiError("ERR_PROCTOR_NOT_CERTIFIED")


def effective_accommodation_status(accommodation):
    if accommodation["status"] == "APPROVED":
        valid_until = accommodation.get("_valid_until")
        if valid_until is not None and clock() >= valid_until:
            return "EXPIRED"
    return accommodation["status"]


def accommodation_pub(accommodation):
    data = pub(accommodation)
    data["status"] = effective_accommodation_status(accommodation)
    return data


# --------------------------------------------------------------------------
# shared aggregate maintenance
# --------------------------------------------------------------------------

def recount_section_seats(section):
    section["seats_available"] = section["seats_total"] - section["seats_taken"]


def decrement_active_enrollment(student):
    if student["active_enrollment_count"] > 0:
        student["active_enrollment_count"] -= 1
    if student["active_enrollment_count"] == 0 and student["intake_status"] == "ENROLLED":
        student["intake_status"] = "PLACED"
    touch(student)


def student_enrollments(student_id):
    return [e for e in store.enrollments.values() if e["student_id"] == student_id]


def recompute_student_hours(student):
    total = Decimal("0")
    for enrollment in student_enrollments(student["id"]):
        total += enrollment["_posted_hours"]
    student["_total_instructional_hours"] = q2(total)
    student["total_instructional_hours"] = hours_out(total)
