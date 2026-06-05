"""Timesheet submit/approve/reject/resubmit, segregation of duties, OCC version
checks, frozen-week guards, punch-edit cascade into gross, and the validation
precedence pairs that bite on the approve/edit paths.

Covers Queue A non_linear_state_machine (timesheet cycle), transitive_cascade
(punch edit), cross_entity_state_dependency (punch edit frozen),
priority_pair_validation_conflict, and Queue B validations + cross_cutting OCC.
"""
from test_helpers import (
    validate_success, validate_error,
    assert_version_incremented,
    ApiErrorId,
    setup_ca_employer, setup_locked_week_in_run,
    create_employee as mk_employee,
    create_closed_punch, create_draft_week, submit_week, approve_week,
    create_payroll_run, include_week_payload,
    edit_punch_payload, approve_week_payload,
    make_employee_headers,
    ADMIN, SUP1, SUP2, SUP9,
)


# ─── Reject / resubmit cycle (Queue A non_linear_state_machine) ──

def test_timesheet_reject_resubmit_returns_to_submitted_with_version_growth(api):
    """PRD §3.8: "A rejected week loops back: resubmission (REJECTED → SUBMITTED)
    recomputes the wage fields, records a fresh submitted_by_user_id, and increments
    version again — the same open-punch guard applies."
    PRD §3.8: "Rejection ... advances the week SUBMITTED → REJECTED, clears
    submitted_by_user_id, and increments version."

    Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_cycle
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    rejected = validate_success(api.reject_timesheet_week(week["id"], SUP2), 200)
    assert rejected["status"] == "REJECTED"
    assert_version_incremented(rejected["version"], submitted["version"])
    resubmitted = submit_week(api, week["id"], SUP1)
    # The machine is cyclic: REJECTED -> SUBMITTED returns to a prior state.
    assert resubmitted["status"] == "SUBMITTED"
    assert_version_incremented(resubmitted["version"], rejected["version"])


def test_timesheet_reject_clears_submitter_then_resubmit_records_fresh(api):
    """PRD §3.8: "it advances the week SUBMITTED → REJECTED, clears
    submitted_by_user_id, and increments version."
    PRD §3.8: "resubmission (REJECTED → SUBMITTED) recomputes the wage fields,
    records a fresh submitted_by_user_id, and increments version again".

    Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_cycle
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submit_week(api, week["id"], SUP1)
    rejected = validate_success(api.reject_timesheet_week(week["id"], SUP2), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["submitted_by_user_id"] is None
    resubmitted = submit_week(api, week["id"], SUP1)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submitted_by_user_id"] == "sup-1"


# ─── Punch-edit cascade into gross (Queue A transitive_cascade) ──

def test_punch_edit_cascades_into_timesheet_gross(api):
    """PRD §3.3: "it applies the new value to the punch and recomputes
    worked_minutes, setting the punch's edited flag to true ... and, when a
    timesheet week in DRAFT, SUBMITTED, or REJECTED covers the punch's
    workday_date, it triggers a recompute of that week's derived wage fields".

    Design: Difficulty/transitive_cascade/punch_edit_cascades_to_timesheet_gross
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submit_week(api, week["id"], SUP1)
    # Extend the punch clock-out from 16:00 to 22:00 (8h -> 14h).
    validate_success(api.edit_punch(
        punch["id"], edit_punch_payload("CLOCK_OUT", "2026-06-01T22:00:00Z",
                                        reason="Forgot to clock out; corrected per badge log"),
        SUP9), 201)
    punch_after = validate_success(api.get_punch(punch["id"], SUP1), 200)
    assert punch_after["worked_minutes"] == 840
    assert punch_after["edited"] is True
    # The edit cascade recomputes the SUBMITTED week's derived wage fields in place
    # (PRD §3.3); GET the week to surface the recomputed gross.
    data = validate_success(api.get_timesheet_week(week["id"], SUP1), 200)
    assert data["ot_minutes"] == 240
    assert data["dt_minutes"] == 120
    assert data["gross_wages_cents"] == 36000


def test_punch_edit_shrinking_punch_cascades_gross_down(api):
    """PRD §3.3: "it applies the new value to the punch and recomputes
    worked_minutes ... and, when a timesheet week in DRAFT, SUBMITTED, or REJECTED
    covers the punch's workday_date, it triggers a recompute of that week's derived
    wage fields".

    The inverse cascade direction: editing an 8h punch's clock-out earlier to 6h
    propagates a lower regular_minutes / gross into the covering week.

    Design: Difficulty/transitive_cascade/punch_edit_cascades_to_timesheet_gross
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submit_week(api, week["id"], SUP1)
    validate_success(api.edit_punch(
        punch["id"], edit_punch_payload("CLOCK_OUT", "2026-06-01T14:00:00Z",
                                        reason="left early; corrected"), SUP9), 201)
    punch_after = validate_success(api.get_punch(punch["id"], SUP1), 200)
    assert punch_after["worked_minutes"] == 360
    # The edit cascade recomputes the SUBMITTED week's derived wage fields in place
    # (PRD §3.3); GET the week to surface the recomputed gross.
    data = validate_success(api.get_timesheet_week(week["id"], SUP1), 200)
    assert data["regular_minutes"] == 360
    # straight 2000 * 6 = 12000, no OT.
    assert data["gross_wages_cents"] == 12000


# ─── Void cascade reconciliation (Queue B cross_cutting) ──

def test_void_closed_punch_reconciles_gross_to_zero(api):
    """PRD §3.3: "Voiding a CLOSED punch ... sets the punch to VOIDED, forces its
    worked_minutes to zero, and cascades a recompute of the owning timesheet week's
    derived wage fields so the lost time drops out of the paycheck. Voided punches
    are excluded from every wage calculation."

    Design: Corner/cross_cutting_complexity_layers/void_punch_reconciles_timesheet_gross
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submit_week(api, week["id"], SUP1)
    voided = validate_success(api.void_punch(punch["id"], SUP9), 200)
    assert voided["status"] == "VOIDED"
    assert voided["worked_minutes"] == 0
    # The void cascade recomputes the SUBMITTED week's derived wage fields in place
    # (PRD §3.3); GET the week to surface the reconciled gross.
    data = validate_success(api.get_timesheet_week(week["id"], SUP1), 200)
    assert data["regular_minutes"] == 0
    assert data["gross_wages_cents"] == 0


# ─── Frozen-week guard on edit (Queue A cross_entity_state_dependency) ──

def test_punch_edit_blocked_when_week_approved(api):
    """PRD §3.3: "no edit is permitted while the punch's covering timesheet week is
    APPROVED or LOCKED; such an attempt is rejected with ERR_TIMESHEET_FROZEN."

    Design: Difficulty/cross_entity_state_dependency/punch_edit_blocked_by_timesheet_state
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    approve_week(api, week["id"], submitted["version"], SUP2)
    resp = api.edit_punch(punch["id"],
                          edit_punch_payload("CLOCK_OUT", "2026-06-01T17:00:00Z",
                                             reason="late correction"), SUP9)
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_FROZEN.value, 409)


