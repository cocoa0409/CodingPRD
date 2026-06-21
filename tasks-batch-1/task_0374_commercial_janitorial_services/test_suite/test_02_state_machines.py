"""State-machine transitions: invalid transitions, idempotency, preconditions,
terminal lockdown, and side effects.

Translates SCAFFOLD_CORNER_DESIGN.yaml §1.9 `state_machines` non-stub instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, ApiErrorId,
    schedule_callback_payload, fixtures,
)
from test_helpers.test_users import TEST_USERS
from test_helpers.api_client import api_client

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
CC = TEST_USERS["client_contact_headers"]


def test_cancel_visit_from_completed_returns_invalid_state(api):
    """PRD §3.3: "Each of these three transitions out of `SCHEDULED` requires the
    visit to actually be in `SCHEDULED` status; otherwise the transition is
    refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_visit_from_completed_returns_invalid_state
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_completed_routine_visit(site["id"], crew["id"])
    resp = api.cancel_visit(visit["id"], FS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_visit(visit["id"], FS), 200)
    assert after["status"] == "COMPLETED"


def test_pause_schedule_idempotent_second_pause_returns_invalid_state(api):
    """PRD §3.2: "A paused schedule can be resumed back to `ACTIVE`, but only when
    it is currently `PAUSED`". PRD §3.2: "A `FieldSupervisor` can pause an `ACTIVE`
    schedule, transitioning its `status` to `PAUSED`".

    Design: Corner/state_machines/pause_schedule_idempotent_second_pause_returns_invalid_state
    """
    _, site, crew = fixtures.setup_account_site_crew()
    sched = validate_success(api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 600,
         "window_end_min": 660, "assigned_crew_id": crew["id"]}, FS), 201)
    validate_success(api.pause_schedule(sched["id"], FS), 200)
    resp = api.pause_schedule(sched["id"], FS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_schedule(sched["id"], FS), 200)
    assert after["status"] == "PAUSED"


def test_terminate_contract_with_open_period_returns_period_open(api):
    """PRD §3.9: "Terminating an `ACTIVE` contract advances it `ACTIVE →
    TERMINATED`, but only when no billing period of the contract is in `OPEN` or
    `REOPENED` status; a still-open period blocks termination with `ERR_PERIOD_OPEN`."

    Design: Corner/state_machines/terminate_contract_with_open_period_returns_period_open
    """
    bundle = fixtures.setup_billing_scenario(crew=False)
    resp = api.terminate_contract(bundle["contract"]["id"], AM)
    validate_error(resp, ApiErrorId.ERR_PERIOD_OPEN.value)
    after = validate_success(api.get_contract(bundle["contract"]["id"], AM), 200)
    assert after["status"] == "ACTIVE"


def test_complete_visit_with_open_time_entry_returns_open_time_entry(api):
    """PRD §3.5: "Completion is gated by two clock conditions: at least one time
    entry for the visit must already be `COMPLETED` (otherwise `ERR_NO_TIME_ENTRY`),
    and no time entry for the visit may still be `OPEN` (otherwise `ERR_OPEN_TIME_ENTRY`)."

    Design: Corner/state_machines/complete_visit_with_open_time_entry_returns_open_time_entry
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_started_visit(site["id"], crew["id"])
    # one OPEN time entry, never clocked out
    validate_success(api.create_time_entry(
        {"visit_id": visit["id"], "crew_id": crew["id"], "clock_in_min": 540}, FS), 201)
    resp = api.complete_visit(visit["id"], FS)
    # With one OPEN and zero COMPLETED entries, both completion gates fail;
    # PRD §3.5 lists them ("at least one COMPLETED, otherwise ERR_NO_TIME_ENTRY,
    # and no OPEN, otherwise ERR_OPEN_TIME_ENTRY") without pinning precedence, so
    # either error_id is a faithful reading.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_OPEN_TIME_ENTRY.value, ApiErrorId.ERR_NO_TIME_ENTRY.value],
    )
    after = validate_success(api.get_visit(visit["id"], FS), 200)
    assert after["status"] == "IN_PROGRESS"


def test_complete_visit_with_no_completed_time_entry_returns_no_time_entry(api):
    """PRD §3.5: "Completion is gated by two clock conditions: at least one time
    entry for the visit must already be `COMPLETED` (otherwise `ERR_NO_TIME_ENTRY`),
    and no time entry for the visit may still be `OPEN` (otherwise `ERR_OPEN_TIME_ENTRY`)."

    Design: Corner/state_machines/complete_visit_with_no_completed_time_entry_returns_no_time_entry
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_started_visit(site["id"], crew["id"])
    te = validate_success(api.create_time_entry(
        {"visit_id": visit["id"], "crew_id": crew["id"], "clock_in_min": 540}, FS), 201)
    validate_success(api.void_time_entry(te["id"], FS), 200)
    resp = api.complete_visit(visit["id"], FS)
    validate_error(resp, ApiErrorId.ERR_NO_TIME_ENTRY.value)
    after = validate_success(api.get_visit(visit["id"], FS), 200)
    assert after["status"] == "IN_PROGRESS"


