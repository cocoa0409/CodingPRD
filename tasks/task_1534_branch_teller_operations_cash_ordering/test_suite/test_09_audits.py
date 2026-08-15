"""Audit sessions: surprise freeze, scheduled begin, overlap, clock rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, make_branch, make_teller, open_drawer,
)

MGR = TEST_USERS["manager_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_surprise_audit_freezes_branch_immediately(api):
    """PRD §3.9: "A `SURPRISE` audit skips all of this: it is created directly
    `IN_PROGRESS`, in the very instant of its creation." and "The branch's
    status becomes `AUDIT_FROZEN` — set at creation for a surprise audit".

    Design: Corner/state_machines/surprise_audit_freezes_branch_immediately
    """
    branch = make_branch(api)
    audit = validate_success(api.create_audit(branch["id"], {"type": "SURPRISE"}, AUD), 201)
    assert audit["status"] == "IN_PROGRESS"
    assert audit["freeze_applied"] is True
    frozen = validate_success(api.get_branch(branch["id"], AUD))
    assert frozen["status"] == "AUDIT_FROZEN"


def test_scheduled_audit_begin_on_wrong_date_rejected(api):
    """PRD §3.9: "a planned audit sits `PLANNED` until its date arrives;
    beginning it early or late is `ERR_AUDIT_NOT_DUE`, and only when the
    logical date equals `scheduled_date` does beginning move it to
    `IN_PROGRESS`."

    Design: Corner/state_machines/scheduled_audit_begin_on_wrong_date_rejected
    """
    branch = make_branch(api)
    audit = validate_success(api.create_audit(
        branch["id"], {"type": "SCHEDULED", "scheduled_date": "2026-08-07"}, AUD), 201)
    assert audit["status"] == "PLANNED"
    resp = api.begin_audit(audit["id"], AUD)
    validate_error(resp, "ERR_AUDIT_NOT_DUE", 409)


def test_scheduled_audit_weekend_date_rejected(api):
    """PRD §3.9: "its `scheduled_date` must be a Monday-through-Friday date
    strictly later than the current logical date, or creation fails with
    `ERR_INVALID_AUDIT_DATE`".

    Design: Corner/errors/scheduled_audit_weekend_date_rejected
    """
    branch = make_branch(api)
    resp = api.create_audit(branch["id"],
                            {"type": "SCHEDULED", "scheduled_date": "2026-08-08"}, AUD)
    validate_error(resp, "ERR_INVALID_AUDIT_DATE", 422)


def test_audit_overlap_rejected_while_in_progress(api):
    """PRD §3.9: "A branch hosts at most one audit in `PLANNED` or
    `IN_PROGRESS` at a time; a second creation attempt meets
    `ERR_AUDIT_IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/audit_session_lifecycle_overlap_exclusion
    """
    branch = make_branch(api)
    surprise = validate_success(api.create_audit(branch["id"], {"type": "SURPRISE"}, AUD), 201)
    assert surprise["status"] == "IN_PROGRESS"
    resp = api.create_audit(branch["id"],
                            {"type": "SCHEDULED", "scheduled_date": "2026-08-07"}, AUD)
    validate_error(resp, "ERR_AUDIT_IN_PROGRESS", 409)


def test_audit_slot_freed_after_completion(api):
    """PRD §3.9: "The freeze lifts — the branch returns to `OPEN` — and the
    audit becomes terminal `COMPLETED`." Only then may another audit be
    planned.

    Design: Difficulty/resource_temporal_overlap/audit_session_lifecycle_overlap_exclusion
    """
    branch = make_branch(api)
    surprise = validate_success(api.create_audit(branch["id"], {"type": "SURPRISE"}, AUD), 201)
    done = validate_success(api.complete_audit(surprise["id"], 50_000_000, [], AUD))
    assert done["status"] == "COMPLETED"
    assert done["discrepancy_total_cents"] == 0
    planned = validate_success(api.create_audit(
        branch["id"], {"type": "SCHEDULED", "scheduled_date": "2026-08-07"}, AUD), 201)
    assert planned["status"] == "PLANNED"
    assert planned["scheduled_date"] == "2026-08-07"


def test_clock_regression_rejected(api):
    """PRD §2.5: "The clock moves forward only: a call naming an instant
    earlier than the current logical time is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 422)."

    Design: Corner/errors/clock_regression_rejected
    """
    get_success_data(api.set_clock("2026-08-10T00:00:00Z", MGR))
    resp = api.set_clock("2026-08-09T23:59:59Z", MGR)
    validate_error(resp, "ERR_CLOCK_REGRESSION", 422)


def test_surprise_audit_blocks_drawer_opening(api):
    """PRD §3.9: "while the freeze stands, no cash may move: no postings, no
    buys or sells, no drawer openings, no cash-order placement or delivery,
    and no instrument execution all fail with `ERR_BRANCH_FROZEN`."

    Design: Corner/state_machines/surprise_audit_freezes_branch_immediately
    """
    branch = make_branch(api)
    teller = make_teller(api, branch)
    validate_success(api.create_audit(branch["id"], {"type": "SURPRISE"}, AUD), 201)
    resp = api.open_drawer(teller["id"], TEST_USERS["head_teller_headers"])
    validate_error(resp, "ERR_BRANCH_FROZEN", 409)
