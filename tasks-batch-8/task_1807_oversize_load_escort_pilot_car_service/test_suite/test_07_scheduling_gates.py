"""Scheduling gates: curfew windows, permit coverage, completeness, quotas."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    set_clock,
    create_tx_job,
    list_job_legs,
    list_leg_assignments,
    quote_job,
    accept_quote,
    get_job,
    get_leg,
    get_assignment,
    add_permit,
    issue_permit,
    request_survey,
    submit_survey,
    decide_survey,
    offer_assignment,
    accept_assignment,
    check_in,
    open_delay,
    close_delay,
    generate_invoice,
    make_escort_operator_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _booked_zero_position_cleared(carrier, *, window_start, window_end, permit_number):
    """Zero-position TX job (width 150 / height 150) carried to CLEARED with an
    issued permit covering 2026-08-09..2026-08-12."""
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(
        carrier,
        load_description=permit_number,
        width_inches=150,
        window_start_at=window_start,
        window_end_at=window_end,
        planned_entry_at=window_start,
        planned_exit_at=window_end,
    )
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    permit = add_permit(leg["id"], permit_number=permit_number)
    issue_permit(permit["id"])
    assert get_job(job["id"])["job_status"] == "CLEARED"
    return job, leg


def test_curfew_boundary_touching_entries_and_exits_allowed(api):
    """PRD §3.5: "Because both intervals are half-open, a `planned_entry_at`
    exactly at a curfew's end, or a `planned_exit_at` exactly at a curfew's
    start, is permitted."
    PRD §3.5: "The curfew windows, in UTC, are: Texas 07:00 to 09:00 and 16:00
    to 18:30; Oklahoma 07:00 to 09:00 and 16:30 to 18:30; Kansas 06:30 to
    08:30 and 16:00 to 18:00; Louisiana 06:30 to 09:00 and 15:30 to 18:00."

    Design: Difficulty/resource_temporal_overlap/curfew_half_open_boundaries
    """
    carrier = register_carrier(1_000_000, "Curfew Test Co")
    # Entry exactly at the TX morning curfew END (09:00) is permitted.
    job_d, _ = _booked_zero_position_cleared(
        carrier, window_start="2026-08-10T09:00:00Z", window_end="2026-08-10T13:00:00Z",
        permit_number="TX-P-12",
    )
    scheduled_d = validate_success(api.schedule_job(job_d["id"], DISPATCHER))
    assert scheduled_d["job_status"] == "SCHEDULED"

    # Exit exactly at the TX evening curfew START (16:00) is permitted.
    job_f, _ = _booked_zero_position_cleared(
        carrier, window_start="2026-08-10T13:00:00Z", window_end="2026-08-10T16:00:00Z",
        permit_number="TX-P-14",
    )
    scheduled_f = validate_success(api.schedule_job(job_f["id"], DISPATCHER))
    assert scheduled_f["job_status"] == "SCHEDULED"


def test_curfew_straddling_window_rejected(api):
    """PRD §3.5: "each leg's traversal interval, treated as half-open from
    `planned_entry_at` up to but not including `planned_exit_at`, must not
    intersect any of its state's daily curfew windows on any traversed UTC
    date; an intersection rejects the schedule with
    `ERR_CURFEW_WINDOW_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/curfew_half_open_boundaries
    """
    carrier = register_carrier(1_000_000, "Curfew Test Co")
    job_e, _ = _booked_zero_position_cleared(
        carrier, window_start="2026-08-10T08:30:00Z", window_end="2026-08-10T09:30:00Z",
        permit_number="TX-P-13",
    )
    resp = api.schedule_job(job_e["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CURFEW_WINDOW_VIOLATION)
    assert get_job(job_e["id"])["job_status"] == "CLEARED"


def test_permit_window_gap_at_schedule(api):
    """PRD §3.5: "First, permit coverage: for every leg, some `ISSUED` permit
    must fully cover the planned traversal — `valid_from` no later than the
    leg's `planned_entry_at` and `valid_until` no earlier than its
    `planned_exit_at` — and no entry of that permit's `holiday_closure_dates`
    may fall on any UTC calendar date the traversal touches; any leg failing
    coverage rejects the schedule with `ERR_PERMIT_WINDOW_INSUFFICIENT`."

    Design: Corner/validations/permit_window_gap_at_schedule
    """
    carrier = register_carrier(10_000_000, "Gap Co")
    esc = register_escort(("TX",), "Rider Gap")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Gap")
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    # Permit starts AFTER the planned 09:00 entry: existence gate passes...
    permit = add_permit(
        leg["id"], permit_number="TX-P-40",
        valid_from="2026-08-10T10:00:00Z", valid_until="2026-08-12T00:00:00Z",
    )
    issue_permit(permit["id"])
    assert get_job(job["id"])["job_status"] == "CLEARED", (
        "the CLEARED gate checks permit existence; coverage is deferred to schedule"
    )
    asg = offer_assignment(leg["id"], "REAR", esc["id"])
    accept_assignment(asg, esc["id"])

    resp = api.schedule_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_INSUFFICIENT)


def test_holiday_closure_embargo_at_schedule(api):
    """PRD §3.5: "no entry of that permit's `holiday_closure_dates` may fall on
    any UTC calendar date the traversal touches; any leg failing coverage
    rejects the schedule with `ERR_PERMIT_WINDOW_INSUFFICIENT`."

    Design: Corner/validations/holiday_closure_embargo_at_schedule
    """
    carrier = register_carrier(10_000_000, "Holiday Co")
    esc = register_escort(("TX",), "Rider H")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="H")
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    permit = add_permit(
        leg["id"], permit_number="TX-P-41", holiday_closure_dates=["2026-08-10"]
    )
    issue_permit(permit["id"])
    asg = offer_assignment(leg["id"], "REAR", esc["id"])
    accept_assignment(asg, esc["id"])

    resp = api.schedule_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_INSUFFICIENT)


def test_assignments_incomplete_at_schedule(api):
    """PRD §3.5: "Third, completeness: every required escort position on every
    leg must be covered by an `ACCEPTED` assignment, else the schedule is
    rejected with `ERR_ASSIGNMENTS_INCOMPLETE`."

    Design: Corner/validations/assignments_incomplete_at_schedule
    """
    carrier = register_carrier(10_000_000, "Incomplete Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="INC")
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    permit = add_permit(leg["id"], permit_number="TX-P-49")
    issue_permit(permit["id"])
    assert get_job(job["id"])["job_status"] == "CLEARED"

    resp = api.schedule_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENTS_INCOMPLETE)
    assert get_job(job["id"])["job_status"] == "CLEARED"


def test_schedule_temporal_beats_referential(api):
    """PRD §2.11: "Every mutating request passes through a single ordered
    validation pipeline, and the first failing check produces the response —
    later checks are not evaluated once an earlier one has failed."
    PRD §2.11: "10. Temporal business rules in endpoint order: permit window
    coverage (`ERR_PERMIT_WINDOW_INSUFFICIENT`, HTTP 409) ... 11. Referential
    uniqueness and quota rules (HTTP 409): ... `ERR_ASSIGNMENTS_INCOMPLETE`."

    Design: Corner/validations/schedule_temporal_beats_referential
    """
    carrier = register_carrier(10_000_000, "Priority Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="PR")
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    permit = add_permit(
        leg["id"], permit_number="TX-P-43",
        valid_from="2026-08-10T10:00:00Z", valid_until="2026-08-12T00:00:00Z",
    )
    issue_permit(permit["id"])

    # Both a permit window gap AND missing assignments; the temporal rule fires.
    resp = api.schedule_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_INSUFFICIENT)


def test_uniqueness_guards_open_records(api):
    """PRD §3.4: "a leg may have at most one non-terminal survey (one in
    `REQUESTED` or `SUBMITTED`) at a time; a second request while one is open
    is rejected with `ERR_OPEN_SURVEY_EXISTS`."
    PRD §3.5: "if the number of non-terminal assignments — those in `OFFERED`,
    `ACCEPTED`, or `ACTIVE` — already covering that position on the leg has
    reached the required count (`required_front_escorts` for `FRONT`,
    `required_rear_escorts` for `REAR`), the offer is rejected with
    `ERR_POSITION_QUOTA_FILLED`."
    PRD §3.7: "a job may have at most one `OPEN` delay event at a time; a
    second open attempt is rejected with `ERR_OPEN_DELAY_EVENT_EXISTS`."
    PRD §3.8: "the job must not already have a non-terminal invoice, meaning
    one in `DRAFT`, `FINALIZED`, or `DISPUTED`, else the generation is rejected
    with `ERR_ACTIVE_INVOICE_EXISTS`"

    Design: Corner/validations/uniqueness_guards_open_records
    """
    carrier = register_carrier(10_000_000, "Singleton Co")
    esc1 = register_escort(("TX",), "Rider U1")
    esc2 = register_escort(("TX",), "Rider U2")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="U", height_inches=170)
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)

    survey = request_survey(leg["id"])
    asg = offer_assignment(leg["id"], "REAR", esc1["id"])

    # One open survey per leg.
    resp = api.request_route_survey(leg["id"], TEST_USERS["route_surveyor_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_SURVEY_EXISTS)
    # Position quota: REAR quota 1 already covered by the OFFERED assignment.
    resp = api.create_assignment(leg["id"], {"position": "REAR", "escort_id": esc2["id"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_POSITION_QUOTA_FILLED)

    permit = add_permit(leg["id"], permit_number="TX-P-48")
    issue_permit(permit["id"])
    submit_survey(survey["id"], 180)
    decide_survey(survey["id"], leg["id"], "ACCEPTED")
    accept_assignment(asg, esc1["id"])
    validate_success(api.schedule_job(job["id"], DISPATCHER))
    set_clock("2026-08-10T09:00:00Z")
    validate_success(api.depart_job(job["id"], DISPATCHER))

    # One OPEN delay event per job.
    set_clock("2026-08-10T10:00:00Z")
    d1 = open_delay(job["id"], "WEATHER", "2026-08-10T10:00:00Z")
    resp = api.create_delay_event(
        job["id"], {"cause": "WEATHER", "started_at": "2026-08-10T10:00:00Z"}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_DELAY_EVENT_EXISTS)
    close_delay(d1["id"])
    check_in(asg["id"], esc1["id"])
    validate_success(api.deliver_job(job["id"], DISPATCHER))

    # One non-terminal invoice per job.
    inv = generate_invoice(job["id"], "bc-1")
    resp = api.create_invoice(job["id"], TEST_USERS["billing_clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_ACTIVE_INVOICE_EXISTS)
    rows, meta = validate_paginated(api.list_job_invoices(job["id"], DISPATCHER))
    assert meta["total_count"] == 1 and rows[0]["id"] == inv["id"]


def test_depart_requires_scheduled(api):
    """PRD §3.6: "A `Dispatcher` departs a `SCHEDULED` job — any other status
    is rejected with `ERR_JOB_INVALID_STATE`."

    Design: Corner/state_machines/depart_requires_scheduled
    """
    carrier = register_carrier(10_000_000, "Early Depart Co")
    job, leg = _booked_zero_position_cleared(
        carrier, window_start="2026-08-10T09:00:00Z", window_end="2026-08-10T13:00:00Z",
        permit_number="TX-P-20",
    )
    resp = api.depart_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)
    assert get_job(job["id"])["job_status"] == "CLEARED"