def test_resolve_complaint_callback_not_complete_returns_callback_not_complete(api):
    """PRD §3.7: "Resolving a complaint advances it `CALLBACK_SCHEDULED →
    RESOLVED`, but only once the callback visit named by `callback_visit_id` is
    itself `COMPLETED`; resolving while the callback visit is not yet complete is
    refused with `ERR_CALLBACK_NOT_COMPLETE`."

    Design: Corner/state_machines/resolve_complaint_callback_not_complete_returns_callback_not_complete
    """
    bundle = fixtures.setup_billing_scenario()
    complaint, _cb = fixtures.setup_callback_scheduled_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MAJOR")
    resp = api.resolve_complaint(complaint["id"], FS)
    validate_error(resp, ApiErrorId.ERR_CALLBACK_NOT_COMPLETE.value)
    after = validate_success(api.get_complaint(complaint["id"], FS), 200)
    assert after["status"] == "CALLBACK_SCHEDULED"
    assert after["credit_applied_cents"] == 0


def test_reopen_minor_complaint_returns_reopen_not_allowed(api):
    """PRD §3.7: "reopening is restricted to the site's `ClientContact` and only
    for complaints whose `severity` is `MAJOR`; attempting to reopen a `MINOR`
    resolved complaint is refused with `ERR_REOPEN_NOT_ALLOWED`."

    Design: Corner/state_machines/reopen_minor_complaint_returns_reopen_not_allowed
    """
    bundle = fixtures.setup_billing_scenario()
    complaint = fixtures.setup_resolved_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MINOR")
    resp = api.reopen_complaint(complaint["id"], CC)
    validate_error(resp, ApiErrorId.ERR_REOPEN_NOT_ALLOWED.value)
    after = validate_success(api.get_complaint(complaint["id"], FS), 200)
    assert after["status"] == "RESOLVED"


def test_invoiced_period_terminal_lockdown_reopen_returns_invalid_state(api):
    """PRD §3.9: "a `CLOSED` period may be invoiced by an `AccountManager`,
    advancing it `CLOSED → INVOICED`; this is terminal and freezes the figures.
    Each of these billing-period transitions requires the period to be in the
    precondition state named, or the request is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/invoiced_period_terminal_lockdown_reopen_returns_invalid_state
    """
    bundle = fixtures.setup_closed_period()
    validate_success(api.invoice_billing_period(bundle["period"]["id"], AM), 200)
    ver = fixtures.get_account_version(bundle["account"]["id"])
    resp = api.reopen_billing_period(bundle["period"]["id"], {"expected_account_version": ver}, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    assert after["status"] == "INVOICED"


def test_resume_schedule_window_conflict_rechecked_on_resume(api):
    """PRD §3.2: "A paused schedule can be resumed back to `ACTIVE`, but only when
    it is currently `PAUSED`; resuming re-checks that the schedule's
    `assigned_crew_id` crew is `AVAILABLE` (otherwise `ERR_CREW_INACTIVE`) and
    re-runs the same closed-interval window-conflict test against other `ACTIVE`
    schedules for that crew and weekday (otherwise `ERR_SCHEDULE_WINDOW_CONFLICT`)."

    Design: Corner/state_machines/resume_schedule_window_conflict_rechecked_on_resume
    """
    _, site, crew = fixtures.setup_account_site_crew()
    sched_a = validate_success(api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 600,
         "window_end_min": 660, "assigned_crew_id": crew["id"]}, FS), 201)
    validate_success(api.pause_schedule(sched_a["id"], FS), 200)
    validate_success(api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 620,
         "window_end_min": 680, "assigned_crew_id": crew["id"]}, FS), 201)
    resp = api.resume_schedule(sched_a["id"], FS)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_CONFLICT.value)
    after = validate_success(api.get_schedule(sched_a["id"], FS), 200)
    assert after["status"] == "PAUSED"


