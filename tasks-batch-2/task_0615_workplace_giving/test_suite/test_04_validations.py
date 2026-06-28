"""Validation and precedence: state-vs-business precedence, schedule-overlap-vs-ceiling order,
cross-entity guards (campaign launch / donation settle), temporal overlap geometry (half-open
schedules, closed batch periods), and window / cross-entity validations (PRD 2.10, 3.3-3.8).
"""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    get_success_data,
    setup_giving_scenario,
    create_active_program,
    create_approved_charity,
    create_employee,
    create_live_campaign,
    create_authorized_donation,
    create_settled_donation,
    create_logged_volunteer_log,
    create_active_schedule,
    create_open_batch,
    stage_grant,
    lock_batch,
    set_clock,
    create_charity_payload,
    create_campaign_payload,
    create_payroll_schedule_payload,
    create_disbursement_batch_payload,
)

PM = TEST_USERS["program_manager_headers"]
GA = TEST_USERS["giving_admin_headers"]


# ===========================================================================
# Difficulty / priority_pair_validation_conflict
# ===========================================================================
def test_state_beats_charity_not_approved_on_batch_settle(api):
    """PRD 2.10: "seventh, the state-precondition check for the requested transition
    (`ERR_INVALID_STATE`). Business-rule checks specific to an operation — charity approval
    status, campaign and schedule windows, eligibility, fiscal ceilings, and the like — are
    evaluated after these foundational checks, in the relative order described alongside each
    workflow in §3."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_charity_not_approved_on_batch_settle
    """
    # OPEN (not LOCKED) batch whose charity is SUSPENDED: state check (not LOCKED) fires first.
    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(
        s["program"]["id"], s["charity"]["id"],
        period_start="2026-01-01T00:00:00Z", period_end="2026-06-30T00:00:00Z",
    )
    stage_grant(batch["id"], "DONATION", don["id"], batch["version"])
    api.suspend_charity(s["charity"]["id"], GA)

    resp = api.settle_disbursement_batch(batch["id"], GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_disbursement_batch(batch["id"], GA))
    assert after["status"] == "OPEN"


def test_state_check_precedes_business_check_batch_unchanged(api):
    """PRD 2.10: "seventh, the state-precondition check for the requested transition
    (`ERR_INVALID_STATE`). Business-rule checks specific to an operation — charity approval
    status, campaign and schedule windows, eligibility, fiscal ceilings, and the like — are
    evaluated after these foundational checks."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_charity_not_approved_on_batch_settle
    """
    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(
        s["program"]["id"], s["charity"]["id"],
        period_start="2026-01-01T00:00:00Z", period_end="2026-06-30T00:00:00Z",
    )
    stage_grant(batch["id"], "DONATION", don["id"], batch["version"])
    api.suspend_charity(s["charity"]["id"], GA)

    # Even though charity is not APPROVED, the OPEN-not-LOCKED state error must be reported.
    resp = api.settle_disbursement_batch(batch["id"], GA)
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"


def test_schedule_overlap_beats_deduction_limit(api):
    """PRD 3.5: "First, the new schedule's half-open active window from `window_start` up to
    `window_end` must not overlap the window of any existing schedule for the same employee and
    campaign that is in `ACTIVE` or `PAUSED` status; an overlapping window (evaluated with
    half-open semantics) is rejected with `ERR_SCHEDULE_OVERLAP`. Second, the payroll-deduction
    ceiling must hold ... exceeding it is rejected with `ERR_DEDUCTION_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_overlap_beats_deduction_limit
    """
    # salary 1,200,000 -> ceiling 20000; existing schedule 15000 over [Jan, Jul).
    # New schedule 9000 over [Mar, Sep) BOTH overlaps AND would exceed ceiling (15000+9000>20000).
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 1200000},
        campaign_overrides={"goal_cents": 1000000},
    )
    create_active_schedule(
        s, per_period_amount_cents=15000,
        window_start="2026-01-01T00:00:00Z", window_end="2026-07-01T00:00:00Z",
    )
    payload = create_payroll_schedule_payload(
        s["program"]["id"], s["employee"]["id"], s["campaign"]["id"],
        per_period_amount_cents=9000,
        window_start="2026-03-01T00:00:00Z", window_end="2026-09-01T00:00:00Z",
    )
    resp = api.create_payroll_schedule(payload, GA)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP.value)


