"""Auto-callout and offers: decline terminal lockdown, selector ranking with
the preference boost, notice-tier boundaries, the premium cap, and the
OFFERED fork's divergent cascades (decline vs accept)."""
from test_helpers import (
    ApiErrorId,
    accept_offer,
    basic_world,
    create_mark_ok,
    decline_offer,
    get_absence,
    get_school,
    get_substitute,
    make_coordinator_headers,
    make_staff,
    make_substitute_headers,
    make_teacher_headers,
    offer_assignment,
    onboard_substitute,
    report_absence,
    run_dispatch_batch,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_sub_world():
    """Subs A (registered first, rate 20000) and B (18000), both ACTIVE and
    MATH/HIGH qualified; school NONE with budget 1000000; clock 2026-07-29."""
    ctx = basic_world()
    ctx["sub_a"] = onboard_substitute(full_name="Sub A", rate_cents=20000)
    ctx["sub_b"] = onboard_substitute(full_name="Sub B", rate_cents=18000)
    return ctx


def test_assignment_terminal_lockdown_decline_then_respond(api):
    """PRD 3.4: "A decline flips the offer to `DECLINED` and immediately
    re-runs the selector: the next candidate receives a fresh offer with an
    incremented `offer_sequence`, and if the pool is empty the absence simply
    stays `DISPATCHING`."
    PRD 2.8: "The target's state machine must permit the operation, else the
    appropriate `ERR_ABSENCE_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`,
    `ERR_SUBSTITUTE_INVALID_STATE`, `ERR_CLEARANCE_INVALID_STATE`,
    `ERR_MARK_INVALID_STATE`, `ERR_COVERAGE_INVALID_STATE`,
    `ERR_TIMESHEET_INVALID_STATE`, `ERR_PAYROLL_PERIOD_INVALID_STATE`, or
    `ERR_PERFORMANCE_FLAG_INVALID_STATE` (409)."
    PRD 2.11: "no `DECLINED` or `EXPIRED` assignment exists for this absence
    and substitute — a substitute who declined or timed out is never
    re-offered the same absence."

    Design: Corner/state_machines/assignment_terminal_lockdown_decline_then_respond
    """
    ctx = basic_world()
    ctx["sub"] = onboard_substitute()
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    offer = offer_assignment(absence["id"], ctx["sub"]["id"], coord_headers)
    decline_offer(offer["id"], ctx["sub"]["id"])

    res = api.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_substitute_headers(ctx["sub"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE, expected_status=409)

    absence_after = get_absence(absence["id"])
    assert absence_after["fill_status"] == "DISPATCHING", (
        "the decline re-dispatch ran once; the only substitute declined and is "
        "never re-offered, so the absence stays DISPATCHING"
    )


def test_dispatch_preference_boost_overrides_creation_order(api, district_admin_headers):
    """PRD 2.11: "Among eligible candidates, each is scored: the rank score is
    the substitute's `reliability_trailing_score` plus a flat boost — the
    district's `preference_rank_boost`, 10 points by default — when the
    substitute holds an `ACTIVE` `PREFERRED` mark at the absence's school."
    PRD 2.11: "Candidates are ordered by rank score descending, ties broken by
    earliest substitute registration (the substitute's `created_at`,
    ascending)."

    Design: Corner/calculations/dispatch_preference_boost_overrides_creation_order
    """
    ctx = basic_world()
    onboard_substitute(full_name="Sub B", rate_cents=18000)
    sub_a = onboard_substitute(full_name="Sub A", rate_cents=20000)
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    create_mark_ok(
        ctx["school"]["id"], sub_a["id"], "PREFERRED", coord_headers, priority_rank=1
    )
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")

    batch = run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-07-29")
    assert batch["offers_created"] == 1

    data, _ = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": absence["id"], "status": "OFFERED"},
        )
    )
    assert len(data) == 1
    assert data[0]["substitute_id"] == sub_a["id"], (
        "boosted 110 (100 + 10 PREFERRED) beats 100 despite later registration"
    )
    assert data[0]["offer_sequence"] == 1


