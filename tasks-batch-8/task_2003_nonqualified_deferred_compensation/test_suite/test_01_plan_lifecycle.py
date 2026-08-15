"""Plan setup, defaults, lifecycle (DRAFT/ACTIVE/SUSPENDED), and termination.

PRD §3.1: Plan Setup, Amendment, and Lifecycle.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock,
    assert_plan,
    create_active_plan,
    create_election,
    create_plan,
    enroll_participant,
    get_election,
    get_plan,
    is_valid_uuid,
    add_fund,
    add_window,
    submit_election,
    validate_error,
    validate_paginated,
    validate_success,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]


def test_plan_create_applies_defaults(api):
    """PRD §3.1: "`six_month_delay_enabled` (default true) controls whether the
    six-month delay for specified employees applies to separation distributions;
    `rabbi_trust_required` (default false) records whether the plan maintains a
    rabbi trust as its informal funding vehicle; `accelerate_on_cic` (default
    false) controls whether a verified change in control accelerates distribution
    of vested balances; and `separation_fraction_test` selects the
    service-fraction presumption test, defaulting to `DEFAULT_50` with
    `LIBERAL_20` as the alternative."
    PRD §3.1: "Two numeric knobs complete the configuration: `vesting_cliff_years`,
    a whole number from one to ten defaulting to three, and `processing_lag_days`,
    the administrative lag added to distribution base dates, a whole number from
    zero to ninety defaulting to thirty."
    PRD §3.1: "A newly created plan rests in `DRAFT` with `document_posture` of
    `COMPLIANT` and an `open_findings_count` of zero."

    Design: Corner/entities/plan_create_applies_defaults
    """
    payload = {
        "name": "Plan DEF",
        "effective_date": "2026-01-01",
        "distribution_events_allowed": ["SEPARATION", "FIXED_TIME"],
        "officer_comp_threshold_cents": 20000000,
    }
    created = validate_success(api.create_plan(payload, PS), 201)
    assert_plan(created)
    plan = validate_success(api.get_plan(created["id"], PS), 200)

    assert plan["six_month_delay_enabled"] is True
    assert plan["rabbi_trust_required"] is False
    assert plan["accelerate_on_cic"] is False
    assert plan["separation_fraction_test"] == "DEFAULT_50"
    assert plan["vesting_cliff_years"] == 3
    assert plan["processing_lag_days"] == 30
    assert plan["status"] == "DRAFT"
    assert plan["document_posture"] == "COMPLIANT"
    assert plan["open_findings_count"] == 0
    assert isinstance(plan["version"], int)


def test_plan_create_missing_required_returns_invalid_request(api):
    """PRD §2.8: "The request body must contain all required fields with matching
    types, valid enum members, parseable date strings, and — for any date-range
    input — a start that falls before its end. Violations surface as
    `ERR_INVALID_REQUEST` or `ERR_INVALID_DATE_RANGE`."
    PRD §3.1: "The sponsor also supplies `officer_comp_threshold_cents`, the
    positive annual-compensation threshold against which the
    `COMPENSATION_THRESHOLD` basis of specified-employee status is later judged."

    Design: Corner/entities/plan_create_missing_required_returns_invalid_request
    """
    payload = {
        "name": "Plan BAD",
        "effective_date": "2026-01-01",
        "distribution_events_allowed": ["SEPARATION"],
    }
    res = api.create_plan(payload, PS)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    data, meta = validate_paginated(api.list_plans(PS))
    assert meta["total_count"] == 0, f"no Plan row may be created, got {meta['total_count']}"
    assert data == []


def test_plan_get_not_found_returns_404(api):
    """PRD §2.8: "Resource identifiers in the path are validated left to right —
    the first missing identifier short-circuits the request with `ERR_NOT_FOUND`".

    Design: Corner/entities/plan_get_not_found_returns_404
    """
    res = api.get_plan(NON_EXISTENT_UUID, PS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_plan_create_id_version_input_ignored(api):
    """PRD §2.4: "**`id` (string):** A unique, server-minted identifier formatted
    as a UUID, with no type prefix."
    PRD §2.4: "**`version` (integer):** A system-managed integer that increments
    by exactly one on every mutation of the resource, including system-driven
    state transitions and cascade effects."

    Client-injected id/version in the create body are never echoed: the returned
    id is server-minted (not the injected sentinel) and the returned version is
    system-managed (not the injected 99).

    Design: Corner/entities/plan_create_id_version_input_ignored
    """
    injected_id = "00000000-0000-4000-8000-000000000000"
    payload = {
        "name": "Plan SYS",
        "effective_date": "2026-01-01",
        "distribution_events_allowed": ["SEPARATION"],
        "officer_comp_threshold_cents": 20000000,
        "id": injected_id,
        "version": 99,
    }
    created = validate_success(api.create_plan(payload, PS), 201)
    assert is_valid_uuid(created["id"]), "server must mint a UUID id"
    assert created["id"] != injected_id, "client-injected id must not be echoed"
    assert created["version"] != 99, "client-injected version must not be echoed"
    assert isinstance(created["version"], int)


def test_plan_suspend_blocks_child_write_and_resume_restores(api):
    """PRD §3.1: "Unless the plan is `ACTIVE`, every child write is refused with
    `ERR_PLAN_NOT_ACTIVE`: creating an election window, enrolling a participant,
    creating a notional fund, opening an account, creating or submitting a
    deferral election, posting a payroll deferral, posting a crediting run,
    creating a distribution request, establishing the rabbi trust, creating a
    specified-employee list, reporting a change in control, reporting a document
    finding, and reporting an operational failure."
    PRD §3.1: "a plan may be suspended from `ACTIVE` into `SUSPENDED` and later
    resumed back to `ACTIVE`; each of these transitions requires the matching
    source state and is otherwise rejected with `ERR_PLAN_STATE_INVALID`".

    Design: Difficulty/non_linear_state_machine/plan_suspend_resume_cycle_with_gate
    """
    plan = create_active_plan(name="Plan SR", distribution_events_allowed=["SEPARATION"])
    assert plan["status"] == "ACTIVE"

    suspended = validate_success(api.suspend_plan(plan["id"], PS), 200)
    assert suspended["status"] == "SUSPENDED"

    blocked = api.create_participant({
        "plan_id": plan["id"], "employee_ref": "EMP-SR", "hire_date": "2023-08-03",
        "initial_eligibility_date": "2026-01-05", "annual_compensation_cents": 30000000,
    }, BA)
    validate_error(blocked, "ERR_PLAN_NOT_ACTIVE", expected_status=409)

    resumed = validate_success(api.resume_plan(plan["id"], PS), 200)
    assert resumed["status"] == "ACTIVE"

    participant = validate_success(api.create_participant({
        "plan_id": plan["id"], "employee_ref": "EMP-SR", "hire_date": "2023-08-03",
        "initial_eligibility_date": "2026-01-05", "annual_compensation_cents": 30000000,
    }, BA), 201)
    assert participant["id"], "post-resume participant create returns 201 with an id"


def test_draft_plan_gates_child_write(api):
    """PRD §3.1: "Suspension is therefore a true freeze: the same gate applies
    while the plan is `SUSPENDED`, and it applies equally in `DRAFT`,
    `TERMINATION_PENDING`, and `TERMINATED`."

    A plan in DRAFT (the initial state, never activated) refuses participant
    enrollment with the same ERR_PLAN_NOT_ACTIVE gate.

    Design: Difficulty/non_linear_state_machine/plan_suspend_resume_cycle_with_gate
    """
    plan = create_plan(name="Plan DG", distribution_events_allowed=["SEPARATION"])
    assert plan["status"] == "DRAFT"

    blocked = api.create_participant({
        "plan_id": plan["id"], "employee_ref": "EMP-DG", "hire_date": "2023-08-03",
        "initial_eligibility_date": "2026-01-05", "annual_compensation_cents": 30000000,
    }, BA)
    validate_error(blocked, "ERR_PLAN_NOT_ACTIVE", expected_status=409)

    activated = validate_success(api.activate_plan(plan["id"], PS), 200)
    assert activated["status"] == "ACTIVE"
    participant = validate_success(api.create_participant({
        "plan_id": plan["id"], "employee_ref": "EMP-DG", "hire_date": "2023-08-03",
        "initial_eligibility_date": "2026-01-05", "annual_compensation_cents": 30000000,
    }, BA), 201)
    assert participant["status"] == "ACTIVE"


def test_plan_terminate_voids_unlocked_elections(api):
    """PRD §3.1: "The `PlanSponsor` initiates termination from `ACTIVE` or
    `SUSPENDED` — from any other state the attempt is rejected with
    `ERR_PLAN_STATE_INVALID` — whereupon the plan moves to `TERMINATION_PENDING`,
    its `termination_effective_date` is set to the current clock date plus twelve
    calendar months (that field stays null until termination begins), and every
    deferral election of the plan still resting in `DRAFT` or `SUBMITTED` is
    voided."
    PRD §3.1: "When the logical clock later reaches the
    `termination_effective_date`, the scheduled sweep moves the plan from
    `TERMINATION_PENDING` to its terminal `TERMINATED` state."

    Design: Corner/state_machines/plan_terminate_voids_unlocked_elections
    """
    plan = create_active_plan(name="Plan TM", distribution_events_allowed=["SEPARATION"])
    fund = add_fund(plan["id"])
    window1 = add_window(plan["id"], plan_year=2027,
                         general_open_date="2026-10-01", general_close_date="2026-12-31")
    window2 = add_window(plan["id"], plan_year=2028,
                         general_open_date="2027-10-01", general_close_date="2027-12-31")
    p1 = enroll_participant(plan["id"], employee_ref="EMP-T1")
    p2 = enroll_participant(plan["id"], employee_ref="EMP-T2")

    advance_clock("2026-10-15T00:00:00Z")
    e1 = create_election(p1["id"], window1["id"], fund["id"], deferral_percent_bp=5000)
    submit_election(e1["id"], p1["id"])
    advance_clock("2027-01-01T00:00:00Z")  # window1 closes -> e1 LOCKED
    assert get_election(e1["id"])["status"] == "LOCKED"

    advance_clock("2027-10-15T00:00:00Z")  # window2 OPEN
    e2 = create_election(p2["id"], window2["id"], fund["id"], deferral_percent_bp=2500)
    submit_election(e2["id"], p2["id"])
    assert get_election(e2["id"])["status"] == "SUBMITTED"

    terminated = validate_success(api.terminate_plan(plan["id"], PS), 200)
    assert terminated["status"] == "TERMINATION_PENDING"
    assert terminated["termination_effective_date"] == "2028-10-15", (
        "clock date 2027-10-15 plus twelve calendar months"
    )

    assert get_election(e2["id"])["status"] == "VOIDED", "SUBMITTED election voided by termination"
    assert get_election(e1["id"])["status"] == "LOCKED", "LOCKED elections survive termination"

    advance_clock("2028-10-16T00:00:00Z")  # past the termination effective date
    final_plan = get_plan(plan["id"])
    assert final_plan["status"] == "TERMINATED"