def test_schedule_overlap_reported_before_ceiling(api):
    """PRD 3.5: "First, the new schedule's half-open active window ... must not overlap ... is
    rejected with `ERR_SCHEDULE_OVERLAP`. Second, the payroll-deduction ceiling must hold ...
    exceeding it is rejected with `ERR_DEDUCTION_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_overlap_beats_deduction_limit
    """
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 1200000},
        campaign_overrides={"goal_cents": 1000000},
    )
    create_active_schedule(
        s, per_period_amount_cents=15000,
        window_start="2026-01-01T00:00:00Z", window_end="2026-07-01T00:00:00Z",
    )
    payload = create_payroll_schedule_payload(
        s["program"]["id"], s["employee"]["id"], s["campaign"]["id"],
        per_period_amount_cents=9000,
        window_start="2026-03-01T00:00:00Z", window_end="2026-09-01T00:00:00Z",
    )
    resp = api.create_payroll_schedule(payload, GA)
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_SCHEDULE_OVERLAP", (
        "overlap (first) must be reported before the deduction ceiling (second)"
    )


# ===========================================================================
# Difficulty / cross_entity_state_dependency
# ===========================================================================
def test_campaign_launch_requires_charity_approved(api):
    """PRD 3.4: "Launching a campaign moves it from `DRAFT` to `LIVE`, but only when three
    conditions hold: the campaign is in `DRAFT` (else `ERR_INVALID_STATE`), the referenced charity
    is `APPROVED` (else `ERR_CHARITY_NOT_APPROVED`), and the owning program is `ACTIVE` (else
    `ERR_PROGRAM_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/campaign_launch_requires_charity_approved
    """
    prog = create_active_program()
    charity = get_success_data(
        api.create_charity(create_charity_payload(prog["id"], legal_name="X1", ein="15-1515151"), GA)
    )
    api.start_review_charity(charity["id"], GA)  # left UNDER_REVIEW, not approved
    camp = get_success_data(
        api.create_campaign(create_campaign_payload(prog["id"], charity["id"], name="X1C", goal_cents=100000), PM)
    )
    resp = api.launch_campaign(camp["id"], PM)
    validate_error(resp, ApiErrorId.ERR_CHARITY_NOT_APPROVED.value)

    after = validate_success(api.get_campaign(camp["id"], PM))
    assert after["status"] == "DRAFT"


def test_donation_settle_requires_campaign_live(api):
    """PRD 3.5: "Settling an authorized donation is an administrative action permitted only when
    the donation is `AUTHORIZED` (else `ERR_INVALID_STATE`) and its campaign is `LIVE` (else
    `ERR_CAMPAIGN_NOT_LIVE`)."

    Design: Difficulty/cross_entity_state_dependency/donation_settle_requires_campaign_live
    """
    s = setup_giving_scenario()
    don = create_authorized_donation(s, base_amount_cents=5000)
    api.pause_campaign(s["campaign"]["id"], PM)  # campaign LIVE -> PAUSED

    resp = api.settle_donation(don["id"], GA)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_LIVE.value)

    after = validate_success(api.get_donation(don["id"], GA))
    assert after["status"] == "AUTHORIZED"


def test_campaign_launch_with_approved_charity_succeeds(api):
    """PRD 3.4: "Launching a campaign moves it from `DRAFT` to `LIVE`, but only when three
    conditions hold: the campaign is in `DRAFT` (else `ERR_INVALID_STATE`), the referenced charity
    is `APPROVED` (else `ERR_CHARITY_NOT_APPROVED`), and the owning program is `ACTIVE` (else
    `ERR_PROGRAM_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/campaign_launch_requires_charity_approved
    """
    # The complementary positive: once the charity is APPROVED, the same launch succeeds -> LIVE.
    prog = create_active_program()
    charity = create_approved_charity(prog["id"], legal_name="X1ok", ein="15-1515152")
    camp = get_success_data(
        api.create_campaign(create_campaign_payload(prog["id"], charity["id"], name="X1OK", goal_cents=100000), PM)
    )
    launched = validate_success(api.launch_campaign(camp["id"], PM))
    assert launched["status"] == "LIVE"


