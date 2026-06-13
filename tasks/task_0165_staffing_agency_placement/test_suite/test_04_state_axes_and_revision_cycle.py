"""Parallel placement status axes and the cyclic timesheet revision loop.

Translates Difficulty/non_linear_state_machine.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_active_placement,
    create_timesheet, submit_timesheet, reject_timesheet,
    make_account_manager_headers, make_candidate_headers,
)

AM = make_account_manager_headers()


def test_placement_assignment_and_conversion_axes_are_independent(api):
    """PRD 3.5: "A placement carries two independent status axes. The `assignment_status`
    axis tracks the temporary engagement, while the `conversion_status` axis (Section 3.7)
    tracks any perm conversion; neither dictates the other until a conversion forces the
    assignment to close."
    PRD 3.4: "Its `conversion_status` begins at `NONE` in all cases."
    PRD 3.7: "The `conversion_status` moves to `CONVERTED`. And the temporary engagement closes:
    the placement's `assignment_status` moves from `ACTIVE` to `ENDED`."

    Before convert: assignment_status ACTIVE coexists with conversion_status NONE. Converting a
    TEMP_TO_PERM placement then drives conversion_status -> CONVERTED and assignment_status -> ENDED.

    Design: Difficulty/non_linear_state_machine/placement_parallel_axes_independent
    """
    scen = setup_active_placement(
        client_overrides={"name": "Mercy", "conversion_fee_pct": 0.20},
        job_order_overrides={
            "title": "Nurse", "employment_type": "TEMP_TO_PERM",
            "required_skill_code": "RN", "bill_rate_cents": 9000,
            "target_pay_rate_cents": 6000, "annual_salary_cents": 10000000,
        },
        candidate_overrides={"full_name": "Nina RN", "skill_codes": ["RN"], "base_pay_rate_cents": 6000},
        skill=("RN", "CLINICAL"),
        submitted_pay_rate_cents=6000)
    pl = scen["placement"]
    before = validate_success(api.get_placement(pl["id"], scen["recruiter"]))
    assert before["assignment_status"] == "ACTIVE", f"assignment {before['assignment_status']}"
    assert before["conversion_status"] == "NONE", f"conversion {before['conversion_status']}"

    get_success_data(api.convert_placement(pl["id"], {"annual_salary_cents": 10000000}, AM))
    after = validate_success(api.get_placement(pl["id"], scen["recruiter"]))
    assert after["conversion_status"] == "CONVERTED", f"conversion {after['conversion_status']}"
    assert after["assignment_status"] == "ENDED", f"assignment {after['assignment_status']}"


def test_starting_assignment_leaves_conversion_status_untouched(api):
    """PRD 3.5: "For a `TEMP` or `TEMP_TO_PERM` placement, a `Recruiter` starts the engagement by
    advancing `assignment_status` from `PENDING_START` to `ACTIVE`."
    PRD 3.5: "neither dictates the other until a conversion forces the assignment to close."
    PRD 3.4: "Its `conversion_status` begins at `NONE` in all cases."

    A TEMP_TO_PERM placement created is PENDING_START / NONE; starting it moves assignment_status to
    ACTIVE while conversion_status stays NONE — the assignment axis moves without disturbing the
    conversion axis.

    Design: Difficulty/non_linear_state_machine/placement_parallel_axes_independent
    """
    from test_helpers import setup_offer_extended_scenario, create_placement, start_placement
    scen = setup_offer_extended_scenario(
        client_overrides={"name": "Mercy", "conversion_fee_pct": 0.20},
        job_order_overrides={
            "title": "Nurse", "employment_type": "TEMP_TO_PERM",
            "required_skill_code": "RN", "bill_rate_cents": 9000,
            "target_pay_rate_cents": 6000, "annual_salary_cents": 10000000,
        },
        candidate_overrides={"full_name": "Nina RN", "skill_codes": ["RN"], "base_pay_rate_cents": 6000},
        skill=("RN", "CLINICAL"),
        submitted_pay_rate_cents=6000)
    created = create_placement(scen["submission"]["id"], scen["jo_version"])
    assert created["assignment_status"] == "PENDING_START", f"assignment {created['assignment_status']}"
    assert created["conversion_status"] == "NONE", f"conversion {created['conversion_status']}"
    started = start_placement(created["id"])
    assert started["assignment_status"] == "ACTIVE", f"assignment {started['assignment_status']}"
    assert started["conversion_status"] == "NONE", (
        f"conversion_status must stay NONE after starting the assignment, got {started['conversion_status']}"
    )


def test_timesheet_revision_cycle_status_path(api):
    """PRD 3.6: "A `Client` then either approves or rejects a `SUBMITTED` timesheet ... rejection
    advances it to `REJECTED`. A `REJECTED` timesheet may be revised by a `Candidate` back to
    `DRAFT`, which requires it to currently be `REJECTED` (otherwise `ERR_TIMESHEET_BAD_STATE`)."
    PRD 3.6: "This rejection-and-revision forms a cycle through `SUBMITTED`, `REJECTED`, and `DRAFT`."

    DRAFT -> SUBMITTED -> REJECTED -> DRAFT walks the cycle and returns to the previously-visited
    DRAFT state.

    Design: Difficulty/non_linear_state_machine/timesheet_revision_cycle
    """
    scen = setup_active_placement()
    pl, cand = scen["placement"], scen["candidate"]
    cand_headers = make_candidate_headers(cand["id"])
    ts = create_timesheet(pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 45)
    assert ts["status"] == "DRAFT", f"created status {ts['status']}"
    submit_timesheet(ts["id"], cand["id"])
    rejected = reject_timesheet(ts["id"], scen["client"]["id"])
    assert rejected["status"] == "REJECTED", f"after reject {rejected['status']}"
    revised = get_success_data(
        api.patch_timesheet(ts["id"], {"target_status": "DRAFT", "hours": 40}, cand_headers))
    assert revised["status"] == "DRAFT", (
        f"revise should return the timesheet to the previously-visited DRAFT state, got {revised['status']}"
    )


def test_timesheet_revision_cycle_recomputes_margin(api):
    """PRD 3.6: "A `REJECTED` timesheet may be revised by a `Candidate` back to `DRAFT`, which
    requires it to currently be `REJECTED` (otherwise `ERR_TIMESHEET_BAD_STATE`); the revise
    request may carry a new `hours` value, and when it does, the timesheet's `pay_cents`,
    `bill_cents`, and `margin_cents` are recomputed. This rejection-and-revision forms a cycle
    through `SUBMITTED`, `REJECTED`, and `DRAFT`."
    PRD 3.6: "The week's `margin_cents` is the `bill_cents` minus the `pay_cents`."

    45h timesheet (margin 190000) -> SUBMITTED -> REJECTED -> revise to DRAFT with 40h ->
    SUBMITTED again. The cycle returns to a previously-visited state (SUBMITTED) and the margin
    is recomputed to 160000 (40*12000 - 40*8000).

    Design: Difficulty/non_linear_state_machine/timesheet_revision_cycle
    """
    scen = setup_active_placement()
    pl, cand = scen["placement"], scen["candidate"]
    cand_headers = make_candidate_headers(cand["id"])
    ts = create_timesheet(pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 45)
    assert ts["margin_cents"] == 190000, f"initial margin {ts['margin_cents']}"
    submit_timesheet(ts["id"], cand["id"])
    reject_timesheet(ts["id"], scen["client"]["id"])
    get_success_data(api.patch_timesheet(ts["id"], {"target_status": "DRAFT", "hours": 40}, cand_headers))
    resubmitted = get_success_data(api.patch_timesheet(ts["id"], {"target_status": "SUBMITTED"}, cand_headers))
    assert resubmitted["status"] == "SUBMITTED", f"status {resubmitted['status']}"
    assert resubmitted["margin_cents"] == 160000, (
        f"margin should be recomputed to 160000 after revising to 40h, got {resubmitted['margin_cents']}"
    )