def test_premium_notice_boundaries_at_24h_and_72h(api):
    """PRD 3.4: "The notice component is the short-notice fraction when lead
    time is strictly below `short_notice_hours`, else the moderate-notice
    fraction when strictly below `moderate_notice_hours`, else zero — so an
    offer created exactly 24 hours out earns the moderate tier, and exactly 72
    hours out earns none."
    PRD 3.4: "Lead time is measured from the clock's current instant to
    midnight UTC of the absence's first day and may be negative for same-day
    callouts."

    Design: Corner/calculations/premium_notice_boundaries_at_24h_and_72h
    """
    ctx = basic_world(clock="2026-08-02T00:00:00Z")
    teacher2 = make_staff(
        ctx["school"]["id"], full_name="Teach Two", subject="MATH", grade_band="HIGH"
    )
    sub = onboard_substitute()
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    absence_a = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    absence_b = validate_success(
        api.create_absence(
            {
                "staff_member_id": teacher2["id"],
                "start_date": "2026-08-06",
                "end_date": "2026-08-06",
                "absence_type": "SICK",
                "required_subject": "MATH",
                "required_grade_band": "HIGH",
            },
            make_teacher_headers(teacher2["id"]),
        ),
        201,
    )

    offer_a = offer_assignment(absence_a["id"], sub["id"], coord_headers)
    assert offer_a["premium_multiplier_snapshot"] == 1.1, (
        "lead exactly 24h is NOT strictly below short_notice_hours: moderate tier"
    )
    assert offer_a["provisional_pay_cents"] == 22000

    set_logical_clock("2026-08-03T00:00:00Z")
    offer_b = offer_assignment(absence_b["id"], sub["id"], coord_headers)
    assert offer_b["premium_multiplier_snapshot"] == 1.0, (
        "lead exactly 72h earns no notice premium at all"
    )
    assert offer_b["provisional_pay_cents"] == 20000


def test_premium_multiplier_cap_binds_over_raw_sum(api):
    """PRD 3.4: "The snapshot multiplier is one plus the two components,
    capped at `premium_cap_multiplier`"
    PRD 3.1: "All premiums combined are hard-capped by `premium_cap_multiplier`
    — 1.50 by default, meaning pay never exceeds 150% of base no matter how
    many incentives stack."

    Design: Difficulty/combinatorial_formula/premium_multiplier_nested_cap_and_tiers
    """
    ctx = basic_world(
        district_config={"htf_high_premium_pct": 0.40},
        tier="HIGH",
        clock="2026-08-02T12:00:00Z",
    )
    sub = onboard_substitute()
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    offer = offer_assignment(absence["id"], sub["id"], coord_headers)
    assert offer["premium_multiplier_snapshot"] == 1.5, (
        "min(1.0 + 0.40 HIGH tier + 0.25 short notice, 1.50) — the cap binds, "
        "not the raw 1.65"
    )
    assert offer["provisional_pay_cents"] == 30000, "1 day x round_half_up(20000 x 1.50)"


def test_premium_multiplier_components_and_offer_identity(api):
    """PRD 3.4: "The hard-to-fill component is the district's high-tier
    fraction for a `HIGH` school, the moderate-tier fraction for a `MODERATE`
    school, and zero for `NONE`."
    PRD 3.4: "`offer_source` records the channel — `AUTO_DISPATCH` from a
    batch, `MANUAL_OFFER` from a coordinator or district admin naming an
    `absence_id` and `substitute_id`, or `SELF_CLAIM` from a substitute — and
    its `offer_sequence` is a per-absence monotonically increasing number
    starting at 1"
    PRD 3.4: "From the snapshot comes `provisional_pay_cents`:
    `scheduled_days` times the substitute's `base_daily_rate_cents` scaled by
    the snapshot multiplier, the product rounded half up to integer cents once
    per assignment"

    Design: Difficulty/combinatorial_formula/premium_multiplier_nested_cap_and_tiers
    """
    ctx = basic_world(
        district_config={"htf_high_premium_pct": 0.40},
        tier="HIGH",
        clock="2026-08-02T12:00:00Z",
    )
    sub = onboard_substitute()
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    offer = offer_assignment(absence["id"], sub["id"], coord_headers)
    assert offer["offer_source"] == "MANUAL_OFFER"
    assert offer["status"] == "OFFERED"
    assert offer["offer_sequence"] == 1
    assert offer["scheduled_days"] == 1
    assert offer["premium_multiplier_snapshot"] == 1.5
    assert offer["provisional_pay_cents"] == 30000