def test_donation_settle_with_live_campaign_succeeds(api):
    """PRD 3.5: "Settling an authorized donation is an administrative action permitted only when
    the donation is `AUTHORIZED` (else `ERR_INVALID_STATE`) and its campaign is `LIVE` (else
    `ERR_CAMPAIGN_NOT_LIVE`)."

    Design: Difficulty/cross_entity_state_dependency/donation_settle_requires_campaign_live
    """
    # The complementary positive: while the campaign is LIVE, the settle succeeds -> SETTLED.
    s = setup_giving_scenario()
    don = create_authorized_donation(s, base_amount_cents=5000)
    settled = validate_success(api.settle_donation(don["id"], GA))
    assert settled["status"] == "SETTLED"


# ===========================================================================
# Difficulty / resource_temporal_overlap
# ===========================================================================
def test_schedule_half_open_overlap_rejected(api):
    """PRD 3.5: "the new schedule's half-open active window from `window_start` up to `window_end`
    must not overlap the window of any existing schedule for the same employee and campaign that
    is in `ACTIVE` or `PAUSED` status; an overlapping window (evaluated with half-open semantics)
    is rejected with `ERR_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/schedule_half_open_overlap_per_employee_campaign
    """
    # Existing [Jan, Apr); new [Mar, Aug) shares [Mar, Apr) -> overlap. Huge salary so no ceiling.
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 120000000},
        campaign_overrides={"goal_cents": 1000000},
    )
    create_active_schedule(
        s, per_period_amount_cents=1000,
        window_start="2026-01-01T00:00:00Z", window_end="2026-04-01T00:00:00Z",
    )
    payload = create_payroll_schedule_payload(
        s["program"]["id"], s["employee"]["id"], s["campaign"]["id"],
        per_period_amount_cents=1000,
        window_start="2026-03-01T00:00:00Z", window_end="2026-08-01T00:00:00Z",
    )
    resp = api.create_payroll_schedule(payload, GA)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP.value)


def test_schedule_half_open_adjacent_touch_allowed(api):
    """PRD 3.5: "the new schedule's half-open active window from `window_start` up to `window_end`
    must not overlap the window of any existing schedule for the same employee and campaign that
    is in `ACTIVE` or `PAUSED` status; an overlapping window (evaluated with half-open semantics)
    is rejected with `ERR_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/schedule_half_open_overlap_per_employee_campaign
    """
    # Existing [Jan, Apr); adjacent [Apr, Jul) touches only at 2026-04-01 -> half-open, allowed.
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 120000000},
        campaign_overrides={"goal_cents": 1000000},
    )
    create_active_schedule(
        s, per_period_amount_cents=1000,
        window_start="2026-01-01T00:00:00Z", window_end="2026-04-01T00:00:00Z",
    )
    payload = create_payroll_schedule_payload(
        s["program"]["id"], s["employee"]["id"], s["campaign"]["id"],
        per_period_amount_cents=1000,
        window_start="2026-04-01T00:00:00Z", window_end="2026-07-01T00:00:00Z",
    )
    resp = api.create_payroll_schedule(payload, GA)
    validate_success(resp, expected_status=201)


