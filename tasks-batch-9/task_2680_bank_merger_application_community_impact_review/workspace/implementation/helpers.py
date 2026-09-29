"""Shared route helpers: record lookup, ownership, pagination, period windows."""
import calc
from db import db, fmt_dt, now_dt, parse_dt, serialize, set_fields, sorted_records
from errors import ApiError
from middleware import actor_id, actor_role, pagination, paginate, present
from response import list_response

NOT_FOUND_ERROR = {
    "institutions": "ERR_INSTITUTION_NOT_FOUND",
    "markets": "ERR_MARKET_NOT_FOUND",
    "branches": "ERR_BRANCH_NOT_FOUND",
    "applications": "ERR_APPLICATION_NOT_FOUND",
    "schedules": "ERR_SCHEDULE_NOT_FOUND",
    "analyses": "ERR_ANALYSIS_NOT_FOUND",
    "periods": "ERR_COMMENT_PERIOD_NOT_FOUND",
    "comments": "ERR_COMMENT_NOT_FOUND",
    "hearings": "ERR_HEARING_REQUEST_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "line_items": "ERR_LINE_ITEM_NOT_FOUND",
    "decisions": "ERR_DECISION_NOT_FOUND",
    "conditions": "ERR_CONDITION_NOT_FOUND",
    "conversion_plans": "ERR_CONVERSION_PLAN_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
}


def fetch(collection_name, record_id):
    record = getattr(db, collection_name).get(record_id)
    if record is None:
        raise ApiError(
            NOT_FOUND_ERROR[collection_name],
            "no such record: %s" % record_id,
        )
    return record


def fetch_fk(collection_name, record_id):
    """A body-carried foreign key resolves to the same not-found family."""
    if not isinstance(record_id, str) or not record_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", "a valid identifier is required")
    return fetch(collection_name, record_id)


def list_and_respond(collection_name, filter_fields=()):
    from flask import request

    limit, offset = pagination()
    filters = {}
    for field in filter_fields:
        value = request.args.get(field)
        if value is not None and value != "":
            filters[field] = value

    def matches(record):
        for field, value in filters.items():
            if str(record.get(field)) != value:
                return False
        return True

    items = sorted_records(getattr(db, collection_name), matches)
    page = paginate(items, limit, offset)
    return list_response([serialize(r) for r in page], limit, offset, len(items))


# --------------------------------------------------------------------------
# ownership
# --------------------------------------------------------------------------
def ensure_application_filer(application):
    """PRD 2.1 — a Filer may act only on its own application."""
    if actor_role() == "Filer" and actor_id() != application["acquirer_id"]:
        raise ApiError(
            "ERR_NOT_APPLICATION_FILER",
            "the acting principal is not this application's acquirer",
        )


def check_application_version(application, expected):
    if int(expected) != int(application["version"]):
        raise ApiError(
            "ERR_STALE_APPLICATION_VERSION",
            "expected_application_version does not match the application's current version",
        )


def require_usd(body, field, minimum=0, required=True, default=0):
    """A USD amount is a non-negative integer (PRD 2.5 step 4)."""
    if not present(body, field):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required" % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if value < 0:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a non-negative integer" % field)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return value


# --------------------------------------------------------------------------
# comment period windows (PRD 2.10)
# --------------------------------------------------------------------------
def period_opens_dt(period):
    return parse_dt(period["opens_at"])


def period_closes_dt(period):
    return parse_dt(period["closes_at"])


def compute_closes_at(period):
    opens = period_opens_dt(period)
    total_days = int(period["duration_days"]) + int(period["extended_days_total"])
    return fmt_dt(opens + _days(total_days))


def _days(count):
    from datetime import timedelta

    return timedelta(days=int(count))


def window_contains(period, instant):
    """Half-open interval: opens_at inclusive, closes_at exclusive."""
    return period_opens_dt(period) <= instant < period_closes_dt(period)


def windows_overlap(a_opens, a_closes, b_opens, b_closes):
    return a_opens < b_closes and b_opens < a_closes


def set_earliest_decision_at(application, closes_dt):
    set_fields(
        application,
        earliest_decision_at=fmt_dt(closes_dt + _days(calc.POST_COMMENT_REVIEW_DAYS)),
    )


# --------------------------------------------------------------------------
# the community-review axis (PRD 3.2 / 3.7 / 3.8)
# --------------------------------------------------------------------------
def move_review_axis(application, from_states, to_state):
    if application["public_review_status"] in from_states:
        set_fields(application, public_review_status=to_state)
        return True
    return False


def all_periods_closed(application_id):
    from aggregates import application_periods

    periods = application_periods(application_id)
    return all(p["status"] == "CLOSED" for p in periods)


def buffered_closure_window(branch):
    """Closed interval buffered 15 days on both sides (PRD 2.10)."""
    notice = parse_dt(branch.get("notice_sent_at"))
    closure = parse_dt(branch.get("planned_closure_date"))
    if notice is None or closure is None:
        return None
    return (
        notice - _days(calc.CONVERSION_BUFFER_DAYS),
        closure + _days(calc.CONVERSION_BUFFER_DAYS),
    )


def closed_intervals_conflict(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def conversion_conflicts_with_branch(branch, conv_start, conv_end):
    window = buffered_closure_window(branch)
    if window is None:
        return False
    return closed_intervals_conflict(window[0], window[1], conv_start, conv_end)


def now():
    return now_dt()