def test_offered_fork_decline_branch_redispatches_without_penalty(api, district_admin_headers):
    """PRD 2.11: "Candidates are ordered by rank score descending, ties broken
    by earliest substitute registration (the substitute's `created_at`,
    ascending)."
    PRD 3.4: "A decline flips the offer to `DECLINED` and immediately re-runs
    the selector: the next candidate receives a fresh offer with an
    incremented `offer_sequence`, and if the pool is empty the absence simply
    stays `DISPATCHING`. Neither declining nor expiring writes a reliability
    event."

    Design: Difficulty/non_linear_state_machine/assignment_offered_fork_divergent_cascades
    """
    ctx = _two_sub_world()
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-04")
    batch = run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-07-29")
    assert batch["offers_created"] == 1

    data, _ = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": absence["id"], "status": "OFFERED"},
        )
    )
    offer_a = data[0]
    assert offer_a["substitute_id"] == ctx["sub_a"]["id"], (
        "rank tie at trailing 100 resolves to the earliest-registered substitute"
    )
    assert offer_a["offer_sequence"] == 1

    declined = decline_offer(offer_a["id"], ctx["sub_a"]["id"])
    assert declined["status"] == "DECLINED"
    assert get_substitute(ctx["sub_a"]["id"])["reliability_trailing_score"] == 100
    assert get_absence(absence["id"])["fill_status"] == "DISPATCHING"

    data, _ = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": absence["id"], "status": "OFFERED"},
        )
    )
    assert len(data) == 1
    offer_b = data[0]
    assert offer_b["substitute_id"] == ctx["sub_b"]["id"]
    assert offer_b["offer_sequence"] == 2
    assert offer_b["offer_source"] == "AUTO_DISPATCH"


def test_offered_fork_accept_branch_commits_budget(api, district_admin_headers):
    """PRD 3.4: "A successful accept moves the offer to `ACCEPTED`, the
    absence from `DISPATCHING` to `ASSIGNED`, cancels every other `OFFERED`
    assignment on that absence with `cancel_reason` `ABSENCE_CANCEL` (no
    penalty — they simply lost the race), and adds the provisional pay into
    the school's committed budget."

    Design: Difficulty/non_linear_state_machine/assignment_offered_fork_divergent_cascades
    """
    ctx = _two_sub_world()
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-04")
    run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-07-29")

    data, _ = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": absence["id"], "status": "OFFERED"},
        )
    )
    offer_a = data[0]
    decline_offer(offer_a["id"], ctx["sub_a"]["id"])

    data, _ = validate_paginated(
        api.list_assignments(
            district_admin_headers,
            params={"absence_id": absence["id"], "status": "OFFERED"},
        )
    )
    offer_b = data[0]
    accepted = accept_offer(offer_b["id"], ctx["sub_b"]["id"])
    assert accepted["status"] == "ACCEPTED"

    assert get_absence(absence["id"])["fill_status"] == "ASSIGNED"
    school = get_school(ctx["school"]["id"])
    assert school["coverage_budget_committed_cents"] == 36000, (
        "2 scheduled days x 18000 base at premium 1.00 committed on accept"
    )
    assert school["coverage_budget_spent_cents"] == 0
    assert school["coverage_budget_available_cents"] == 1_000_000 - 36000