def test_batch_closed_interval_touching_endpoints_conflict(api):
    """PRD 3.8: "a new batch's period from `period_start` through `period_end` must not overlap
    any existing batch for the same charity that is in `OPEN`, `LOCKED`, or `SETTLED` status, and
    because the interval is closed, even touching endpoints count as a conflict; an overlap is
    rejected with `ERR_BATCH_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/batch_closed_interval_touching_endpoints_conflict
    """
    prog = create_active_program()
    charity = create_approved_charity(prog["id"], legal_name="Ov2", ein="18-1818181")
    create_open_batch(prog["id"], charity["id"], period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z")

    payload = create_disbursement_batch_payload(
        prog["id"], charity["id"],
        period_start="2026-01-31T00:00:00Z", period_end="2026-02-28T00:00:00Z",
    )
    resp = api.create_disbursement_batch(payload, GA)
    validate_error(resp, ApiErrorId.ERR_BATCH_PERIOD_OVERLAP.value)


def test_batch_non_touching_period_allowed(api):
    """PRD 3.8: "a new batch's period from `period_start` through `period_end` must not overlap
    any existing batch for the same charity that is in `OPEN`, `LOCKED`, or `SETTLED` status, and
    because the interval is closed, even touching endpoints count as a conflict; an overlap is
    rejected with `ERR_BATCH_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/batch_closed_interval_touching_endpoints_conflict
    """
    # A strictly-later, non-touching period [Feb-01, Feb-28] after [Jan-01, Jan-31] is allowed.
    prog = create_active_program()
    charity = create_approved_charity(prog["id"], legal_name="Ov3", ein="18-1818182")
    create_open_batch(prog["id"], charity["id"], period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z")

    payload = create_disbursement_batch_payload(
        prog["id"], charity["id"],
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
    )
    resp = api.create_disbursement_batch(payload, GA)
    validate_success(resp, expected_status=201)


# ===========================================================================
# Corner / validations
# ===========================================================================
def test_donation_pledge_outside_campaign_window_rejected(api):
    """PRD 3.5: "At pledge time the target campaign must be `LIVE`, and the logical clock must
    fall within the campaign's half-open window from `window_start` up to `window_end`; a clock
    outside that window is rejected with `ERR_CAMPAIGN_WINDOW_CLOSED`."

    Design: Corner/validations/donation_pledge_outside_campaign_window_rejected
    """
    from test_helpers import create_donation_payload

    s = setup_giving_scenario()  # campaign window [2026-01-01, 2027-01-01)
    set_clock("2027-06-01T00:00:00Z")  # past window_end
    payload = create_donation_payload(
        s["program"]["id"], s["employee"]["id"], s["campaign"]["id"], base_amount_cents=5000
    )
    resp = api.create_donation(payload, GA)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CLOSED.value)


def test_runcycle_outside_schedule_window_rejected(api):
    """PRD 3.5: "Running a cycle on a schedule ... requires the schedule to be `ACTIVE` (else
    `ERR_INVALID_STATE`), the logical clock to fall within the schedule's half-open window from
    `window_start` up to `window_end` (else `ERR_SCHEDULE_WINDOW_CLOSED`), and the funded
    campaign to be `LIVE` (else `ERR_CAMPAIGN_NOT_LIVE`)."

    Design: Corner/validations/runcycle_outside_schedule_window_rejected
    """
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 120000000},
        campaign_overrides={"goal_cents": 1000000},
    )
    sched = create_active_schedule(
        s, per_period_amount_cents=1000,
        window_start="2026-01-01T00:00:00Z", window_end="2026-04-01T00:00:00Z",
    )
    set_clock("2026-09-01T00:00:00Z")  # past schedule window_end
    resp = api.run_cycle_payroll_schedule(sched["id"], GA)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_CLOSED.value)


def test_grant_source_not_disbursable_rejected(api):
    """PRD 3.8: "the source must be in a disbursable state — a donation `SETTLED`, a matching gift
    `FINALIZED`, or a volunteer log `APPROVED` — failing with `ERR_SOURCE_NOT_DISBURSABLE`."

    Design: Corner/validations/grant_source_not_disbursable_rejected
    """
    from test_helpers import stage_grant_payload

    s = setup_giving_scenario()
    don = create_authorized_donation(s, base_amount_cents=5000)  # AUTHORIZED, not SETTLED
    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])

    resp = api.stage_grant(
        batch["id"], stage_grant_payload("DONATION", don["id"], batch["version"]), GA
    )
    validate_error(resp, ApiErrorId.ERR_SOURCE_NOT_DISBURSABLE.value)


