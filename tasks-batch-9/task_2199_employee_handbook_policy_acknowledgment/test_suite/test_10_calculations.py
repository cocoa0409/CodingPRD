"""Pinned constants and evaluation orders: tier ladder, ack clamps, retention horizon."""
from test_helpers import (
    api_client,
    assert_same_instant,
    assignments_of,
    make_admin_headers,
    refresh_assignment,
    refresh_case,
    set_clock,
    setup_open_escalation_case,
    sweep,
    validate_paginated,
)


def test_tier_ladder_lower_edges_are_inclusive_at_six_seven_and_fourteen_days():
    """PRD §3.8: "A base tier of 1 applies when the days overdue is at least 1 and
    fewer than 7; a base tier of 2 applies when it is at least 7 and fewer than 14; a
    base tier of 3 applies at 14 or more. So 13 days overdue is base tier 2, exactly 7
    days overdue is already base tier 2 rather than 1, and exactly 14 days overdue is
    already base tier 3 rather than 2." ... "The same checkpoint recomputes `tier` for
    every existing case whose `status` is `OPEN` or `NOTIFIED`".

    Design: Corner/calculations/corner_escalation_tier_thresholds_at_six_seven_and_fourteen_days
    """
    ctx = setup_open_escalation_case(
        clock_to="2026-09-17T00:00:00Z",
        jurisdiction={"ack_deadline_days": 10, "min_legal_review_days": 5},
        effective_date="2026-09-01T00:00:00Z",
    )
    assignment, case = ctx["assignment"], ctx["case"]
    assert_same_instant(
        refresh_assignment(assignment["id"])["due_date"],
        "2026-09-11T00:00:00.000Z",
        "due_date",
    )

    for clock, expected_overdue, expected_tier in (
        ("2026-09-17T00:00:00Z", 6, 1),
        ("2026-09-18T00:00:00Z", 7, 2),
        ("2026-09-25T00:00:00Z", 14, 3),
    ):
        set_clock(clock)
        sweep()
        row = refresh_assignment(assignment["id"])
        assert row["days_overdue"] == expected_overdue, (
            f"at the {clock} clock a due_date of 2026-09-11 is {expected_overdue} "
            f"whole days overdue, got {row['days_overdue']}"
        )
        current = refresh_case(case["id"])
        assert current["tier"] == expected_tier, (
            f"{expected_overdue} days overdue is tier {expected_tier}, got "
            f"{current['tier']}"
        )
        assert current["status"] == "OPEN", (
            f"re-tiering must leave the case OPEN, got {current['status']}"
        )
        assert row["escalation_state"] == "ESCALATING", (
            f"the escalation dimension stays ESCALATING, got {row['escalation_state']}"
        )

    rows, meta = validate_paginated(
        api_client.list_escalations(
            make_admin_headers(),
            params={"assignment_id": assignment["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        "three sweeps must re-tier the same case rather than open new ones, got "
        f"{meta['total_count']}"
    )
    assert rows[0]["id"] == case["id"]


def test_accessibility_floor_is_raised_first_and_the_safety_cap_overrides_it():
    """PRD §3.7: "Start with the smaller of the assignment jurisdiction's
    `ack_deadline_days` and the owning document's `max_ack_deadline_days`. Second, if
    the assignee's `employment_status` is `ON_LEAVE`, add 14 days ... Third, if the
    assignee's `needs_accessible_format` is true, raise the figure to at least 21
    days, which is three weeks and acts as a floor rather than an addition. Fourth, if
    the owning document's `category` is `SAFETY`, cap the figure at 7 days, a hard
    one-week ceiling that overrides the accessibility floor because it is applied
    last."

    Design: Corner/calculations/corner_ack_due_clamp_constants_and_their_pinned_order
    """
    from test_helpers import (
        add_approved_version_to_document,
        new_document,
        new_employee,
        new_jurisdiction,
        new_reviewer,
        refresh_employee,
        released_package_for,
    )

    jurisdiction = new_jurisdiction(ack_deadline_days=10, min_legal_review_days=5)
    reviewer = new_reviewer(jurisdiction["id"])
    accessible = new_employee(jurisdiction["id"], needs_accessible_format=True)
    standard = new_employee(jurisdiction["id"], needs_accessible_format=False)

    conduct = new_document(category="CODE_OF_CONDUCT")
    safety = new_document(category="SAFETY")
    v_conduct = add_approved_version_to_document(
        conduct, jurisdiction["id"], reviewer["id"]
    )
    v_safety = add_approved_version_to_document(
        safety, jurisdiction["id"], reviewer["id"]
    )

    package = released_package_for(
        [v_conduct["id"], v_safety["id"]],
        [jurisdiction["id"]],
        "2026-09-01T00:00:00Z",
    )
    assert package["roster_snapshot_size"] == 4, (
        "two employees times two item versions mints four assignments, got "
        f"{package['roster_snapshot_size']}"
    )

    def _due(employee_id, policy_version_id):
        rows = assignments_of(
            release_package_id=package["id"],
            employee_id=employee_id,
            policy_version_id=policy_version_id,
        )
        assert len(rows) == 1, f"expected exactly 1 assignment, got {len(rows)}"
        assert_same_instant(
            rows[0]["window_start_date"], "2026-09-01T00:00:00.000Z", "window_start_date"
        )
        return rows[0]["due_date"]

    assert_same_instant(
        _due(accessible["id"], v_conduct["id"]),
        "2026-09-22T00:00:00.000Z",
        "accessible employee on a CODE_OF_CONDUCT policy: 10 raised to the 21-day floor",
    )
    assert_same_instant(
        _due(accessible["id"], v_safety["id"]),
        "2026-09-08T00:00:00.000Z",
        "accessible employee on a SAFETY policy: the 21-day floor then cut to the "
        "7-day cap applied last",
    )
    assert_same_instant(
        _due(standard["id"], v_conduct["id"]),
        "2026-09-11T00:00:00.000Z",
        "standard employee on a CODE_OF_CONDUCT policy: the raw 10 days",
    )
    assert_same_instant(
        _due(standard["id"], v_safety["id"]),
        "2026-09-08T00:00:00.000Z",
        "standard employee on a SAFETY policy: 10 capped at 7",
    )

    for employee in (accessible, standard):
        assert refresh_employee(employee["id"])["open_ack_count"] == 2, (
            "each employee carries two fresh obligations, got "
            f"{refresh_employee(employee['id'])['open_ack_count']}"
        )


def test_retention_horizon_takes_the_dominating_calendar_year_candidate():
    """PRD §3.7: "The calendar base is the row's `retained_from` advanced by the
    governing jurisdiction's `retention_years` whole calendar years, landing on the
    same month and day ... The dispute floor is the row's `retained_from` advanced by
    1095 days, which is the three-year minimum the company holds evidence for
    regardless of state law. `retention_until` is whichever of the two is later. The
    governing jurisdiction is the one named by the retention row's own
    `jurisdiction_id`, snapshotted from the assignment".

    Design: Corner/calculations/corner_retention_until_takes_the_dominating_calendar_year_branch
    """
    from test_helpers import (
        acknowledge,
        assert_append_only_fields,
        retention_rows_for,
        setup_released_scenario,
    )

    ctx = setup_released_scenario(
        jurisdiction={
            "retention_years": 7,
            "ack_deadline_days": 30,
            "min_legal_review_days": 5,
        },
        effective_date="2026-09-01T00:00:00Z",
    )
    assert ctx["jurisdiction"]["retention_years"] == 7

    ack = acknowledge(ctx["assignment"], ctx["employee"]["id"])
    assert ack["status"] == "EFFECTIVE"
    assert_same_instant(ack["captured_at"], "2026-09-01T00:00:00.000Z", "captured_at")

    rows = retention_rows_for(ctx["employee"]["id"])
    assert len(rows) == 1, f"one capture appends exactly one retention row, got {len(rows)}"
    row = rows[0]
    assert_append_only_fields(row)
    assert row["record_kind"] == "CAPTURE", (
        f"a capture appends a CAPTURE row, got {row['record_kind']}"
    )
    assert row["signed_delta"] == 1, (
        f"a CAPTURE row carries signed_delta +1, got {row['signed_delta']}"
    )
    assert_same_instant(row["retained_from"], "2026-09-01T00:00:00.000Z", "retained_from")
    assert_same_instant(
        row["retention_until"],
        "2033-09-01T00:00:00.000Z",
        "retention_until must be the 7 calendar years candidate, which is later than "
        "the 1095-day dispute floor",
    )
    assert row["jurisdiction_id"] == ctx["jurisdiction"]["id"], (
        "the governing jurisdiction is snapshotted from the assignment, got "
        f"{row['jurisdiction_id']}"
    )
    assert row["legal_hold"] is False, (
        f"a freshly appended retention row is not under legal hold, got {row['legal_hold']}"
    )


def test_due_date_freezes_the_mint_instant_inputs_and_the_sweep_skips_undelivered():
    """PRD §3.7: "if the assignee's `employment_status` is `ON_LEAVE`, add 14 days"
    ... "The inputs are the jurisdiction of the assignment, the document of the
    assignment's version, and the assignee's `employment_status` and
    `needs_accessible_format` as of the mint instant."  PRD §3.8: "Assignments whose
    `ack_state` is anything other than `PENDING` are excluded from the sweep
    entirely."

    Design: Corner/calculations/corner_input_sets_are_frozen_at_mint_and_filtered_by_ack_state
    """
    from test_helpers import deliver, patch_employee, setup_released_scenario

    ctx = setup_released_scenario(
        employee={"employment_status": "ON_LEAVE"},
        jurisdiction={"ack_deadline_days": 10, "min_legal_review_days": 5},
        effective_date="2026-09-01T00:00:00Z",
        deliver=False,
    )
    assignment = ctx["assignment"]
    assert assignment["ack_state"] == "UNDELIVERED"
    assert_same_instant(
        assignment["due_date"],
        "2026-09-25T00:00:00.000Z",
        "an ON_LEAVE assignee gets 10 + 14 = 24 days from 2026-09-01",
    )

    patch_employee(ctx["employee"]["id"], employment_status="ACTIVE")
    assert_same_instant(
        refresh_assignment(assignment["id"])["due_date"],
        "2026-09-25T00:00:00.000Z",
        "the frozen mint-instant input must not be re-read, so the due_date stays",
    )

    set_clock("2026-09-30T00:00:00Z")
    opened = sweep()
    assert opened == [], (
        f"an UNDELIVERED assignment is outside the sweep's input set, got {opened}"
    )
    _rows, meta = validate_paginated(
        api_client.list_escalations(
            make_admin_headers(),
            params={"assignment_id": assignment["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 0, (
        f"no case may be opened while the row is UNDELIVERED, got {meta['total_count']}"
    )
    assert refresh_assignment(assignment["id"])["escalation_state"] == "NONE"

    delivered = deliver(assignment["id"])
    assert delivered["ack_state"] == "PENDING", (
        f"delivery moves the row to PENDING, got {delivered['ack_state']}"
    )
    assert_same_instant(delivered["delivered_at"], "2026-09-30T00:00:00.000Z", "delivered_at")

    cases = sweep()
    assert len(cases) == 1, (
        f"the now-PENDING overdue row must open exactly one case, got {len(cases)}"
    )
    assert cases[0]["tier"] == 1, (
        "5 days overdue falls in the [1,7) band, which is tier 1, got "
        f"{cases[0]['tier']}"
    )
    row = refresh_assignment(assignment["id"])
    assert row["days_overdue"] == 5, (
        "a due_date of 2026-09-25 read at 2026-09-30 is 5 whole days overdue, got "
        f"{row['days_overdue']}"
    )
    assert row["escalation_state"] == "ESCALATING", (
        f"the sweep moves the escalation dimension, got {row['escalation_state']}"
    )