def test_resume_schedule_inactive_crew_returns_crew_inactive(api):
    """PRD §3.2: "resuming re-checks that the schedule's `assigned_crew_id` crew
    is `AVAILABLE` (otherwise `ERR_CREW_INACTIVE`)".

    Design: Corner/state_machines/resume_schedule_inactive_crew_returns_crew_inactive
    """
    _, site, crew = fixtures.setup_account_site_crew()
    sched = validate_success(api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 600,
         "window_end_min": 660, "assigned_crew_id": crew["id"]}, FS), 201)
    validate_success(api.pause_schedule(sched["id"], FS), 200)
    validate_success(api.deactivate_crew(crew["id"], FS), 200)
    resp = api.resume_schedule(sched["id"], FS)
    validate_error(resp, ApiErrorId.ERR_CREW_INACTIVE.value)
    after = validate_success(api.get_schedule(sched["id"], FS), 200)
    assert after["status"] == "PAUSED"


def test_start_visit_on_archived_site_returns_site_archived(api):
    """PRD §3.3: "starting requires that the visit's `crew_id` crew is `AVAILABLE`
    (otherwise `ERR_CREW_INACTIVE`) and that the site is `ACTIVE` (otherwise
    `ERR_SITE_ARCHIVED`)."

    Design: Corner/state_machines/start_visit_on_archived_site_returns_site_archived
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_visit(site["id"], crew["id"])
    validate_success(api.archive_site(site["id"], AM), 200)
    resp = api.start_visit(visit["id"], FS)
    validate_error(resp, ApiErrorId.ERR_SITE_ARCHIVED.value)
    after = validate_success(api.get_visit(visit["id"], FS), 200)
    assert after["status"] == "SCHEDULED"


def test_contract_activate_on_archived_site_returns_site_archived(api):
    """PRD §3.9: "activation requires the site to be `ACTIVE` (otherwise
    `ERR_SITE_ARCHIVED`) and the owning account to be `ACTIVE` (otherwise
    `ERR_ACCOUNT_NOT_ACTIVE`)."

    Design: Corner/state_machines/contract_activate_on_archived_site_returns_site_archived
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"])
    contract = fixtures.create_draft_contract(site["id"])
    validate_success(api.archive_site(site["id"], AM), 200)
    resp = api.activate_contract(contract["id"], AM)
    validate_error(resp, ApiErrorId.ERR_SITE_ARCHIVED.value)
    after = validate_success(api.get_contract(contract["id"], AM), 200)
    assert after["status"] == "DRAFT"


def test_miss_visit_side_effect_no_billing_capture(api):
    """PRD §3.3: "From `SCHEDULED`, a visit may instead be marked `MISSED` (no
    labor is captured and nothing settles into billing; a missed routine visit
    contributes no inspection and therefore does not affect any period's mean
    quality score)".

    Design: Corner/state_machines/miss_visit_side_effect_no_billing_capture
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_visit(site["id"], crew["id"])
    resp = api.miss_visit(visit["id"], FS)
    data = validate_success(resp, 200)
    assert data["status"] == "MISSED"
    assert data["billing_period_id"] is None


def test_acknowledge_complaint_bumps_open_complaint_count(api):
    """PRD §3.7: "Acknowledging an `OPEN` complaint advances it `OPEN →
    ACKNOWLEDGED` and recomputes the owning account's `open_complaint_count`."
    PRD §3.1: "the count of complaints across all of the account's sites whose
    `status` is any of `OPEN`, `ACKNOWLEDGED`, or `CALLBACK_SCHEDULED`."

    Design: Corner/state_machines/acknowledge_complaint_bumps_open_complaint_count
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"])
    complaint = fixtures.raise_complaint(site["id"], severity="MINOR")
    validate_success(api.acknowledge_complaint(complaint["id"], FS), 200)
    acct_after = validate_success(api.get_account(acct["id"], AM), 200)
    assert acct_after["open_complaint_count"] == 1


def test_complaint_resolve_clears_open_count_back_to_zero(api):
    """PRD §3.7: "The complaint's `status` becomes `RESOLVED`, and the owning
    account's `open_complaint_count` is recomputed." PRD §3.1: "the count of
    complaints across all of the account's sites whose `status` is any of `OPEN`,
    `ACKNOWLEDGED`, or `CALLBACK_SCHEDULED`."

    Design: Corner/state_machines/complaint_resolve_clears_open_count_back_to_zero
    """
    bundle = fixtures.setup_billing_scenario()
    fixtures.setup_resolved_complaint(bundle["site"]["id"], bundle["crew"]["id"], severity="MAJOR")
    acct_after = validate_success(api.get_account(bundle["account"]["id"], AM), 200)
    assert acct_after["open_complaint_count"] == 0