def test_grant_charity_mismatch_rejected(api):
    """PRD 3.8: "the source's beneficiary charity must match the batch's charity, failing with
    `ERR_GRANT_CHARITY_MISMATCH`."

    Design: Corner/validations/grant_charity_mismatch_rejected
    """
    from test_helpers import stage_grant_payload

    prog = create_active_program()
    ch_a = create_approved_charity(prog["id"], legal_name="A", ein="49-4949494")
    ch_b = create_approved_charity(prog["id"], legal_name="B", ein="50-5050505")
    emp = create_employee(prog["id"], email="mm@co.com", full_name="Mm")
    camp_a = create_live_campaign(prog["id"], ch_a["id"], name="CA", goal_cents=100000)

    s_a = {"program": prog, "charity": ch_a, "employee": emp, "campaign": camp_a}
    don = create_settled_donation(s_a, base_amount_cents=5000)

    batch_b = create_open_batch(prog["id"], ch_b["id"])
    resp = api.stage_grant(
        batch_b["id"], stage_grant_payload("DONATION", don["id"], batch_b["version"]), GA
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_CHARITY_MISMATCH.value)


def test_source_already_granted_rejected(api):
    """PRD 3.8: "the source must not already be staged or settled in another grant, failing with
    `ERR_SOURCE_ALREADY_GRANTED`."

    Design: Corner/validations/source_already_granted_rejected
    """
    from test_helpers import stage_grant_payload

    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])
    grant = stage_grant(batch["id"], "DONATION", don["id"], batch["version"])

    refreshed = validate_success(api.get_disbursement_batch(batch["id"], GA))
    resp = api.stage_grant(
        batch["id"], stage_grant_payload("DONATION", don["id"], refreshed["version"]), GA
    )
    validate_error(resp, ApiErrorId.ERR_SOURCE_ALREADY_GRANTED.value)


def test_volunteer_minutes_zero_rejected(api):
    """PRD 2.10: "fifth, request-body well-formedness — required fields present, enum values
    valid, amounts and minutes strictly greater than zero, EIN in the format of two digits, a
    hyphen, then seven digits (`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/volunteer_minutes_zero_rejected
    """
    from test_helpers import create_volunteer_log_payload

    s = setup_giving_scenario()
    payload = create_volunteer_log_payload(
        s["program"]["id"], s["employee"]["id"], s["charity"]["id"],
        minutes=0, activity_date="2026-02-10T00:00:00Z",
    )
    resp = api.create_volunteer_log(payload, GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_volunteer_approve_requires_charity_approved(api):
    """PRD 3.7: "Approving a volunteer log is an administrative action permitted only when the log
    is `LOGGED` (else `ERR_INVALID_STATE`), the referenced charity is `APPROVED` (else
    `ERR_CHARITY_NOT_APPROVED`), and the volunteer employee is `ACTIVE` (else
    `ERR_EMPLOYEE_NOT_ACTIVE`)."

    Design: Corner/validations/volunteer_approve_requires_charity_approved
    """
    s = setup_giving_scenario()
    log = create_logged_volunteer_log(s, minutes=120, activity_date="2026-02-10T00:00:00Z")
    api.suspend_charity(s["charity"]["id"], GA)

    resp = api.approve_volunteer_log(log["id"], GA)
    validate_error(resp, ApiErrorId.ERR_CHARITY_NOT_APPROVED.value)


def test_campaign_launch_requires_program_active(api):
    """PRD 3.4: "Launching a campaign moves it from `DRAFT` to `LIVE`, but only when three
    conditions hold: the campaign is in `DRAFT` (else `ERR_INVALID_STATE`), the referenced charity
    is `APPROVED` (else `ERR_CHARITY_NOT_APPROVED`), and the owning program is `ACTIVE` (else
    `ERR_PROGRAM_NOT_ACTIVE`)."

    Design: Corner/validations/campaign_launch_requires_program_active
    """
    prog = get_success_data(
        api.create_program({"name": "P", "tax_year": 2026}, PM)
    )  # left DRAFT, never activated
    charity = create_approved_charity(prog["id"], legal_name="C", ein="54-5454545")
    camp = get_success_data(
        api.create_campaign(create_campaign_payload(prog["id"], charity["id"], name="C", goal_cents=100000), PM)
    )
    resp = api.launch_campaign(camp["id"], PM)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)