def test_punch_edit_blocked_when_week_locked(api):
    """PRD §3.3: "no edit is permitted while the punch's covering timesheet week is
    APPROVED or LOCKED; such an attempt is rejected with ERR_TIMESHEET_FROZEN."

    The other freezing state: once the week is LOCKED into a payroll run, the punch
    edit is rejected just as it is when APPROVED.

    Design: Difficulty/cross_entity_state_dependency/punch_edit_blocked_by_timesheet_state
    """
    ctx = setup_locked_week_in_run(api)
    resp = api.edit_punch(ctx["punch"]["id"],
                          edit_punch_payload("CLOCK_OUT", "2026-06-01T17:00:00Z",
                                             reason="late correction"), SUP9)
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_FROZEN.value, 409)


# ─── Priority-pair: frozen state beats missing reason (Queue A) ──

def test_frozen_week_beats_missing_edit_reason(api):
    """PRD §2.8: "State legality comes after that — the target must be in a state
    that permits the requested transition (ERR_INVALID_STATE), including the
    frozen-timesheet guard (ERR_TIMESHEET_FROZEN) ... Only once these structural
    gates pass does the system evaluate the business-specific constraints — reason
    requirements, duration positivity, interval overlaps".

    Design: Difficulty/priority_pair_validation_conflict/frozen_state_beats_missing_reason
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    approve_week(api, week["id"], submitted["version"], SUP2)
    # Edit on a frozen (APPROVED) week WITH an empty reason: both checks fail; the
    # frozen-state guard (a structural gate) is reported, not the reason rule.
    resp = api.edit_punch(punch["id"],
                          edit_punch_payload("CLOCK_OUT", "2026-06-01T17:00:00Z", reason=""), SUP9)
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_FROZEN.value, 409)


def test_frozen_week_beats_negative_duration_edit(api):
    """PRD §2.8: "State legality comes after that ... including the frozen-timesheet
    guard (ERR_TIMESHEET_FROZEN) ... Only once these structural gates pass does the
    system evaluate the business-specific constraints — reason requirements,
    duration positivity, interval overlaps".

    A second business-constraint pairing: an edit to a frozen (APPROVED) week that
    ALSO produces a negative duration still surfaces the structural frozen-state
    error, not the duration-positivity error.

    Design: Difficulty/priority_pair_validation_conflict/frozen_state_beats_missing_reason
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    approve_week(api, week["id"], submitted["version"], SUP2)
    # CLOCK_OUT moved before clock_in (negative duration) AND the week is frozen.
    resp = api.edit_punch(punch["id"],
                          edit_punch_payload("CLOCK_OUT", "2026-06-01T07:00:00Z",
                                             reason="bad correction"), SUP9)
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_FROZEN.value, 409)


# ─── Priority-pair: invalid state beats stale version (Queue A) ──

