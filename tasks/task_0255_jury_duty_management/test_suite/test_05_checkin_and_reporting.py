"""Check-in: the report-date lower bound, the same-day collision rule, and the
QUALIFIED_PENDING -> REPORTING first-check-in transition.

Translates difficulty-design `resource_temporal_overlap /
checkin_same_service_date_rejected` (queue A) and corner-design instances from
§1.9 section `validations` (queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    check_in_payload,
    TEST_USERS,
    setup_qualified_pending, set_clock, check_in, get_summons,
)

_CLERK = TEST_USERS["court_clerk_headers"]


# ─── Difficulty: duplicate service_date on one summons ─────────────────

def test_duplicate_service_date_rejected(api):
    """PRD §3.4: "And no existing check-in on the same summons may already share
    that `service_date`; a duplicate calendar date on one summons is rejected with
    `ERR_DUPLICATE_SERVICE_DATE` (HTTP 409), so no day is ever double-credited."

    Design: Difficulty/resource_temporal_overlap/checkin_same_service_date_rejected
    """
    set_clock("2026-07-16T08:00:00Z")
    s = setup_qualified_pending(term_overrides={"name": "TK", "report_date": "2026-07-01T00:00:00Z"})
    check_in(s["summons"]["id"], "2026-07-16T00:00:00Z", 8.0)
    resp = api.check_in(s["summons"]["id"], check_in_payload("2026-07-16T00:00:00Z", 4.0), _CLERK)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERVICE_DATE.value)


def test_duplicate_service_date_does_not_advance_service_days(api):
    """PRD §3.4: "the summons's `service_days` counter increments by one with every
    check-in."
    PRD §3.4: "a duplicate calendar date on one summons is rejected with
    `ERR_DUPLICATE_SERVICE_DATE` (HTTP 409), so no day is ever double-credited."

    Design: Difficulty/resource_temporal_overlap/checkin_same_service_date_rejected
    """
    set_clock("2026-07-16T08:00:00Z")
    s = setup_qualified_pending(term_overrides={"name": "TK2", "report_date": "2026-07-01T00:00:00Z"})
    check_in(s["summons"]["id"], "2026-07-16T00:00:00Z", 8.0)
    api.check_in(s["summons"]["id"], check_in_payload("2026-07-16T00:00:00Z", 4.0), _CLERK)
    assert get_summons(s["summons"]["id"])["service_days"] == 1, (
        "service_days must stay 1 after a rejected duplicate-date check-in"
    )


# ─── Corner: report-date lower bound ───────────────────────────────────

def test_checkin_before_report_date_rejected(api):
    """PRD §3.4: "The `service_date` must be on or after the term's `report_date` —
    this is a closed lower bound, so a check-in dated exactly on the report date is
    allowed and one dated even a day earlier is rejected with
    `ERR_BEFORE_REPORT_DATE` (HTTP 409)."

    Design: Corner/validations/checkin_before_report_date_rejected
    """
    set_clock("2026-07-02T08:00:00Z")
    s = setup_qualified_pending(term_overrides={"name": "V1", "report_date": "2026-07-01T00:00:00Z"})
    resp = api.check_in(s["summons"]["id"], check_in_payload("2026-06-30T00:00:00Z", 8.0), _CLERK)
    validate_error(resp, ApiErrorId.ERR_BEFORE_REPORT_DATE.value)
    assert get_summons(s["summons"]["id"])["status"] == "QUALIFIED_PENDING"


def test_checkin_on_report_date_succeeds_and_reports(api):
    """PRD §3.4: "a check-in dated exactly on the report date is allowed."
    PRD §3.4: "The first check-in advances the summons from `QUALIFIED_PENDING` to
    `REPORTING`."
    PRD §3.4: "When `on_floor_hours` is at or above the term's `full_day_hours`, the
    day is a `FULL` day; otherwise it is a `HALF` day."

    Design: Corner/validations/checkin_on_report_date_succeeds_boundary
    """
    set_clock("2026-07-01T08:00:00Z")
    s = setup_qualified_pending(term_overrides={"name": "V2", "report_date": "2026-07-01T00:00:00Z"})
    resp = api.check_in(s["summons"]["id"], check_in_payload("2026-07-01T00:00:00Z", 8.0), _CLERK)
    ci = validate_success(resp, 201)
    assert ci["day_kind"] == "FULL", f"8.0 >= 6.0 must be FULL, got {ci['day_kind']}"
    summons = get_summons(s["summons"]["id"])
    assert summons["status"] == "REPORTING"
    assert summons["service_days"] == 1
