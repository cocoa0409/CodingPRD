"""Follow-up outcome windows and per-milestone uniqueness."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    setup_active_enrollment, create_quit_attempt, set_clock, record_follow_up,
)
from test_helpers import factories as F

CM = TEST_USERS["case_manager_headers"]


def test_followup_before_window_returns_not_open(api):
    """PRD §3.7: "A milestone may not be recorded before its window opens: the
    current clock time must be at or after the relevant quit attempt's `quit_date`
    plus `day` days, else the request is rejected with `ERR_FOLLOWUP_WINDOW_NOT_OPEN`."

    Design: Corner/state_machines/followup_before_window_returns_not_open
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False, clock="2026-06-01T00:00:00Z")
    create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
    set_clock(api, "2026-06-03T00:00:00Z")  # before quit_date + 7 days (2026-06-09)
    resp = api.create_follow_up_outcome(
        ctx["enrollment_id"], F.create_follow_up_outcome_payload(day=7, abstinent=True), CM
    )
    validate_error(resp, ApiErrorId.ERR_FOLLOWUP_WINDOW_NOT_OPEN.value)


def test_duplicate_followup_same_day_rejected(api):
    """PRD §3.7: "At most one outcome may exist per enrollment per `day`; a repeat for
    the same milestone is rejected with `ERR_DUPLICATE_FOLLOWUP`."

    Design: Corner/state_machines/duplicate_followup_same_day_returns_error
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False, clock="2026-06-01T00:00:00Z")
    create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
    set_clock(api, "2026-06-09T00:00:00Z")
    record_follow_up(api, ctx["enrollment_id"], 7, True)
    resp = api.create_follow_up_outcome(
        ctx["enrollment_id"], F.create_follow_up_outcome_payload(day=7, abstinent=True), CM
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FOLLOWUP.value)