def test_approve_draft_week_with_stale_version_reports_invalid_state(api):
    """PRD §2.8: "State legality comes after that — the target must be in a state
    that permits the requested transition (ERR_INVALID_STATE) ... Only once these
    structural gates pass does the system evaluate the business-specific constraints
    — reason requirements, duration positivity, interval overlaps, segregation of
    duties, concurrency, and generic field-level validity."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_stale_version_on_approve
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    # Approve a DRAFT (never-submitted) week with a deliberately stale version.
    # The state precondition (must be SUBMITTED) is checked before OCC.
    resp = api.approve_timesheet_week(
        week["id"], approve_week_payload(week["version"] - 1), SUP2)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_approve_already_approved_week_with_stale_version_reports_invalid_state(api):
    """PRD §2.8: "State legality comes after that — the target must be in a state
    that permits the requested transition (ERR_INVALID_STATE) ... Only once these
    structural gates pass does the system evaluate the business-specific constraints
    — reason requirements, duration positivity, interval overlaps, segregation of
    duties, concurrency, and generic field-level validity."

    From the terminal-for-this-action APPROVED state (re-approval is not a legal
    transition), a stale expected version still loses to the state check.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_stale_version_on_approve
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    approved = approve_week(api, week["id"], submitted["version"], SUP2)
    # Approve again (week is APPROVED, not SUBMITTED) with a stale version.
    resp = api.approve_timesheet_week(
        week["id"], approve_week_payload(approved["version"] - 1), SUP1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ─── Submit guard: open punch in week (Queue B) ───────

def test_submit_blocked_by_open_punch_in_week(api):
    """PRD §3.6: "Submitting requires the week to be in DRAFT (or REJECTED, for a
    resubmission) and requires that no OPEN punch exists for the employee anywhere
    inside the workweek, else the submit is rejected with ERR_OPEN_PUNCH_IN_WEEK."

    Design: Corner/state_machines/submit_blocked_by_open_punch_in_week
    """
    from test_helpers import create_open_punch
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_open_punch(api, employee["id"], worksite["id"],
                      "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z", "2026-06-01T08:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    resp = api.submit_timesheet_week(week["id"], SUP1)
    validate_error(resp, ApiErrorId.ERR_OPEN_PUNCH_IN_WEEK.value, 409)


# ─── Segregation of duties: submitter cannot approve (Queue B) ──

def test_submitter_cannot_approve_own_week(api):
    """PRD §3.8: "requires that the approver's X-User-ID differ both from
    submitted_by_user_id and from the editor_user_id of every TimeEdit applied to
    any punch in that week — an approver who submitted the week, or who edited any
    punch feeding it, is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 409)."

    Design: Corner/validations/segregation_submitter_cannot_approve
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    # Same supervisor (sup-1) who submitted attempts to approve.
    resp = api.approve_timesheet_week(
        week["id"], approve_week_payload(submitted["version"]), SUP1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)


# ─── Segregation of duties: editor cannot approve (Queue B) ──

def test_punch_editor_cannot_approve_week(api):
    """PRD §3.8: "requires that the approver's X-User-ID differ both from
    submitted_by_user_id and from the editor_user_id of every TimeEdit applied to
    any punch in that week — an approver who submitted the week, or who edited any
    punch feeding it, is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 409)."

    Design: Corner/validations/editor_cannot_approve_segregation
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    # sup-9 edits a punch in the week; sup-1 submits.
    validate_success(api.edit_punch(
        punch["id"], edit_punch_payload("CLOCK_IN", "2026-06-01T07:55:00Z",
                                        reason="early badge-in confirmed"), SUP9), 201)
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    # The editor (sup-9) — who did not submit — still cannot approve.
    resp = api.approve_timesheet_week(
        week["id"], approve_week_payload(submitted["version"]), SUP9)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)


# ─── OCC: version increments and a correct expected version succeeds (Queue B) ──

def test_occ_version_increments_on_submit_and_approve(api):
    """PRD §2.4: "The version is an integer that starts at its initial value on
    creation and increments by one on every mutation of the resource".
    PRD §3.8: "A clean approval records approved_by_user_id, advances the week
    SUBMITTED → APPROVED, and increments version."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_write
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    v_draft = week["version"]
    submitted = submit_week(api, week["id"], SUP1)
    assert_version_incremented(submitted["version"], v_draft)
    approved = approve_week(api, week["id"], submitted["version"], SUP2)
    assert approved["status"] == "APPROVED"
    assert_version_incremented(approved["version"], submitted["version"])


# ─── OCC: stale version on payroll include (Queue B) ──

def test_occ_stale_version_on_payroll_include_rejected(api):
    """PRD §3.9: "Locking requires the week to be APPROVED, requires
    expected_timesheet_week_version to match the week's current version (else
    ERR_STALE_VERSION, HTTP 412 — guarding against a late punch void having
    superseded the gross since it was observed)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_payroll_include
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    submitted = submit_week(api, week["id"], SUP1)
    approved = approve_week(api, week["id"], submitted["version"], SUP2)
    run = create_payroll_run(api, employer["id"], "2026-06-01", "2026-06-07")
    # Include with a version one behind the current (stale).
    resp = api.include_week_in_run(
        run["id"], include_week_payload(week["id"], approved["version"] - 1), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
